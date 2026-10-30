"""Private member calendar feed.

``CalendarLinkController`` (signed in) issues and rotates the secret token at ``/api/me/calendar``.
``CalendarFeedController`` (public, token-authenticated) serves the ``.ics`` feed at ``/api/calendar/<token>.ics``:
mounted under ``/api`` so Cloudflare never caches it, and ``opt=SKIP_SESSION`` so it never carries ``Set-Cookie``
(same reasoning as ``lib/website.py``'s static routes). An unknown token 404s.
"""

from datetime import UTC, datetime

from litestar import Controller, Response, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.params import FromPath

from sidequest_api.domain.calendar.dependencies import provide_calendar_service
from sidequest_api.domain.calendar.services import CalendarService
from sidequest_api.lib.ics import build_calendar_feed
from sidequest_api.lib.website import SKIP_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import CalendarLink
from sidequest_common.settings import WebSettings


def _to_link(token: str, web_settings: WebSettings) -> CalendarLink:
    return CalendarLink(token=token, url=f"{web_settings.BASE_URL}/api/calendar/{token}.ics")


class CalendarLinkController(Controller):
    """``/api/me/calendar``: the signed-in member's private calendar link."""

    path = "/api/me/calendar"
    tags = ["Calendar"]
    dependencies = {"calendar_service": Provide(provide_calendar_service)}

    @get("/", operation_id="GetCalendarLink")
    async def get_calendar_link(
        self,
        current_member: NamedDependency[Member],
        calendar_service: NamedDependency[CalendarService],
        web_settings: NamedDependency[WebSettings],
    ) -> CalendarLink:
        """The member's calendar link, generating a token the first time it's asked for. 401 if not a guild member."""
        token = await calendar_service.get_or_create_token(current_member)
        return _to_link(token, web_settings)

    @post("/rotate", operation_id="RotateCalendarLink", status_code=200)
    async def rotate_calendar_link(
        self,
        current_member: NamedDependency[Member],
        calendar_service: NamedDependency[CalendarService],
        web_settings: NamedDependency[WebSettings],
    ) -> CalendarLink:
        """Issue a fresh token; the previous link 404s immediately."""
        token = await calendar_service.rotate_token(current_member)
        return _to_link(token, web_settings)


class CalendarFeedController(Controller):
    """``/api/calendar``: the public, token-authenticated ``.ics`` feed."""

    path = "/api/calendar"
    tags = ["Calendar"]
    dependencies = {"calendar_service": Provide(provide_calendar_service)}

    @get("/{token_file:str}", operation_id="GetCalendarFeed", opt=SKIP_SESSION, include_in_schema=False)
    async def get_calendar_feed(
        self,
        token_file: FromPath[str],
        calendar_service: NamedDependency[CalendarService],
        web_settings: NamedDependency[WebSettings],
    ) -> Response[str]:
        """The member's events (from 30 days ago onward) as an ``.ics`` feed. 404 for an unknown or old token."""
        if not token_file.endswith(".ics"):
            msg = "No such calendar"
            raise NotFoundException(msg)
        token = token_file.removesuffix(".ics")
        member = await calendar_service.get_by_token(token)
        if member is None:
            msg = "No such calendar"
            raise NotFoundException(msg)
        now = datetime.now(UTC)
        events = await calendar_service.list_feed_events(member, now=now)
        body = build_calendar_feed(events, base_url=web_settings.BASE_URL, now=now)
        return Response(content=body, media_type="text/calendar; charset=utf-8", headers={"Cache-Control": "private"})
