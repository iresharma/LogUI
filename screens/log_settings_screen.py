"""Modal screen to choose the display key for collapsed log lines."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList
from textual.widgets.option_list import Option


class LogSettingsScreen(ModalScreen[str]):
    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=True)]
    """Let user pick which key to show in the collapsed log line."""

    def __init__(
        self,
        keys: list[str],
        current: str,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._keys = keys
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Select key to show in collapsed log line:")
            option_list = OptionList(id="key-option-list")
            for k in self._keys:
                option_list.add_option(Option(k, id=k))
            yield option_list
            yield Button("Done", id="done")

    def on_mount(self) -> None:
        self.query_one("#key-option-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            self.dismiss(str(event.option_id))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "done":
            opt = self.query_one("#key-option-list", OptionList).highlighted_option
            if opt and opt.id:
                self.dismiss(str(opt.id))
            else:
                self.dismiss(self._current)
