"""Modal screen to choose level, message, and timestamp keys for collapsed log lines."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList
from textual.widgets.option_list import Option

ResultType = tuple[str | None, str | None, str | None]
INFER_ID = "__infer__"


class LogSettingsScreen(ModalScreen[ResultType]):
    """Let user pick level key, message key, and timestamp key (Rust will use these)."""

    BINDINGS = [Binding("escape", "dismiss", "Cancel", show=True)]

    def __init__(
        self,
        keys: list[str],
        current_level: str | None = None,
        current_message: str | None = None,
        current_timestamp: str | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._keys = keys
        self._level_key: str | None = current_level
        self._message_key: str | None = current_message
        self._timestamp_key: str | None = current_timestamp

    def compose(self) -> ComposeResult:
        def add_options(option_list: OptionList) -> None:
            option_list.add_option(Option("(infer)", id=INFER_ID))
            for k in self._keys:
                option_list.add_option(Option(k, id=k))

        with Vertical():
            yield Label("Level key:")
            level_list = OptionList(id="level-list")
            add_options(level_list)
            yield level_list
            yield Label("Message key:")
            message_list = OptionList(id="message-list")
            add_options(message_list)
            yield message_list
            yield Label("Timestamp key:")
            ts_list = OptionList(id="timestamp-list")
            add_options(ts_list)
            yield ts_list
            yield Button("Done", id="done")

    def on_mount(self) -> None:
        self.query_one("#level-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id is None:
            return
        opt_id = None if event.option_id == INFER_ID else str(event.option_id)
        try:
            ol = event.option_list
            if ol.id == "level-list":
                self._level_key = opt_id
            elif ol.id == "message-list":
                self._message_key = opt_id
            elif ol.id == "timestamp-list":
                self._timestamp_key = opt_id
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "done":
            self.dismiss((self._level_key, self._message_key, self._timestamp_key))
