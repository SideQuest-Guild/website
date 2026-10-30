"""Calendar bearer tokens must never reach uvicorn's access log in plain text."""

import logging

from sidequest_api.lib.logging import CalendarTokenRedactionFilter, install_calendar_log_redaction


def _access_record(full_path: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %s',
        args=("127.0.0.1:12345", "GET", full_path, "1.1", "200"),
        exc_info=None,
    )


def _full_path(record: logging.LogRecord) -> str:
    assert isinstance(record.args, tuple)
    path = record.args[2]
    assert isinstance(path, str)
    return path


def test_calendar_token_is_redacted_from_access_log_path() -> None:
    record = _access_record("/api/calendar/super-secret-token-abc123.ics")
    assert CalendarTokenRedactionFilter().filter(record) is True
    assert _full_path(record) == "/api/calendar/***.ics"
    assert "super-secret-token-abc123" not in _full_path(record)


def test_unrelated_paths_are_left_untouched() -> None:
    record = _access_record("/api/members")
    CalendarTokenRedactionFilter().filter(record)
    assert _full_path(record) == "/api/members"


def test_calendar_link_issuance_path_is_untouched() -> None:
    """``/api/me/calendar`` carries no token in its path; only the ``.ics`` feed does."""
    record = _access_record("/api/me/calendar")
    CalendarTokenRedactionFilter().filter(record)
    assert _full_path(record) == "/api/me/calendar"


def test_install_is_idempotent_and_applies_to_the_uvicorn_access_logger() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    # Other tests' app fixtures may have already called this (create_app runs it at startup); start from a clean
    # slate so this test only measures what *this* call contributes, regardless of run order.
    for f in list(access_logger.filters):
        if isinstance(f, CalendarTokenRedactionFilter):
            access_logger.removeFilter(f)
    install_calendar_log_redaction()
    install_calendar_log_redaction()
    assert sum(1 for f in access_logger.filters if isinstance(f, CalendarTokenRedactionFilter)) == 1

    record = _access_record("/api/calendar/another-secret-token.ics")
    assert access_logger.filter(record)
    assert _full_path(record) == "/api/calendar/***.ics"

    # cleanup so this test doesn't leak a filter into other tests' logger state
    for f in list(access_logger.filters):
        if isinstance(f, CalendarTokenRedactionFilter):
            access_logger.removeFilter(f)
