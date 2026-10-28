"""Raid, signup, and raid-chart persistence and queries."""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from advanced_alchemy.exceptions import IntegrityError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from advanced_alchemy.service import SQLAlchemyAsyncRepositoryService
from litestar.exceptions import HTTPException, NotFoundException, ValidationException
from litestar.status_codes import HTTP_409_CONFLICT
from sqlalchemy import func, or_, select

from sidequest_api.lib.discord import avatar_url
from sidequest_common.models import DiscordEventTombstone, Member, Raid, RaidSignup
from sidequest_common.schemas import (
    RaidChartUpdate,
    RaidCounts,
    RaidCreate,
    RaidDetail,
    RaidSummary,
    RaidUpdate,
    Signup,
    SignupUpsert,
)

if TYPE_CHECKING:
    from uuid import UUID

UPCOMING_LOOKBACK = timedelta(hours=6)
PAST_LIMIT = 50


def _raid_summary_fields(raid: Raid) -> dict[str, object]:
    return {
        "id": raid.id,
        "title": raid.title,
        "instance": raid.instance,
        "starts_at": raid.starts_at,
        "ends_at": raid.ends_at,
        "size": raid.size,
        "status": raid.status,
        "notes": raid.notes,
    }


def _to_signup_schema(signup: RaidSignup, member: Member) -> Signup:
    member_avatar = avatar_url(member.discord_id, member.avatar_hash)
    return Signup.model_validate(
        {
            "id": signup.id,
            "member": {"display_name": member.display_name, "avatar_url": member_avatar},
            "character": signup.character,
            "class": signup.wow_class,
            "role": signup.role,
            "status": signup.status,
            "comment": signup.comment,
            "group": signup.raid_group,
            "bench": signup.bench,
            "updated_at": signup.updated_at,
        }
    )


def _counts_from_rows(rows: list[tuple[str, str, int]]) -> RaidCounts:
    """``rows`` are ``(role, status, count)`` for one raid. tank/healer/dps only count ``signed``."""
    tank = healer = dps = tentative = absent = 0
    for role, status, count in rows:
        if status == "tentative":
            tentative += count
        elif status == "absent":
            absent += count
        elif status == "signed":
            if role == "tank":
                tank += count
            elif role == "healer":
                healer += count
            elif role == "dps":
                dps += count
    return RaidCounts(tank=tank, healer=healer, dps=dps, tentative=tentative, absent=absent)


class RaidsRepository(SQLAlchemyAsyncRepository[Raid]):
    """Raid persistence."""

    model_type = Raid


class RaidsService(SQLAlchemyAsyncRepositoryService[Raid]):
    """Raid CRUD plus the read-side views (list with headcounts, detail with roster)."""

    repository_type = RaidsRepository

    async def list_summaries(self, when: Literal["upcoming", "past"]) -> list[RaidSummary]:
        """Raids for the given window, with headcounts. Upcoming is ascending; past is descending, limit 50."""
        session = self.repository.session
        statement = select(Raid)
        cutoff = datetime.now(UTC) - UPCOMING_LOOKBACK
        if when == "upcoming":
            statement = statement.where(Raid.starts_at >= cutoff, Raid.status != "completed").order_by(
                Raid.starts_at.asc()
            )
        else:
            statement = (
                statement.where(or_(Raid.starts_at < cutoff, Raid.status == "completed"))
                .order_by(Raid.starts_at.desc())
                .limit(PAST_LIMIT)
            )
        raids = list((await session.execute(statement)).scalars().all())
        counts = await self._counts_for([raid.id for raid in raids])
        return [RaidSummary.model_validate({**_raid_summary_fields(raid), "counts": counts[raid.id]}) for raid in raids]

    async def get_detail(self, raid_id: UUID, *, viewer: Member | None) -> RaidDetail:
        """A raid with its full roster and the viewer's own signup (``None`` if anonymous or not signed up)."""
        raid = await self.get_raid_or_404(raid_id)
        session = self.repository.session
        statement = (
            select(RaidSignup, Member)
            .join(Member, RaidSignup.member_id == Member.id)
            .where(RaidSignup.raid_id == raid_id)
        )
        rows = (await session.execute(statement)).all()
        signups = [_to_signup_schema(signup, member) for signup, member in rows]
        my_signup = None
        if viewer is not None:
            own = next(((signup, member) for signup, member in rows if member.id == viewer.id), None)
            if own is not None:
                my_signup = _to_signup_schema(*own)
        counts = (await self._counts_for([raid_id]))[raid_id]
        return RaidDetail.model_validate(
            {**_raid_summary_fields(raid), "counts": counts, "signups": signups, "my_signup": my_signup}
        )

    async def get_raid_or_404(self, raid_id: UUID) -> Raid:
        """The raid, or 404."""
        raid = await self.get_one_or_none(id=raid_id)
        if raid is None:
            msg = f"No raid {raid_id}"
            raise NotFoundException(msg)
        return raid

    async def create_raid(self, data: RaidCreate) -> Raid:
        """Create a scheduled raid."""
        raid = Raid(
            title=data.title,
            instance=data.instance,
            starts_at=data.starts_at,
            ends_at=data.ends_at,
            size=data.size,
            notes=data.notes,
        )
        return await self.create(raid, auto_commit=True)

    async def update_raid(self, raid_id: UUID, data: RaidUpdate) -> Raid:
        """Apply the present fields of ``data``. 400 if the resulting ``ends_at`` isn't after ``starts_at``."""
        raid = await self.get_raid_or_404(raid_id)
        changes = data.model_dump(exclude_unset=True)
        starts_at = changes.get("starts_at", raid.starts_at)
        ends_at = changes.get("ends_at", raid.ends_at)
        if ends_at is not None and ends_at <= starts_at:
            msg = "ends_at must be after starts_at"
            raise ValidationException(msg)
        for field, value in changes.items():
            setattr(raid, field, value)
        return await self.update(raid, auto_commit=True)

    async def delete_raid(self, raid_id: UUID) -> None:
        """Delete a raid and its signups; tombstone a linked Discord event in the same transaction."""
        raid = await self.get_raid_or_404(raid_id)
        if raid.discord_event_id is not None:
            self.repository.session.add(DiscordEventTombstone(discord_event_id=raid.discord_event_id))
        await self.delete(raid_id, auto_commit=True)

    async def _counts_for(self, raid_ids: list[UUID]) -> dict[UUID, RaidCounts]:
        if not raid_ids:
            return {}
        session = self.repository.session
        statement = (
            select(RaidSignup.raid_id, RaidSignup.role, RaidSignup.status, func.count())
            .where(RaidSignup.raid_id.in_(raid_ids))
            .group_by(RaidSignup.raid_id, RaidSignup.role, RaidSignup.status)
        )
        rows_by_raid: dict[UUID, list[tuple[str, str, int]]] = {raid_id: [] for raid_id in raid_ids}
        for raid_id, role, status, count in (await session.execute(statement)).all():
            rows_by_raid[raid_id].append((role, status, count))
        return {raid_id: _counts_from_rows(rows) for raid_id, rows in rows_by_raid.items()}


class RaidSignupsRepository(SQLAlchemyAsyncRepository[RaidSignup]):
    """RaidSignup persistence."""

    model_type = RaidSignup


class RaidSignupsService(SQLAlchemyAsyncRepositoryService[RaidSignup]):
    """Member signups and the officer raid chart (group/bench placement)."""

    repository_type = RaidSignupsRepository

    async def upsert_signup(self, raid_id: UUID, member: Member, data: SignupUpsert) -> Signup:
        """Create or replace the member's signup for ``raid_id``. 409 if the raid isn't scheduled."""
        session = self.repository.session
        raid = await session.get(Raid, raid_id)
        if raid is None:
            msg = f"No raid {raid_id}"
            raise NotFoundException(msg)
        if raid.status != "scheduled":
            msg = "Raid is not open for signups"
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg)
        existing = await self.get_one_or_none(raid_id=raid_id, member_id=member.id)
        fields = {
            "character": data.character,
            "wow_class": data.wow_class.value,
            "role": data.role.value,
            "status": data.status.value,
            "comment": data.comment,
        }
        if existing is None:
            try:
                signup = await self.create(RaidSignup(raid_id=raid_id, member_id=member.id, **fields), auto_commit=True)
            except IntegrityError as exc:
                msg = "Signup conflict"
                raise HTTPException(status_code=HTTP_409_CONFLICT, detail=msg) from exc
        else:
            for field, value in fields.items():
                setattr(existing, field, value)
            signup = await self.update(existing, auto_commit=True)
        return _to_signup_schema(signup, member)

    async def delete_for_member(self, raid_id: UUID, member: Member) -> None:
        """Remove the member's signup for ``raid_id``, if any."""
        existing = await self.get_one_or_none(raid_id=raid_id, member_id=member.id)
        if existing is not None:
            await self.delete(existing.id, auto_commit=True)

    async def update_chart(self, raid_id: UUID, signup_id: UUID, data: RaidChartUpdate) -> Signup:
        """Place a signup on the raid chart (group 1-8) or the bench."""
        session = self.repository.session
        row = (
            await session.execute(
                select(RaidSignup, Member)
                .join(Member, RaidSignup.member_id == Member.id)
                .where(RaidSignup.id == signup_id, RaidSignup.raid_id == raid_id)
            )
        ).first()
        if row is None:
            msg = f"No signup {signup_id} on raid {raid_id}"
            raise NotFoundException(msg)
        signup, member = row
        changes = data.model_dump(exclude_unset=True)
        if "group" in changes:
            signup.raid_group = changes["group"]
        if "bench" in changes:
            signup.bench = changes["bench"]
        signup = await self.update(signup, auto_commit=True)
        return _to_signup_schema(signup, member)
