"""LogUI header with logo and version."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Static


class LogUIHeader(Widget):
    """Header showing LogUI logo and version."""

    DEFAULT_CSS = """
    LogUIHeader {
        dock: top;
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $foreground;
    }
    LogUIHeader .header-title {
        width: auto;
        color: $accent;
    }
    LogUIHeader .header-version {
        width: auto;
        color: $primary;
        text-style: dim;
    }
    LogUIHeader .header-spacer {
        width: 1fr;
    }
    """

    def __init__(
        self,
        version: str = "v0.0.1",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._version = version

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("◉ LogUI", classes="header-title")
            yield Static("", classes="header-spacer")
            yield Static(self._version, classes="header-version")
