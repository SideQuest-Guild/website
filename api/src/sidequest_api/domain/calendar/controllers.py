"""Private member calendar feed.

``CalendarLinkController`` (signed in) issues and rotates the secret token at ``/api/me/calendar``.
``CalendarFeedController`` (public, token-authenticated) serves the ``.ics`` feed at ``/api/calendar/<token>.ics``:
mounted under ``/api`` so Cloudflare never caches it, and ``opt=SKIP_SESSION`` so it never carries ``Set-Cookie``
(same reasoning as ``lib/website.py``'s static routes). An unknown token 404s.
"""

from datetime import UTC, datetime
from typing import Annotated

from litestar import Controller, Response, get, post
from litestar.di import NamedDependency, Provide
from litestar.exceptions import NotFoundException
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import Parameter

from sidequest_api.domain.calendar.dependencies import provide_calendar_service
from sidequest_api.domain.calendar.services import CalendarService
from sidequest_api.lib.ics import build_calendar_feed
from sidequest_api.lib.openapi import NOT_A_MEMBER, NOT_SIGNED_IN, SECURITY_SESSION
from sidequest_api.lib.website import SKIP_SESSION
from sidequest_common.models import Member
from sidequest_common.schemas import CalendarLink
from sidequest_common.settings import WebSettings


def _to_link(token: str, web_settings: WebSettings) -> CalendarLink:
    return CalendarLink(token=token, url=f"{web_settings.BASE_URL}/api/calendar/{token}.ics")


class CalendarLinkController(Controller):
    """``/api/me/calendar``: the signed-in member's private calendar link."""

    path = "/api/me/calendar"
    tags = ["My calendar"]
    security = SECURITY_SESSION
    dependencies = {"calendar_service": Provide(provide_calendar_service)}

    @get(
        "/",
        operation_id="GetCalendarLink",
        summary="Get your calendar link",
        description=(
            "Returns the signed-in member's private calendar link, generating a token the first time it is asked for."
        ),
        response_description="The member's calendar link.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def get_calendar_link(
        self,
        current_member: NamedDependency[Member],
        calendar_service: NamedDependency[CalendarService],
        web_settings: NamedDependency[WebSettings],
    ) -> CalendarLink:
        token = await calendar_service.get_or_create_token(current_member)
        return _to_link(token, web_settings)

    @post(
        "/rotate",
        operation_id="RotateCalendarLink",
        status_code=200,
        summary="Rotate your calendar link",
        description="Issues a fresh calendar token for the signed-in member. The previous link 404s immediately.",
        response_description="The member's new calendar link.",
        responses={401: NOT_SIGNED_IN, 403: NOT_A_MEMBER},
    )
    async def rotate_calendar_link(
        self,
        current_member: NamedDependency[Member],
        calendar_service: NamedDependency[CalendarService],
        web_settings: NamedDependency[WebSettings],
    ) -> CalendarLink:
        token = await calendar_service.rotate_token(current_member)
        return _to_link(token, web_settings)


class CalendarFeedController(Controller):
    """``/api/calendar``: the public, token-authenticated ``.ics`` feed."""

    path = "/api/calendar"
    tags = ["Calendar feed"]
    dependencies = {"calendar_service": Provide(provide_calendar_service)}

    @get(
        "/{token_file:str}",
        operation_id="GetCalendarFeed",
        opt=SKIP_SESSION,
        include_in_schema=False,
        summary="Get a calendar feed",
        description=(
            "Returns a member's events from 30 days ago onward as an `.ics` feed. The token in the path is the "
            "member's private calendar token; no sign-in is needed."
        ),
        response_description="The `.ics` calendar feed.",
        responses={404: ResponseSpec(None, description="The token is unknown, expired, or missing the `.ics` suffix.")},
    )
    async def get_calendar_feed(
        self,
        token_file: Annotated[str, Parameter(description="The calendar token followed by `.ics`.")],
        calendar_service: NamedDependency[CalendarService],
        web_settings: NamedDependency[WebSettings],
    ) -> Response[str]:
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
