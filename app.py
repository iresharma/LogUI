"""Entry point: run LogUI (e.g. python app.py or python -m app)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from rich.text import Text
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
from rust_fuzzy import fuzzy_match
from schema import schema_from_object
from screens.filter_screen import FilterScreen
from screens.loading_screen import LoadingScreen
from widgets.log_container import LogContainer
from widgets.log_ui_header import LogUIHeader
from widgets.search_bar import SearchBar


VERSION = "v0.0.1"

LEVEL_STYLES = {
    "success": "bold white on green3",
    "info": "bold white on steel_blue",
    "debug": "bold white on steel_blue",
    "warn": "bold white on dark_orange3",
    "warning": "bold white on dark_orange3",
    "error": "bold white on red3",
}


def _level_badge_from_level(level: str) -> str:
    """Return a Rich style string for the log level badge background."""
    if not level:
        return "bold white on #555555"
    lvl = level.strip().lower()
    return LEVEL_STYLES.get(lvl, "bold white on #555555")


def _build_title_with_timestamp(
    app: "LogUI", level_val: str, msg_val: str, ts_val: str
) -> Text:
    """Build a single-line title with badge + message + right-aligned timestamp."""
    badge_style = _level_badge_from_level(level_val)
    left = Text.assemble(
        (level_val.upper() or "-", badge_style),
        (": ", "default"),
        (msg_val or "-", "default"),
    )
    if not ts_val:
        return left

    # Try to push timestamp toward the right edge based on app width.
    total_width = max(app.size.width - 8, 0)
    left_width = len(str(left))
    ts_width = len(ts_val)
    padding = max(1, total_width - left_width - ts_width)

    title = Text()
    title.append(left)
    title.append(" " * padding)
    title.append(ts_val, style="dim")
    return title


class LogUI(App[None]):
    """TUI for viewing JSON log files."""

    CSS = """
    #log-container {
        width: 5fr;
        min-width: 20;
        overflow-y: auto;
        overflow-x: hidden;
    }
    #log-container Collapsible.-selected {
        background: $primary 20%;
        border: solid $primary;
    }
    #schema-container {
        width: 2fr;
        min-width: 24;
        border-left: solid $primary;
        padding: 0 1;
    }
    #schema-placeholder {
        padding: 1;
        text-style: italic;
        color: $text-muted;
    }
    Collapsible.-search-current {
        background: $accent 20%;
        border: solid $accent;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("f", "filter", "Filter", show=True),
        Binding("/", "search", "Search", show=True),
        Binding("n", "search_next", "Next match", show=False),
        Binding("shift+n", "search_prev", "Prev match", show=False),
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
        self.search_text: str = ""
        self._search_indices: list[int] = []
        self._search_pos: int | None = None
        self._search_active: bool = False
        self._initial_painted: bool = False
        self._loading_rest: bool = False

    def compose(self) -> ComposeResult:
        yield LogUIHeader(version=VERSION)
        with Horizontal():
            yield LogContainer(id="log-container")
            with Vertical(id="schema-container"):
                yield Static("Schema (hover a log line)", id="schema-placeholder")
                yield Tree("Schema", id="schema-tree")
        yield SearchBar(id="search-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(LOGUI_DARK)
        self.register_theme(LOGUI_LIGHT)
        if self.theme not in self.available_themes:
            self.theme = "logui-dark"
        container = self.query_one("#log-container", LogContainer)
        if self.log_path and self.log_path.exists():
            self._initial_painted = False
            self._loading_rest = False
            # Simple in-panel loading state so the user always sees something.
            container.mount(
                Static("Loading logs…", id="loading-state")
            )
            self.run_worker(
                self._load_log_worker(),
                exclusive=True,
                exit_on_error=False,
            )
        else:
            container.mount(
                Static("No log file loaded. Run: python app.py <path/to/log.txt>", id="empty-state")
            )
        schema_tree = self.query_one("#schema-tree", Tree)
        schema_tree.display = False
        self.query_one("#schema-placeholder", Static).display = True

    async def _load_log_worker(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Run load_log_file in a thread so the loading screen can animate."""
        def on_initial_batch(entries: list[dict[str, Any]], raw_lines: list[str]) -> None:
            # Called from worker thread; hop back to the main thread.
            self.call_from_thread(self._on_initial_batch_from_worker, entries, raw_lines)

        return await asyncio.to_thread(
            load_log_file,
            self.log_path,
            None,
            None,
            None,
            on_initial_batch,
        )

    def _on_initial_batch_from_worker(
        self,
        entries: list[dict[str, Any]],
        raw_lines: list[str],
    ) -> None:
        """Handle the initial tail batch arriving from the loader thread."""
        if self._initial_painted:
            return
        self._initial_painted = True
        self._loading_rest = True
        self.log_entries = entries
        self.raw_lines = raw_lines
        self._recompute_filtered_indices()
        self._populate_log_panel()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """When the load worker finishes, pop the loading screen and show logs."""
        from textual.worker import WorkerState

        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        # Only react to our load worker (result is (entries, raw_lines) on success)
        try:
            if event.state == WorkerState.ERROR:
                # If we've already painted the initial tail batch, the loading
                # screen has been popped in _on_initial_batch_from_worker.
                # Avoid popping again here, which would remove the main app UI.
                if not self._initial_painted:
                    try:
                        self.pop_screen()
                    except Exception:
                        pass
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
        # Remove any in-panel loading indicator before showing actual logs.
        try:
            container = self.query_one("#log-container", LogContainer)
            for child in list(container.children):
                if getattr(child, "id", "") == "loading-state":
                    child.remove()
        except Exception:
            pass
        self._loading_rest = False
        if load_used_rust():
            self.notify("Logs loaded with Rust loader", severity="information")
        self._recompute_filtered_indices()
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
        collapsibles: list[Collapsible] = []
        for i in self._filtered_indices:
            if i >= len(self.log_entries):
                continue
            row = self.log_entries[i]
            the_json = row.get("the_json", {})
            if the_json.get("_parse_error"):
                raw = the_json.get("_raw", str(the_json))
                title: Any = (raw[:57] + "...") if len(raw) > 60 else raw if raw else "(parse error)"
            else:
                level_val = (row.get("level", "") or "-").strip()
                msg_val = row.get("message", "") or "-"
                ts_val = row.get("timestamp", "") or "-"

                title = _build_title_with_timestamp(self, level_val, msg_val, ts_val)

            pretty = json.dumps(the_json, indent=2) if isinstance(the_json, dict) else str(the_json)
            children: list[Widget] = [Static(pretty)]
            collapsible = Collapsible(
                *children,
                title=title,
                collapsed=True,
                collapsed_symbol="→",
                expanded_symbol="▼",
            )
            # Attach logical index without relying on a global ID.
            setattr(collapsible, "log_index", i)
            if i in self.selected_indices:
                collapsible.add_class("-selected")
            if (
                self._search_indices
                and self._search_pos is not None
                and i == self._search_indices[self._search_pos]
            ):
                collapsible.add_class("-search-current")
            collapsibles.append(collapsible)
        if collapsibles:
            container.mount(*collapsibles)

        # After repopulating, if there is an active search, try to keep the current hit focused.
        if self._search_active and self._search_indices and self._search_pos is not None:
            idx = self._search_indices[self._search_pos]
            self._focus_log_row(idx)

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
        rows = [c for c in container.children if isinstance(c, Collapsible)]
        if rows:
            try:
                title = rows[0].query_one("CollapsibleTitle")
                self.screen.set_focus(title)
                rows[0].scroll_visible()
            except NoMatches:
                self.screen.set_focus(container)
        else:
            self.screen.set_focus(container)

    def _focus_log_row(self, logical_index: int) -> None:
        """Focus and scroll to the row whose logical log_index matches."""
        container = self.query_one("#log-container", LogContainer)
        for row in container.children:
            if isinstance(row, Collapsible) and getattr(row, "log_index", None) == logical_index:
                try:
                    title = row.query_one("CollapsibleTitle")
                    self.screen.set_focus(title)
                    row.scroll_visible()
                except NoMatches:
                    pass
                break

    def action_toggle_selection(self) -> None:
        focused = self.focused
        while focused:
            idx = getattr(focused, "log_index", None)
            if isinstance(idx, int):
                if idx in self.selected_indices:
                    self.selected_indices.discard(idx)
                    focused.remove_class("-selected")
                else:
                    self.selected_indices.add(idx)
                    focused.add_class("-selected")
                return
            focused = getattr(focused, "parent", None)

    @on(DescendantFocus)
    def _on_descendant_focus(self, event: DescendantFocus) -> None:
        control: Widget | None = event.control
        while control:
            idx = getattr(control, "log_index", None)
            if isinstance(idx, int) and 0 <= idx < len(self.log_entries):
                self.hovered_log_index = idx
                self._update_schema_panel(self.log_entries[idx].get("the_json"))
                return
            control = getattr(control, "parent", None)
        self.hovered_log_index = None

    def on_search_bar_changed(self, message: SearchBar.Changed) -> None:
        """Live-update search when the search bar text changes."""
        self._on_search_changed(message.value)

    def on_search_bar_submitted(self, message: SearchBar.Submitted) -> None:
        """Handle Enter from the search bar."""
        self._on_search_submitted(message.value)

    def on_search_bar_cancelled(self, message: SearchBar.Cancelled) -> None:
        """Exit search mode on Esc from the search bar."""
        self._on_search_cancelled()

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

    def action_search(self) -> None:
        """Enter Vim-style search mode and focus the search bar."""
        self._search_active = True
        search_bar = self.query_one("#search-bar", SearchBar)
        search_bar.display = True
        search_bar.set_value(self.search_text)
        search_bar.focus_input()
        # Recompute matches for the current text, if any.
        self._recompute_search_indices()

    def action_search_next(self) -> None:
        """Jump to the next search match (n)."""
        if not self._search_indices:
            return
        if self._search_pos is None:
            self._search_pos = 0
        else:
            self._search_pos = (self._search_pos + 1) % len(self._search_indices)
        self._focus_log_row(self._search_indices[self._search_pos])
        self._update_search_status()

    def action_search_prev(self) -> None:
        """Jump to the previous search match (N / shift+n)."""
        if not self._search_indices:
            return
        if self._search_pos is None:
            self._search_pos = 0
        else:
            self._search_pos = (self._search_pos - 1) % len(self._search_indices)
        self._focus_log_row(self._search_indices[self._search_pos])
        self._update_search_status()

    def _recompute_search_indices(self) -> None:
        """Recompute search matches over the current filtered indices."""
        pattern = self.search_text.strip()
        self._search_indices = []
        self._search_pos = None

        if not pattern:
            self._update_search_status()
            return

        scored: list[tuple[int, int]] = []
        for idx in self._filtered_indices:
            if idx >= len(self.log_entries):
                continue
            row = self.log_entries[idx]
            the_json = row.get("the_json", {})
            raw = row.get("raw", "")
            try:
                json_part = json.dumps(the_json)
            except TypeError:
                json_part = str(the_json)
            candidate = f"{json_part}\n{raw}"
            score = fuzzy_match(pattern, candidate)
            if isinstance(score, (int, float)) and score >= 0:
                scored.append((int(score), idx))

        scored.sort(key=lambda t: (-t[0], t[1]))
        self._search_indices = [idx for _, idx in scored]
        if self._search_indices:
            self._search_pos = 0
            self._focus_log_row(self._search_indices[0])
        self._update_search_status()

    def _update_search_status(self) -> None:
        """Update the search bar's status label with match counts."""
        try:
            search_bar = self.query_one("#search-bar", SearchBar)
        except NoMatches:
            return
        total = len(self._search_indices)
        if total == 0 or self.search_text.strip() == "":
            status = ""
        else:
            current = (self._search_pos or 0) + 1 if self._search_pos is not None else 1
            status = f"{current}/{total}"
        search_bar.update_status(status)

    def _on_search_changed(self, value: str) -> None:
        """Handle live search text changes from the search bar."""
        self.search_text = value
        self._recompute_search_indices()

    def _on_search_submitted(self, value: str) -> None:
        """Handle Enter from the search bar."""
        self.search_text = value
        self._recompute_search_indices()

    def _on_search_cancelled(self) -> None:
        """Exit search mode and hide the search bar."""
        self._search_active = False
        try:
            search_bar = self.query_one("#search-bar", SearchBar)
            search_bar.display = False
        except NoMatches:
            pass

    def action_filter(self) -> None:
        self.push_screen(FilterScreen(current=self.filter_text), self._on_filter_done)

    def _on_filter_done(self, filter_text: str | None) -> None:
        if filter_text is None:
            return
        self.filter_text = filter_text
        self._recompute_filtered_indices()
        # Filter affects which rows are visible; recompute search matches if needed.
        if self.search_text.strip():
            self._recompute_search_indices()
        self._populate_log_panel()
        self.notify(f"Filter: {len(self._filtered_indices)} line(s) match")

    @on(FilterScreen.Changed)
    def _on_filter_changed_live(self, event: FilterScreen.Changed) -> None:
        """Live-update filtering while the filter dialog is open."""
        self.filter_text = event.value
        self._recompute_filtered_indices()
        self._populate_log_panel()
        if self.search_text.strip():
            self._recompute_search_indices()

    def _recompute_filtered_indices(self) -> None:
        """Recompute which log indices match the current filter text."""
        if not self.filter_text.strip():
            self._filtered_indices = list(range(len(self.log_entries)))
            return

        pattern = self.filter_text
        indices: list[int] = []
        for i, row in enumerate(self.log_entries):
            the_json = row.get("the_json", {})
            raw = row.get("raw", "")
            try:
                json_part = json.dumps(the_json)
            except TypeError:
                json_part = str(the_json)
            candidate = f"{json_part}\n{raw}"
            if fuzzy_match(pattern, candidate):
                indices.append(i)
        self._filtered_indices = indices


if __name__ == "__main__":
    log_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = LogUI(log_path=log_path)
    app.run()
