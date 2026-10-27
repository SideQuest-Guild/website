"""Serve the website's static build (Astro output in ``website/dist``) from the API at ``/``.

This is the seam between backend and frontend: swap it for litestar-vite's ``VitePlugin`` once the Astro project
exists if dev-server proxying is wanted. Until a build exists, ``/`` serves a short placeholder page.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from litestar import MediaType, get
from litestar.static_files import create_static_files_router

if TYPE_CHECKING:
    from litestar.types import ControllerRouterHandler

# api/src/sidequest_api/lib/website.py -> repo root is four levels up from lib/.
DEFAULT_WEBSITE_DIST = Path(__file__).resolve().parents[4] / "website" / "dist"

_PLACEHOLDER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SideQuest</title></head>
<body><main><h1>SideQuest</h1><p>The guild site is being built. Find us on Discord in the meantime.</p></main></body>
</html>"""


@get("/", media_type=MediaType.HTML, include_in_schema=False, sync_to_thread=False)
def website_placeholder() -> str:
    """Stand-in home page until ``website/dist`` is built."""
    return _PLACEHOLDER


def website_routes(dist_dir: Path = DEFAULT_WEBSITE_DIST) -> list[ControllerRouterHandler]:
    """Static site at ``/`` (with ``index.html`` resolution and ``404.html``) if built, else the placeholder."""
    if (dist_dir / "index.html").is_file():
        return [create_static_files_router(path="/", directories=[dist_dir], html_mode=True, name="website")]
    return [website_placeholder]
