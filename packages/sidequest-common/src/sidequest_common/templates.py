"""User-editable message templates (welcome, level-up).

Placeholders use ``{name}`` syntax. Unknown placeholders are left as-is instead of raising, so a typo in a
guild's template never breaks the bot.
"""

from typing import Any

TEMPLATE_PLACEHOLDERS: dict[str, str] = {
    "mention": "Pings the member (@name)",
    "user": "Member's display name, no ping",
    "guild": "Server name",
    "level": "New level (level-up messages only)",
    "member_count": "Member count (welcome messages only)",
}


class _KeepMissing(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_template(template: str, **values: Any) -> str:
    """Fill ``{placeholder}`` values in ``template``, leaving unknown placeholders untouched."""
    try:
        return template.format_map(_KeepMissing(values))
    except ValueError, IndexError:
        # Malformed braces (e.g. a lone "{") or positional fields: send the template verbatim.
        return template
