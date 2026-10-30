"""Redacts secrets out of uvicorn's access log before it's formatted.

The calendar feed's only credential is its token, embedded in the request path
(``/api/calendar/<token>.ics``, see ``domain/calendar/controllers.py``). The production ``Procfile`` starts
uvicorn with its default access logger, which otherwise writes that full path -- including the reusable bearer
token -- on every successful fetch. ``install_calendar_log_redaction`` must run once at app startup (``create_app``)
so it applies under uvicorn regardless of how it's invoked.
"""

import logging
import re

_TOKEN_IN_PATH = re.compile(r"(?<=/api/calendar/)[^/?]+(?=\.ics)")


class CalendarTokenRedactionFilter(logging.Filter):
    """Masks the token segment of ``/api/calendar/<token>.ics`` in uvicorn access log records.

    uvicorn's ``AccessFormatter`` reads ``record.args`` as a 5-tuple of
    ``(client_addr, method, full_path, http_version, status_code)`` at format time (see
    ``uvicorn.logging.AccessFormatter.formatMessage``), so rewriting ``full_path`` in ``filter()`` -- which runs
    before formatting -- redacts the token in every handler attached to the logger.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the token in ``record``'s path args in place; always returns ``True`` (never drops the record)."""
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):  # noqa: PLR2004
            full_path = args[2]
            redacted = _TOKEN_IN_PATH.sub("***", full_path)
            if redacted != full_path:
                record.args = (*args[:2], redacted, *args[3:])
        return True


def install_calendar_log_redaction() -> None:
    """Attach ``CalendarTokenRedactionFilter`` to ``uvicorn.access``, idempotently."""
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(existing, CalendarTokenRedactionFilter) for existing in access_logger.filters):
        access_logger.addFilter(CalendarTokenRedactionFilter())
