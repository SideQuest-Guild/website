"""A queued/running/finished gear-swap sim job, run through the wowsims/forever CLI.

Requested from the bot's ``#sim`` forum and claimed one at a time per pod by the sim runner
(``api/src/sidequest_api/domain/sims/runner.py``). Finished rows (``done`` or ``failed``) older than 7 days are
deleted by the runner; see ``website/src/pages/privacy/index.astro``.
"""

from datetime import datetime  # SQLAlchemy resolves Mapped[] annotations at runtime

from advanced_alchemy.base import UUIDAuditBase
from advanced_alchemy.types import DateTimeUTC, JsonB
from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class SimJob(UUIDAuditBase):
    """One sim request: the request body, its status, and its result once done."""

    __tablename__ = "sim_job"
    __table_args__ = {
        "comment": (
            "Gear-swap sim jobs run through the wowsims/forever CLI, requested by the bot's #sim forum. "
            "Finished rows are deleted after 7 days."
        )
    }

    request: Mapped[dict] = mapped_column(JsonB, doc="The SimRequest body, as the bot sent it.")
    status: Mapped[str] = mapped_column(
        String(20), default="queued", index=True, doc="queued, running, done, or failed."
    )
    result: Mapped[dict | None] = mapped_column(JsonB, default=None, doc="The SimResult body, once status is done.")
    error: Mapped[str | None] = mapped_column(Text, default=None, doc="A plain-English failure reason, if failed.")
    requested_by: Mapped[str | None] = mapped_column(
        String(32), default=None, index=True, doc="The Discord user id that asked for this sim, for rate limiting."
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), default=None, doc="When the runner claimed this job."
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTimeUTC(timezone=True), default=None, doc="When this job reached done or failed."
    )
    requeued: Mapped[bool] = mapped_column(
        Boolean, default=False, doc="Whether this job was already once requeued after running too long."
    )
