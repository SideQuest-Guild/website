"""The wowsims/forever checkout: static data (``names.json``/``db.json``/``ui/specs``) and the ``wowsimcli`` binary.

Both the sims domain's request-time validation (:mod:`sidequest_api.domain.sims.services`) and the background
runner (:mod:`sidequest_api.domain.sims.runner`) read from the same checkout, at ``WOWSIMS_DIR`` (default
``/opt/wowsims``, the layout the Dockerfile's Go build stage produces; local dev points it at
``~/.cache/wowsims-forever``, which the wow-forever-sim skill's ``setup`` command builds).
"""

from pathlib import Path

from sidequest_common.settings import WowSimsSettings


def wowsims_dir(settings: WowSimsSettings | None = None) -> Path:
    """The checkout's root directory."""
    return Path((settings or WowSimsSettings()).DIR)


def wowsimcli_path(directory: Path) -> Path:
    """The built CLI binary inside ``directory``."""
    return directory / "bin" / "wowsimcli"
