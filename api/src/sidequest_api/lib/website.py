"""Serve the SideQuest website: Astro (``website/``) behind the API at ``/``.

Two independent paths, selected by ``VITE_DEV_MODE`` (litestar-vite's own switch):

- Dev (``VITE_DEV_MODE=1``): :func:`website_vite_plugin` builds a ``VitePlugin`` in ``mode="framework"`` that
  proxies every request Litestar doesn't otherwise handle to the Astro dev server (started separately, e.g. by
  ``make dev``). Browsers only ever talk to Litestar's origin, so ``/api``, ``/auth`` and the site share one
  cookie jar.
- Prod (default): :func:`website_routes` serves the built ``website/dist`` with a static-files router
  (directory ``index.html`` resolution, themed ``404.html`` for unknown paths), or a placeholder page
  if the site hasn't been built yet.

Why not litestar-vite's framework mode in production too: with built assets and no running Node
process, ``ViteConfig._apply_proxy_mode_defaults`` turns on ``spa_handler``, which registers a single
catch-all route serving one ``index.html`` for every path (see ``litestar_vite.handler.AppHandler``,
``spa_handler_prod``) -- true SPA behavior. That always returns 200 and ignores Astro's per-directory
``index.html`` files, so it cannot reproduce "``/raids/`` serves its own page" or "unknown paths get a
404-status themed 404.html", both of which ``create_static_files_router(html_mode=True)`` already does
correctly. Production keeps the static-files router; ``VitePlugin`` is dev-only.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING

from litestar import MediaType, get
from litestar.static_files import create_static_files_router

if TYPE_CHECKING:
    from litestar.types import ControllerRouterHandler
    from litestar_vite import VitePlugin

# api/src/sidequest_api/lib/website.py -> repo root is four levels up from lib/.
WEBSITE_ROOT = Path(__file__).resolve().parents[4] / "website"
DEFAULT_WEBSITE_DIST = WEBSITE_ROOT / "dist"

_TRUE_VALUES = {"1", "true", "yes", "on"}

_PLACEHOLDER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SideQuest</title></head>
<body><main><h1>SideQuest</h1><p>The guild site is being built. Find us on Discord in the meantime.</p></main></body>
</html>"""


def is_vite_dev_mode() -> bool:
    """Whether to proxy the Astro dev server instead of serving a static build.

    Reads ``VITE_DEV_MODE``, the environment variable litestar-vite's own ``RuntimeConfig`` already
    honors, so this one switch controls both sides of the integration.
    """
    return os.environ.get("VITE_DEV_MODE", "").strip().lower() in _TRUE_VALUES


@get("/", media_type=MediaType.HTML, include_in_schema=False, sync_to_thread=False)
def website_placeholder() -> str:
    """Stand-in home page until ``website/dist`` is built."""
    return _PLACEHOLDER


def website_routes(dist_dir: Path = DEFAULT_WEBSITE_DIST) -> list[ControllerRouterHandler]:
    """Static site at ``/`` (with ``index.html`` resolution and ``404.html``) if built, else the placeholder."""
    if (dist_dir / "index.html").is_file():
        return [create_static_files_router(path="/", directories=[dist_dir], html_mode=True, name="website")]
    return [website_placeholder]


def website_vite_plugin(website_root: Path = WEBSITE_ROOT) -> VitePlugin:
    """``VitePlugin`` that proxies the Astro dev server through Litestar's origin.

    ``mode="framework"``: Astro (an external dev server using Vite internally) owns HTML; Litestar
    proxies non-API routes to it via ``SSRProxyMiddleware``. ``start_dev_server=False``: Astro is
    started separately (``make web-dev``), not spawned by this plugin.

    Why not let the plugin spawn ``npm run dev`` itself: ``ViteProcess`` runs the child with
    ``start_new_session=True`` (its own process group, for clean teardown of the whole tree). Astro
    7.4's dev CLI exits immediately with "Dev server process exited before becoming ready" when
    started that way (reproduced directly with ``subprocess.Popen(..., start_new_session=True)``,
    independent of litestar-vite) -- confirmed upstream incompatibility, not a config issue. Running
    Astro in its own terminal sidesteps it entirely; its ``litestar-vite-plugin/astro`` integration
    still reads ``.litestar.json`` (written by this plugin's lifespan on every Litestar start, CLI or
    not) and writes the hotfile Litestar reads to find Astro's port, so the proxy still "just works".
    Litestar's own routes (``/api``, ``/auth``, ``/schema``, ``/health``) are matched directly and
    never reach the proxy catch-all.
    """
    from litestar_vite import PathConfig, RuntimeConfig, ViteConfig, VitePlugin

    return VitePlugin(
        config=ViteConfig(
            mode="framework",
            dev_mode=True,
            paths=PathConfig(root=website_root, bundle_dir=website_root / "dist"),
            runtime=RuntimeConfig(
                host="127.0.0.1",
                port=int(os.environ.get("VITE_PORT", "4321")),
                start_dev_server=False,
            ),
        )
    )
