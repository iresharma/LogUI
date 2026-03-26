"""Scrollable log list with arrow-key navigation between rows."""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Collapsible


class LogContainer(ScrollableContainer):
    """Scrollable container for log rows; Up/Down move focus between rows."""

    BINDINGS = [
        Binding("up", "focus_previous_row", "Previous row", show=False, priority=True),
        Binding("down", "focus_next_row", "Next row", show=False, priority=True),
    ]

    def _log_rows(self) -> list[Widget]:
        """Collapsible rows with a logical log_index (set by LogUI)."""
        return [
            c
            for c in self.children
            if isinstance(c, Collapsible) and getattr(c, "log_index", None) is not None
        ]

    def _focused_row_index(self) -> int | None:
        focused = self.screen.focused
        if not focused:
            return None
        rows = self._log_rows()
        for i, row in enumerate(rows):
            if focused == row or row in focused.ancestors_with_self:
                return i
        return None

    def action_focus_previous_row(self) -> None:
        rows = self._log_rows()
        if not rows:
            return
        idx = self._focused_row_index()
        if idx is None:
            self.screen.set_focus(rows[0].query_one("CollapsibleTitle"))
            rows[0].scroll_visible()
            return
        if idx <= 0:
            return
        prev_row = rows[idx - 1]
        try:
            title = prev_row.query_one("CollapsibleTitle")
            self.screen.set_focus(title)
            prev_row.scroll_visible()
        except NoMatches:
            pass

    def action_focus_next_row(self) -> None:
        rows = self._log_rows()
        if not rows:
            return
        idx = self._focused_row_index()
        if idx is None:
            self.screen.set_focus(rows[0].query_one("CollapsibleTitle"))
            rows[0].scroll_visible()
            return
        if idx >= len(rows) - 1:
            return
        next_row = rows[idx + 1]
        try:
            title = next_row.query_one("CollapsibleTitle")
            self.screen.set_focus(title)
            next_row.scroll_visible()
        except NoMatches:
            pass
