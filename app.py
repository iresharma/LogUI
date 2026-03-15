"""Entry point: run LogUI (e.g. python app.py or python -m app)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.events import DescendantFocus
from textual.widget import Widget
from textual.widgets import Collapsible, Footer, Static, Tree

from themes import LOGUI_DARK, LOGUI_LIGHT

from log_loader import load_log_file
from schema import all_keys_from_entries, schema_from_object
from screens.filter_screen import FilterScreen
from screens.log_settings_screen import LogSettingsScreen
from widgets.log_container import LogContainer
from widgets.log_ui_header import LogUIHeader


VERSION = "v0.0.1"

LEVEL_KEYS = ("level", "log_level", "severity")
LEVEL_STYLES = {"info": "dim", "warn": "yellow", "warning": "yellow", "error": "red", "debug": "dim cyan"}


def _level_badge(entry: dict[str, Any]) -> str:
    """Return a Rich/markup string for the log level badge, or empty if not found."""
    level = None
    for k in LEVEL_KEYS:
        if k in entry and isinstance(entry[k], str):
            level = (entry[k] or "").strip().lower()
            break
    if not level:
        return ""
    style = LEVEL_STYLES.get(level, "dim")
    return f"[{style}][ {level.upper()} ][/{style}]"


class LogUI(App[None]):
    """TUI for viewing JSON log files."""

    CSS = """
    #log-container {
        width: 1fr;
        min-width: 20;
        overflow-y: auto;
        overflow-x: hidden;
    }
    #log-container Collapsible.-selected {
        background: $primary 20%;
        border: solid $primary;
    }
    #schema-container {
        width: 40%;
        min-width: 24;
        border-left: solid $primary;
        padding: 0 1;
    }
    #schema-placeholder {
        padding: 1;
        text-style: italic;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("f", "filter", "Filter", show=True),
        Binding("c", "log_settings", "Log key config", show=True),
        Binding("t", "theme", "Theme", show=True),
        Binding("space", "toggle_selection", "Select", show=True),
        Binding("ctrl+c", "copy", "Copy", show=True),
        Binding("right", "focus_schema", "→ panel", show=True),
        Binding("left", "focus_log_list", "← panel", show=True),
    ]

    def __init__(self, log_path: str | Path | None = None) -> None:
        super().__init__()
        self.log_path = Path(log_path) if log_path else None
        self.log_entries: list[dict[str, Any]] = []
        self.raw_lines: list[str] = []
        self.display_key = "timestamp"
        self.hovered_log_index: int | None = None
        self.selected_indices: set[int] = set()
        self.filter_text = ""
        self._filtered_indices: list[int] = []

    def compose(self) -> ComposeResult:
        yield LogUIHeader(version=VERSION)
        with Horizontal():
            yield LogContainer(id="log-container")
            with Vertical(id="schema-container"):
                yield Static("Schema (hover a log line)", id="schema-placeholder")
                yield Tree("Schema", id="schema-tree")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(LOGUI_DARK)
        self.register_theme(LOGUI_LIGHT)
        if self.theme not in self.available_themes:
            self.theme = "logui-dark"
        if self.log_path and self.log_path.exists():
            self.log_entries, self.raw_lines = load_log_file(self.log_path)
            self._filtered_indices = list(range(len(self.log_entries)))
            keys = all_keys_from_entries(self.log_entries)
            if keys and self.display_key not in keys:
                self.display_key = keys[0]
            self._populate_log_panel()
        else:
            self.query_one("#log-container", LogContainer).mount(
                Static("No log file loaded. Run: python app.py <path/to/log.txt>", id="empty-state")
            )
        schema_tree = self.query_one("#schema-tree", Tree)
        schema_tree.display = False
        self.query_one("#schema-placeholder", Static).display = True

    def _update_schema_panel(self, entry: dict[str, Any] | None) -> None:
        tree = self.query_one("#schema-tree", Tree)
        placeholder = self.query_one("#schema-placeholder", Static)
        if entry is None or entry.get("_parse_error"):
            tree.display = False
            placeholder.display = True
            return
        tree.display = True
        placeholder.display = False
        tree.clear()
        tree.root.label = "Schema"
        for key, type_or_children in schema_from_object(entry):
            if isinstance(type_or_children, list):
                node = tree.root.add(key, expand=True)
                self._add_schema_children(node, type_or_children)
            else:
                tree.root.add_leaf(f'"{key}": {type_or_children}')
        tree.root.expand_all()

    def _add_schema_children(self, node: Any, children: list[Any]) -> None:
        for key, type_or_children in children:
            if isinstance(type_or_children, list):
                child_node = node.add(key, expand=True)
                self._add_schema_children(child_node, type_or_children)
            else:
                node.add_leaf(f'"{key}": {type_or_children}')

    def _populate_log_panel(self) -> None:
        container = self.query_one("#log-container", LogContainer)
        for child in list(container.children):
            child.remove()
        for i in self._filtered_indices:
            if i >= len(self.log_entries):
                continue
            entry = self.log_entries[i]
            if entry.get("_parse_error"):
                title = entry.get("_raw", str(entry))[:60] + ("..." if len(entry.get("_raw", "")) > 60 else "")
            else:
                disp = entry.get(self.display_key, "")
                if isinstance(disp, dict):
                    disp = "[object]"
                elif isinstance(disp, list):
                    disp = "[array]"
                else:
                    disp = str(disp)[:50]
                title = f"log line  {disp}"
            pretty = json.dumps(entry, indent=2) if isinstance(entry, dict) else str(entry)
            badge_text = _level_badge(entry) if not entry.get("_parse_error") else ""
            children: list[Widget] = []
            if badge_text:
                children.append(Static(badge_text))
            children.append(Static(pretty))
            collapsible = Collapsible(
                *children,
                title=title,
                collapsed=True,
                collapsed_symbol="→",
                expanded_symbol="▼",
                id=f"log-line-{i}",
            )
            container.mount(collapsible)
            if i in self.selected_indices:
                collapsible.add_class("-selected")

    def action_focus_schema(self) -> None:
        """Move focus to the schema panel (tree or placeholder)."""
        try:
            tree = self.query_one("#schema-tree", Tree)
            if tree.display:
                self.screen.set_focus(tree)
            else:
                self.screen.set_focus(self.query_one("#schema-placeholder", Static))
        except NoMatches:
            pass

    def action_focus_log_list(self) -> None:
        """Move focus to the log list (first row or container)."""
        container = self.query_one("#log-container", LogContainer)
        rows = [c for c in container.children if getattr(c, "id", None) and str(c.id).startswith("log-line-")]
        if rows:
            try:
                title = rows[0].query_one("CollapsibleTitle")
                self.screen.set_focus(title)
                rows[0].scroll_visible()
            except NoMatches:
                self.screen.set_focus(container)
        else:
            self.screen.set_focus(container)

    def action_toggle_selection(self) -> None:
        focused = self.focused
        while focused:
            if focused.id and focused.id.startswith("log-line-"):
                try:
                    idx = int(focused.id.split("-")[-1])
                    if idx in self.selected_indices:
                        self.selected_indices.discard(idx)
                        focused.remove_class("-selected")
                    else:
                        self.selected_indices.add(idx)
                        focused.add_class("-selected")
                except (ValueError, IndexError):
                    pass
                return
            focused = getattr(focused, "parent", None)

    @on(DescendantFocus)
    def _on_descendant_focus(self, event: DescendantFocus) -> None:
        control: Widget | None = event.control
        while control:
            if control.id and control.id.startswith("log-line-"):
                try:
                    idx = int(control.id.split("-")[-1])
                    if 0 <= idx < len(self.log_entries):
                        self.hovered_log_index = idx
                        self._update_schema_panel(self.log_entries[idx])
                except (ValueError, IndexError):
                    pass
                return
            control = getattr(control, "parent", None)
        self.hovered_log_index = None

    def action_quit(self) -> None:
        self.exit()

    def action_theme(self) -> None:
        self.run_action("app.change_theme")

    def action_copy(self) -> None:
        to_copy: list[int] = sorted(self.selected_indices) if self.selected_indices else []
        if not to_copy and self.hovered_log_index is not None:
            to_copy = [self.hovered_log_index]
        if not to_copy:
            self.notify("Select log line(s) with Space, or focus one, then Copy", severity="information")
            return
        parts = []
        for i in to_copy:
            if i < len(self.raw_lines):
                parts.append(self.raw_lines[i])
            else:
                parts.append(json.dumps(self.log_entries[i], indent=2))
        self.copy_to_clipboard("\n".join(parts))
        self.notify(f"Copied {len(parts)} line(s)")

    def action_log_settings(self) -> None:
        keys = all_keys_from_entries(self.log_entries)
        if not keys:
            self.notify("No log entries to choose key from", severity="warning")
            return
        self.push_screen(LogSettingsScreen(keys=keys, current=self.display_key), self._on_log_settings_done)

    def _on_log_settings_done(self, key: str | None) -> None:
        if key:
            self.display_key = key
            self._populate_log_panel()
            self.notify(f"Display key set to {key}")

    def action_filter(self) -> None:
        self.push_screen(FilterScreen(current=self.filter_text), self._on_filter_done)

    def _on_filter_done(self, filter_text: str | None) -> None:
        if filter_text is None:
            return
        self.filter_text = filter_text
        if not filter_text.strip():
            self._filtered_indices = list(range(len(self.log_entries)))
        else:
            lower = filter_text.lower()
            self._filtered_indices = [
                i for i in range(len(self.log_entries))
                if lower in json.dumps(self.log_entries[i]).lower() or lower in self.raw_lines[i].lower()
            ]
        self._populate_log_panel()
        self.notify(f"Filter: {len(self._filtered_indices)} line(s) match")


if __name__ == "__main__":
    log_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = LogUI(log_path=log_path)
    app.run()
