"""Modal screen for filter input."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class FilterScreen(ModalScreen[str]):
    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=True)]
    """Let user enter a filter string (substring match in log line)."""

    def __init__(
        self,
        current: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Filter (substring in log line):")
            yield Input(value=self._current, placeholder="e.g. error or level=info", id="filter-input")
            with Horizontal():
                yield Button("Apply", id="apply")
                yield Button("Clear", id="clear")

    def on_mount(self) -> None:
        self.query_one("#filter-input", Input).focus()

    class Changed(Message):
        """Message emitted when the filter text changes."""

        def __init__(self, value: str) -> None:
            super().__init__()
            self.value = value

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            # Live-update: inform the app without closing the dialog.
            self.post_message(self.Changed(event.value or ""))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        inp = self.query_one("#filter-input", Input)
        if event.button.id == "apply":
            self.dismiss(inp.value or "")
        elif event.button.id == "clear":
            self.dismiss("")
