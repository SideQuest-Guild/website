"""Background sim runner: claims queued ``SimJob`` rows one at a time per pod and runs them through ``wowsimcli``.

Started in ``create_app``'s lifespan as one asyncio task per web process. ``SELECT ... FOR UPDATE SKIP LOCKED`` on
Postgres lets two pods run the loop without double-claiming a job; SQLite (tests) has no ``SKIP LOCKED``, so the
claim there is a plain conditional read-then-write (fine: tests run one process, never two pods racing).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from sidequest_api.domain.characters.services import CharactersService
from sidequest_api.domain.sims import engine
from sidequest_api.domain.sims.services import prepare_sim, run_sim
from sidequest_api.lib.game_data import GAME_DATA_STATE_KEY
from sidequest_api.lib.wowsims import wowsimcli_path
from sidequest_common.models import SimJob
from sidequest_common.schemas import SimRequest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path

    from litestar import Litestar
    from sqlalchemy.ext.asyncio import AsyncSession
    from wow import AsyncClient

logger = logging.getLogger(__name__)

POLL_SECONDS = 2
SHUTDOWN_GRACE_SECONDS = 5
STUCK_AFTER = timedelta(minutes=10)
RETENTION = timedelta(days=7)
CLEANUP_EVERY = timedelta(minutes=30)


async def _claim_next(session: AsyncSession, *, dialect: str) -> SimJob | None:
    """Claim the oldest queued job, or ``None``."""
    statement = select(SimJob).where(SimJob.status == "queued").order_by(SimJob.created_at).limit(1)
    if dialect == "postgresql":
        statement = statement.with_for_update(skip_locked=True)
    job = (await session.execute(statement)).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.started_at = datetime.now(UTC)
    await session.commit()
    return job


async def _requeue_stuck(session: AsyncSession) -> None:
    """A running job stuck past ``STUCK_AFTER`` is requeued once; stuck again after that, it fails."""
    cutoff = datetime.now(UTC) - STUCK_AFTER
    stuck = (
        (await session.execute(select(SimJob).where(SimJob.status == "running", SimJob.started_at < cutoff)))
        .scalars()
        .all()
    )
    for job in stuck:
        if job.requeued:
            job.status = "failed"
            job.error = "This sim ran too long twice in a row and was stopped."
            job.finished_at = datetime.now(UTC)
        else:
            job.requeued = True
            job.status = "queued"
            job.started_at = None
    if stuck:
        await session.commit()


async def _delete_old(session: AsyncSession) -> None:
    """Finished jobs (``done``/``failed``) older than ``RETENTION`` are deleted."""
    cutoff = datetime.now(UTC) - RETENTION
    await session.execute(delete(SimJob).where(SimJob.status.in_(("done", "failed")), SimJob.finished_at < cutoff))
    await session.commit()


async def _run_one(
    job: SimJob, session: AsyncSession, *, wowsims_dir: Path, wowsimcli: Path, game_data: AsyncClient | None
) -> None:
    request = SimRequest.model_validate(job.request)
    characters_service = CharactersService(session=session)
    try:
        if game_data is None:
            msg = "Battle.net is not configured"
            raise engine.SimEngineError(msg)  # noqa: TRY301
        prepared = await prepare_sim(
            request, characters_service=characters_service, game_data=game_data, wowsims_dir=wowsims_dir
        )
        result = await run_sim(prepared, request, wowsims_dir=wowsims_dir, wowsimcli=wowsimcli)
    except engine.SimEngineError as exc:
        job.status = "failed"
        job.error = str(exc)
    else:
        job.status = "done"
        job.result = result.model_dump(mode="json")
    job.finished_at = datetime.now(UTC)
    await session.commit()


async def _pause(stop: asyncio.Event) -> None:
    """Wait ``POLL_SECONDS``, or less if the app is stopping."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), POLL_SECONDS)


async def _loop(
    session_maker: Callable[[], AsyncSession],
    app: Litestar,
    stop: asyncio.Event,
    *,
    wowsims_dir: Path,
    dialect: str,
) -> None:
    wowsimcli = wowsimcli_path(wowsims_dir)
    last_cleanup = datetime.min.replace(tzinfo=UTC)
    while not stop.is_set():
        try:
            async with session_maker() as session:
                if datetime.now(UTC) - last_cleanup > CLEANUP_EVERY:
                    await _requeue_stuck(session)
                    await _delete_old(session)
                    last_cleanup = datetime.now(UTC)
                job = await _claim_next(session, dialect=dialect)
            if job is None:
                await _pause(stop)
                continue
            game_data = app.state.get(GAME_DATA_STATE_KEY)
            async with session_maker() as session:
                claimed = await session.get(SimJob, job.id)
                if claimed is not None:
                    await _run_one(claimed, session, wowsims_dir=wowsims_dir, wowsimcli=wowsimcli, game_data=game_data)
        except Exception:
            logger.exception("sim runner iteration failed")
            await _pause(stop)


def sim_runner_lifespan(
    session_maker: Callable[[], AsyncSession], *, wowsims_dir: Path, dialect: str, enabled: bool = True
) -> Callable[[Litestar], AbstractAsyncContextManager[None]]:
    """Run queued sims in the background while the app is up, if ``enabled`` and the CLI is installed.

    On shutdown the loop finishes its current step and exits (sessions close cleanly); a sim still running after
    ``SHUTDOWN_GRACE_SECONDS`` is cancelled, and its job, left ``running``, is requeued by the next pod's cleanup.
    """

    @asynccontextmanager
    async def lifespan(app: Litestar) -> AsyncIterator[None]:
        if not enabled:
            yield
            return
        if not wowsimcli_path(wowsims_dir).exists():
            logger.warning("sim runner off: no wowsimcli in %s", wowsims_dir)
            yield
            return
        stop = asyncio.Event()
        task = asyncio.create_task(_loop(session_maker, app, stop, wowsims_dir=wowsims_dir, dialect=dialect))
        try:
            yield
        finally:
            stop.set()
            try:
                await asyncio.wait_for(task, SHUTDOWN_GRACE_SECONDS)
            except TimeoutError:
                logger.warning("sim runner: a sim was still running at shutdown; its job will be requeued")

    return lifespan
