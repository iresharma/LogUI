from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static


class SearchBar(Widget):
    """Small Vim-style search bar shown above the footer."""

    DEFAULT_CSS = """
    SearchBar {
        height: 1;
        dock: bottom;
        padding: 0 1;
        background: $surface;
        color: $text;
    }
    SearchBar > Horizontal {
        height: 1;
    }
    SearchBar .search-prefix {
        width: auto;
        color: $accent;
    }
    SearchBar .search-input {
        width: 1fr;
    }
    SearchBar .search-status {
        width: auto;
        color: $text-muted;
    }
    """

    class Changed(Message):
        """Emitted when the search text changes."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class Submitted(Message):
        """Emitted when the user submits the search (Enter)."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    class Cancelled(Message):
        """Emitted when the user cancels search (Esc)."""

        pass

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._status: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("/", classes="search-prefix")
            yield Input(
                placeholder="Substring (like /pattern in Vim)…",
                classes="search-input",
                id="search-input",
            )
            yield Static("", classes="search-status", id="search-status")

    def on_mount(self) -> None:
        # Hidden by default; LogUI will show it when entering search mode.
        self.display = False

    def focus_input(self) -> None:
        """Focus the search input."""
        self.query_one("#search-input", Input).focus()

    def set_value(self, value: str) -> None:
        """Set the search input value without losing focus."""
        inp = self.query_one("#search-input", Input)
        inp.value = value

    def get_value(self) -> str:
        """Return the current search input text."""
        return self.query_one("#search-input", Input).value or ""

    def update_status(self, status: str) -> None:
        """Update the status label (e.g. '3/12', 'No matches')."""
        self._status = status
        self.query_one("#search-status", Static).update(status)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self.post_message(self.Changed(event.value or ""))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self.post_message(self.Submitted(event.value or ""))

