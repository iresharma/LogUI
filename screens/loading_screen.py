"""Full-screen loading screen – minimal style, covers the entire terminal."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text

from textual.app import ComposeResult, RenderResult
from textual.screen import Screen
from textual.widget import Widget


# ── Animation ─────────────────────────────────────────────────────────────────

SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

STATUS_STEPS = [
    "Initializing parser engine",
    "Reading file structure",
    "Tokenizing JSON entries",
    "Building field index",
    "Mapping event timeline",
    "Resolving nested schemas",
    "Optimizing query cache",
    "Preparing render pipeline",
]

# ── Palette ───────────────────────────────────────────────────────────────────

BG      = "#0d1117"
FG      = "#e6edf3"
ACCENT  = "#58a6ff"
MUTED   = "#8b949e"
SUBDUED = "#30363d"
TRACK   = "#21262d"

# ── Layout constants ──────────────────────────────────────────────────────────

CONTENT_W = 44
TRACK_W   = 30
HEAD_W    =  4


class _LoadingWidget(Widget):
    """Custom widget — render() is called by Textual's own pipeline."""

    DEFAULT_CSS = f"""
    _LoadingWidget {{
        width: {CONTENT_W};
        height: auto;
    }}
    """

    def __init__(self, log_path: Path) -> None:
        super().__init__()
        self._log_path = log_path
        self._frame = 0

    # Textual calls this every time refresh() is triggered — returns rich Text.
    def render(self) -> RenderResult:
        return self._build()

    def tick(self) -> None:
        self._frame += 1
        self.refresh()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _bouncer(self) -> Text:
        travel = TRACK_W - HEAD_W
        period = travel * 2
        t      = self._frame % period
        pos    = t if t <= travel else (period - t)

        line = Text(no_wrap=True)
        line.append("─" * pos,            style=TRACK)
        line.append("█" * HEAD_W,         style=f"bold {ACCENT}")
        line.append("─" * (travel - pos), style=TRACK)
        return line

    def _build(self) -> Text:
        f      = self._frame
        spin   = SPINNER[f % len(SPINNER)]
        status = STATUS_STEPS[(f // 50) % len(STATUS_STEPS)]
        dots   = ("." * ((f // 12) % 4)).ljust(3)

        path_str = str(self._log_path)
        max_path = CONTENT_W - 3
        if len(path_str) > max_path:
            path_str = "…" + path_str[-(max_path - 1):]

        def nl(t: Text) -> Text:
            t.append("\n")
            return t

        out = Text(no_wrap=True)

        out.append("\n")
        out.append("L O G U I\n",        style=f"bold {FG}")
        out.append("json log explorer\n", style=f"dim {MUTED}")
        out.append("\n")
        out.append("─" * CONTENT_W + "\n", style=SUBDUED)
        out.append("\n")
        out.append(spin,                  style=ACCENT)
        out.append("  ",                  style="")
        out.append(status,                style=FG)
        out.append(dots + "\n",           style=MUTED)
        out.append("\n")
        out.append_text(self._bouncer())
        out.append("\n\n")
        out.append("─" * CONTENT_W + "\n", style=SUBDUED)
        out.append("\n")
        out.append("▸  ",                 style=SUBDUED)
        out.append(path_str + "\n",        style=MUTED)

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

    def compose(self) -> ComposeResult:
        self._widget = _LoadingWidget(self._log_path)
        yield self._widget

    def on_mount(self) -> None:
        self._interval = self.set_interval(0.07, self._tick)

    def on_unmount(self) -> None:
        if self._interval:
            self._interval.stop()

    def _tick(self) -> None:
        if self._widget is not None:
            self._widget.tick()