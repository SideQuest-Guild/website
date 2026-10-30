"""Route registry.

``guild_controllers`` serve the Discord bot. ``create_app`` mounts them under ``/api/guilds/{guild_id}`` behind the
``X-API-Key`` guard. ``public_routes`` (health, website/member hub routes) have no service-key auth.
"""

from sidequest_api.domain.addons.controllers import AddonsController
from sidequest_api.domain.attendance.controllers import AttendanceController, AttendanceVoiceController
from sidequest_api.domain.auth.controllers import AuthController
from sidequest_api.domain.away.controllers import AwayController, AwayNowController
from sidequest_api.domain.badges.controllers import BadgesController
from sidequest_api.domain.battlenet.controllers import BattleNetController
from sidequest_api.domain.calendar.controllers import CalendarFeedController, CalendarLinkController
from sidequest_api.domain.cases.controllers import CasesController
from sidequest_api.domain.discord_live.controllers import DiscordLiveController, DiscordLivePublicController
from sidequest_api.domain.discord_online.controllers import DiscordOnlineController
from sidequest_api.domain.discord_signups.controllers import DiscordSignupsController
from sidequest_api.domain.event_series.controllers import EventSeriesController
from sidequest_api.domain.event_sync.controllers import EventSyncController
from sidequest_api.domain.events.controllers import EventsController
from sidequest_api.domain.gm.controllers import GmController
from sidequest_api.domain.guild_roles.controllers import GuildRolesController
from sidequest_api.domain.guilds.controllers import GuildConfigController
from sidequest_api.domain.heroes.controllers import HeroesController
from sidequest_api.domain.levels.controllers import LevelsController
from sidequest_api.domain.member_links.controllers import MemberLinksController
from sidequest_api.domain.member_profiles.controllers import MemberProfilesController
from sidequest_api.domain.members.controllers import MembersController
from sidequest_api.domain.recruiting.controllers import RecruitingController
from sidequest_api.domain.role_menus.controllers import RoleMenusController
from sidequest_api.domain.role_resets.controllers import RoleResetsController
from sidequest_api.domain.signup_notices.controllers import SignupNoticesController
from sidequest_api.domain.system.controllers import HealthController
from sidequest_api.domain.weekly_board.controllers import WeeklyBoardController

GUILD_API_PATH = "/api/guilds/{guild_id:int}"

guild_controllers = [
    GuildConfigController,
    LevelsController,
    CasesController,
    RoleMenusController,
    EventSyncController,
    DiscordLiveController,
    MemberLinksController,
    MemberProfilesController,
    GuildRolesController,
    RoleResetsController,
    SignupNoticesController,
    WeeklyBoardController,
    DiscordSignupsController,
    AwayNowController,
    AttendanceVoiceController,
    BadgesController,
]

public_routes = [
    HealthController,
    AuthController,
    BattleNetController,
    MembersController,
    EventsController,
    EventSeriesController,
    AddonsController,
    DiscordLivePublicController,
    DiscordOnlineController,
    GmController,
    RecruitingController,
    CalendarLinkController,
    CalendarFeedController,
    AwayController,
    AttendanceController,
    HeroesController,
]
