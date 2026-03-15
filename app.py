"""Entry point: run LogUI (e.g. python app.py or python -m app)."""

from __future__ import annotations

import asyncio
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
from textual.worker import Worker

from themes import LOGUI_DARK, LOGUI_LIGHT

from log_loader import load_log_file, load_used_rust
from schema import all_keys_from_entries, infer_display_keys, schema_from_object
from screens.filter_screen import FilterScreen
from screens.loading_screen import LoadingScreen
from screens.log_settings_screen import LogSettingsScreen
from widgets.log_container import LogContainer
from widgets.log_ui_header import LogUIHeader


VERSION = "v0.0.1"

LEVEL_STYLES = {"info": "dim", "warn": "yellow", "warning": "yellow", "error": "red", "debug": "dim cyan"}


def _level_badge_from_level(level: str) -> str:
    """Return a Rich/markup string for the log level badge from normalized level string."""
    if not level:
        return ""
    lvl = level.strip().lower()
    style = LEVEL_STYLES.get(lvl, "dim")
    return f"[{style}][ {lvl.upper()} ][/{style}]"


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
            self.push_screen(LoadingScreen(self.log_path))
            self.run_worker(
                self._load_log_worker(),
                exclusive=True,
                exit_on_error=False,
            )
        else:
            self.query_one("#log-container", LogContainer).mount(
                Static("No log file loaded. Run: python app.py <path/to/log.txt>", id="empty-state")
            )
        schema_tree = self.query_one("#schema-tree", Tree)
        schema_tree.display = False
        self.query_one("#schema-placeholder", Static).display = True

    async def _load_log_worker(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Run load_log_file in a thread so the loading screen can animate."""
        return await asyncio.to_thread(load_log_file, self.log_path)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """When the load worker finishes, pop the loading screen and show logs."""
        from textual.worker import WorkerState

        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        # Only react to our load worker (result is (entries, raw_lines) on success)
        try:
            if event.state == WorkerState.ERROR:
                self.pop_screen()
                self.log_entries = []
                self.raw_lines = []
                err = getattr(event.worker, "error", None)
                msg = str(err) if err else "Failed to parse log file"
                self.query_one("#log-container", LogContainer).mount(
                    Static(f"Error: {msg}", id="empty-state")
                )
                self.notify(msg, severity="error")
                return
            result = event.worker.result
            if result is None or not isinstance(result, tuple) or len(result) != 2:
                return
            self.log_entries, self.raw_lines = result
        except Exception:
            return
        self.pop_screen()
        if load_used_rust():
            self.notify("Logs loaded with Rust loader", severity="information")
        self._filtered_indices = list(range(len(self.log_entries)))
        self._populate_log_panel()

    def _update_schema_panel(self, the_json: dict[str, Any] | None) -> None:
        tree = self.query_one("#schema-tree", Tree)
        placeholder = self.query_one("#schema-placeholder", Static)
        if the_json is None or the_json.get("_parse_error"):
            tree.display = False
            placeholder.display = True
            return
        tree.display = True
        placeholder.display = False
        tree.clear()
        tree.root.label = "Schema"
        for key, type_or_children in schema_from_object(the_json):
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
            row = self.log_entries[i]
            the_json = row.get("the_json", {})
            if the_json.get("_parse_error"):
                raw = the_json.get("_raw", str(the_json))
                title = (raw[:57] + "...") if len(raw) > 60 else raw if raw else "(parse error)"
            else:
                level_val = row.get("level", "") or "-"
                msg_val = row.get("message", "") or "-"
                ts_val = row.get("timestamp", "") or "-"
                title = f"level: {level_val} | message: {msg_val} | timestamp: {ts_val}"
            pretty = json.dumps(the_json, indent=2) if isinstance(the_json, dict) else str(the_json)
            badge_text = _level_badge_from_level(row.get("level", "")) if not the_json.get("_parse_error") else ""
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
                        self._update_schema_panel(self.log_entries[idx].get("the_json"))
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
            if i < len(self.log_entries):
                parts.append(self.log_entries[i].get("raw", ""))
            else:
                parts.append("")
        self.copy_to_clipboard("\n".join(parts))
        self.notify(f"Copied {len(parts)} line(s)")

    def action_log_settings(self) -> None:
        the_jsons = [r.get("the_json", {}) for r in self.log_entries]
        keys = all_keys_from_entries(the_jsons)
        if not keys:
            self.notify("No log entries to choose key from", severity="warning")
            return
        level_key, message_key, timestamp_key = infer_display_keys(the_jsons)
        self.push_screen(
            LogSettingsScreen(
                keys=keys,
                current_level=level_key,
                current_message=message_key,
                current_timestamp=timestamp_key,
            ),
            self._on_log_settings_done,
        )

    def _on_log_settings_done(self, result: tuple[str | None, str | None, str | None] | None) -> None:
        if result is None:
            return
        level_key, message_key, timestamp_key = result
        if not self.log_path or not self.log_path.exists():
            return
        self.log_entries, self.raw_lines = load_log_file(
            self.log_path,
            level_key=level_key or None,
            message_key=message_key or None,
            timestamp_key=timestamp_key or None,
        )
        if self.filter_text.strip():
            lower = self.filter_text.lower()
            self._filtered_indices = [
                i for i in range(len(self.log_entries))
                if lower in json.dumps(self.log_entries[i].get("the_json", {})).lower()
                or lower in self.log_entries[i].get("raw", "").lower()
            ]
        else:
            self._filtered_indices = list(range(len(self.log_entries)))
        self._populate_log_panel()
        self.notify("Log key config applied")

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
                if lower in json.dumps(self.log_entries[i].get("the_json", {})).lower()
                or lower in self.log_entries[i].get("raw", "").lower()
            ]
        self._populate_log_panel()
        self.notify(f"Filter: {len(self._filtered_indices)} line(s) match")


if __name__ == "__main__":
    log_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = LogUI(log_path=log_path)
    app.run()
