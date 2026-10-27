"""Raid and signup endpoints: public read, member signup, officer manage (including the raid chart).

Member/officer gating is dependency-based (``current_member``/``current_officer``, registered app-wide in
``create_app``): declaring the parameter resolves it, raising 401/403 before the handler body runs.
"""

from typing import Literal
from uuid import UUID

from litestar import Controller, delete, get, patch, post, put
from litestar.di import NamedDependency, Provide
from litestar.params import FromPath, FromQuery, JSONBody

from sidequest_api.domain.raids.dependencies import provide_raid_signups_service, provide_raids_service
from sidequest_api.domain.raids.services import RaidSignupsService, RaidsService
from sidequest_api.lib.member_auth import provide_optional_member
from sidequest_common.models import Member
from sidequest_common.schemas import (
    RaidChartUpdate,
    RaidCreate,
    RaidDetail,
    RaidSummary,
    RaidUpdate,
    Signup,
    SignupUpsert,
)


class RaidsController(Controller):
    """``/api/raids``."""

    path = "/api/raids"
    tags = ["Raids"]
    dependencies = {
        "raids_service": Provide(provide_raids_service),
        "raid_signups_service": Provide(provide_raid_signups_service),
        "optional_member": Provide(provide_optional_member),
    }

    @get("/", operation_id="ListRaids")
    async def list_raids(
        self,
        raids_service: NamedDependency[RaidsService],
        when: FromQuery[Literal["upcoming", "past"]] = "upcoming",
    ) -> list[RaidSummary]:
        """Raids for the given window (default ``upcoming``)."""
        return await raids_service.list_summaries(when)

    @get("/{raid_id:uuid}", operation_id="GetRaid")
    async def get_raid(
        self,
        raid_id: FromPath[UUID],
        raids_service: NamedDependency[RaidsService],
        optional_member: NamedDependency[Member | None],
    ) -> RaidDetail:
        """A raid with its full roster. ``my_signup`` is the caller's own signup, if any."""
        return await raids_service.get_detail(raid_id, viewer=optional_member)

    @put("/{raid_id:uuid}/signup", operation_id="UpsertSignup")
    async def upsert_signup(
        self,
        raid_id: FromPath[UUID],
        data: JSONBody[SignupUpsert],
        raid_signups_service: NamedDependency[RaidSignupsService],
        current_member: NamedDependency[Member],
    ) -> Signup:
        """Create or replace the caller's signup (member). 409 if the raid isn't scheduled."""
        return await raid_signups_service.upsert_signup(raid_id, current_member, data)

    @delete("/{raid_id:uuid}/signup", operation_id="DeleteSignup")
    async def delete_signup(
        self,
        raid_id: FromPath[UUID],
        raid_signups_service: NamedDependency[RaidSignupsService],
        current_member: NamedDependency[Member],
    ) -> None:
        """Remove the caller's signup, if any (member)."""
        await raid_signups_service.delete_for_member(raid_id, current_member)

    @post("/", operation_id="CreateRaid", status_code=201)
    async def create_raid(
        self,
        data: JSONBody[RaidCreate],
        raids_service: NamedDependency[RaidsService],
        current_officer: NamedDependency[Member],
    ) -> RaidDetail:
        """Schedule a new raid (officer)."""
        del current_officer
        raid = await raids_service.create_raid(data)
        return await raids_service.get_detail(raid.id, viewer=None)

    @patch("/{raid_id:uuid}", operation_id="UpdateRaid")
    async def update_raid(
        self,
        raid_id: FromPath[UUID],
        data: JSONBody[RaidUpdate],
        raids_service: NamedDependency[RaidsService],
        current_officer: NamedDependency[Member],
    ) -> RaidDetail:
        """Edit a raid, including its status (officer)."""
        del current_officer
        raid = await raids_service.update_raid(raid_id, data)
        return await raids_service.get_detail(raid.id, viewer=None)

    @delete("/{raid_id:uuid}", operation_id="DeleteRaid")
    async def delete_raid(
        self,
        raid_id: FromPath[UUID],
        raids_service: NamedDependency[RaidsService],
        current_officer: NamedDependency[Member],
    ) -> None:
        """Delete a raid and its signups (officer)."""
        del current_officer
        await raids_service.delete_raid(raid_id)

    @patch("/{raid_id:uuid}/signups/{signup_id:uuid}", operation_id="UpdateRaidChart")
    async def update_raid_chart(
        self,
        raid_id: FromPath[UUID],
        signup_id: FromPath[UUID],
        data: JSONBody[RaidChartUpdate],
        raid_signups_service: NamedDependency[RaidSignupsService],
        current_officer: NamedDependency[Member],
    ) -> Signup:
        """Place a signed-up player into a raid chart group (1-8) or the bench (officer)."""
        del current_officer
        return await raid_signups_service.update_chart(raid_id, signup_id, data)
