from sidequest_common.templates import render_template


def test_fills_known_placeholders() -> None:
    assert render_template("GG {mention}, level {level}!", mention="<@1>", level=3) == "GG <@1>, level 3!"


def test_unknown_placeholder_left_intact() -> None:
    assert render_template("Hi {mention} from {guidl}", mention="<@1>") == "Hi <@1> from {guidl}"


def test_malformed_template_returned_verbatim() -> None:
    assert render_template("oops { and {0}", mention="x") == "oops { and {0}"
