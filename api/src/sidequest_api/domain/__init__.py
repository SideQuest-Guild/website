"""Route registry.

``guild_controllers`` serve the Discord bot. ``create_app`` mounts them under ``/api/guilds/{guild_id}`` behind the
``X-API-Key`` guard. ``public_routes`` (health, website/member hub routes) have no service-key auth.
"""

from sidequest_api.domain.addons.controllers import AddonsController
from sidequest_api.domain.auth.controllers import AuthController
from sidequest_api.domain.battlenet.controllers import BattleNetController
from sidequest_api.domain.cases.controllers import CasesController
from sidequest_api.domain.guilds.controllers import GuildConfigController
from sidequest_api.domain.levels.controllers import LevelsController
from sidequest_api.domain.members.controllers import MembersController
from sidequest_api.domain.raids.controllers import RaidsController
from sidequest_api.domain.role_menus.controllers import RoleMenusController
from sidequest_api.domain.system.controllers import HealthController

GUILD_API_PATH = "/api/guilds/{guild_id:int}"

guild_controllers = [
    GuildConfigController,
    LevelsController,
    CasesController,
    RoleMenusController,
]

public_routes = [
    HealthController,
    AuthController,
    BattleNetController,
    MembersController,
    RaidsController,
    AddonsController,
]
