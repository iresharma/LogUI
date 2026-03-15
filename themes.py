"""Custom themes for LogUI."""

from textual.theme import Theme

LOGUI_DARK = Theme(
    name="logui-dark",
    primary="#5B9BD5",
    secondary="#2E5C8A",
    accent="#F0A030",
    warning="#E8A030",
    error="#C45C5C",
    success="#5CB85C",
    foreground="#E0E8F0",
    background="#1A1E24",
    surface="#252B33",
    panel="#2D343C",
)

LOGUI_LIGHT = Theme(
    name="logui-light",
    primary="#2E5C8A",
    secondary="#5B9BD5",
    accent="#C08020",
    warning="#B87820",
    error="#A04040",
    success="#408040",
    foreground="#202830",
    background="#F0F4F8",
    surface="#E4EAEE",
    panel="#D8E0E8",
    dark=False,
)
