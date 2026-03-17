"""Full-screen loading screen – minimal style, covers the entire terminal."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text

from textual.app import ComposeResult, RenderResult
from textual.screen import Screen
from textual.widget import Widget


# ── Animation ─────────────────────────────────────────────────────────────────

SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# ── Palette ───────────────────────────────────────────────────────────────────

BG      = "#0d1117"
FG      = "#e6edf3"
ACCENT  = "#58a6ff"
ACCENT_SOFT = "#1f6feb"
ACCENT_ALT  = "#a5d6ff"
MUTED   = "#8b949e"
SUBDUED = "#30363d"
TRACK   = "#21262d"

class _LoadingWidget(Widget):
    """Simple centered logo + spinner widget."""

    DEFAULT_CSS = """
    _LoadingWidget {
        width: 100%;
        height: 100%;
        content-align: center middle;
    }
    """

    def __init__(self, log_path: Path) -> None:
        super().__init__()
        self._log_path = log_path
        self._frame = 0

    def tick(self) -> None:
        """Advance the spinner frame and trigger a re-render."""
        self._frame += 1
        self.refresh()

    def render(self) -> RenderResult:
        spin = SPINNER[self._frame % len(SPINNER)]

        path_str = str(self._log_path)
        if len(path_str) > 60:
            path_str = "…" + path_str[-59:]

        out = Text(no_wrap=False, justify="center")
        out.append("\n\n")
        out.append("L O G U I\n", style=f"bold {ACCENT_ALT}")
        out.append("json log explorer\n", style=f"dim {MUTED}")
        out.append("\n\n")
        out.append(spin + "  ", style=ACCENT)
        out.append("Loading logs…\n", style=FG)
        out.append("\n")
        out.append(path_str + "\n", style=MUTED)

        return out


class LoadingScreen(Screen[None]):
    """Full-screen loading view – minimal, borderless, covers entire terminal."""

    BINDINGS = []

    DEFAULT_CSS = f"""
    LoadingScreen {{
        align: center middle;
        background: {BG};
    }}
    """

    def __init__(
        self,
        log_path: Path,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._log_path = log_path
        self._widget: _LoadingWidget | None = None
        self._interval = None

    def compose(self) -> ComposeResult:
        self._widget = _LoadingWidget(self._log_path)
        yield self._widget

    def on_mount(self) -> None:
        self._interval = self.set_interval(0.07, self._tick)

    def on_unmount(self) -> None:
        if self._interval is not None:
            self._interval.stop()

    def _tick(self) -> None:
        if self._widget is not None:
            self._widget.tick()