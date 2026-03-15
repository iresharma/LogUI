"""Full-screen loading screen – neo-retro terminal aesthetic using Textual."""

from __future__ import annotations

import math
from pathlib import Path

from rich.align import Align
from rich.box import HEAVY, MINIMAL, ROUNDED, SIMPLE_HEAD
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Static

# ── Animation frames ───────────────────────────────────────────────────────────

BRAILLE_SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Braille "waveform" rows — a 2-row 20-col activity ticker
# Each column cycles through vertical fill states
BRAILLE_COLS = ["⣀", "⣄", "⣆", "⣇", "⣧", "⣷", "⣿", "⣷", "⣧", "⣇", "⣆", "⣄"]

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

# ── ASCII title ────────────────────────────────────────────────────────────────
# Fits cleanly inside a 64-col panel
TITLE_LINES = [
    "  ██╗      ██████╗  ██████╗ ██╗   ██╗██╗  ",
    "  ██║     ██╔═══██╗██╔════╝ ██║   ██║██║  ",
    "  ██║     ██║   ██║██║  ███╗██║   ██║██║  ",
    "  ██║     ██║   ██║██║   ██║██║   ██║██║  ",
    "  ███████╗╚██████╔╝╚██████╔╝╚██████╔╝██║  ",
    "  ╚══════╝ ╚═════╝  ╚═════╝  ╚═════╝╚═╝  ",
]

# ── Palette (hex colours, requires a 24-bit colour terminal) ───────────────────
C_GOLD      = "#e8c547"   # title, accents
C_GOLD_DIM  = "#7a6420"   # muted gold
C_GREEN     = "#4ade80"   # spinner, active bar fill
C_GREEN_DIM = "#1a6636"   # empty bar
C_CYAN      = "#67e8f9"   # highlights
C_GREY      = "#6b7280"   # subtitles
C_GREY_DIM  = "#374151"   # separators
C_BORDER    = "#1e3a2f"   # panel border
C_BG        = "#0b0f0e"   # screen background

# Width of the content inside the panel (between padding)
BAR_W = 50


class LoadingScreen(Screen[None]):
    """Full-screen loading view — neo-retro terminal aesthetic."""

    BINDINGS = []

    DEFAULT_CSS = f"""
    LoadingScreen {{
        align: center middle;
        background: {C_BG};
    }}

    #outer {{
        width: 68;
        height: auto;
        align: center middle;
    }}

    #title-block {{
        width: 100%;
        height: auto;
        content-align: center middle;
    }}

    #panel-block {{
        width: 100%;
        height: auto;
        content-align: center middle;
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
        self._frame = 0

    # ── Compose ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="outer"):
                yield Static(self._render_title(), id="title-block")
                yield Static(self._render_panel(), id="panel-block")

    # ── Title (static – rendered once) ────────────────────────────────────────

    def _render_title(self) -> Group:
        title_parts: list[Text] = []
        for i, line in enumerate(TITLE_LINES):
            t = Text()
            # Subtle gradient: brighter in the middle rows
            brightness = C_GOLD if 1 <= i <= 4 else C_GOLD_DIM
            t.append(line, style=f"bold {brightness}")
            title_parts.append(t)

        subtitle = Text(
            "  ◈  structured log explorer  ◈  ",
            style=f"dim {C_GREY}",
            justify="center",
        )
        gap = Text("")
        return Group(*title_parts, gap, subtitle, gap)

    # ── Animated panel ─────────────────────────────────────────────────────────

    def _render_panel(self) -> Panel:
        f = self._frame

        # ── Spinner ──
        spin = BRAILLE_SPIN[f % len(BRAILLE_SPIN)]

        # ── Status label (advances every 40 frames) ──
        status = STATUS_STEPS[(f // 40) % len(STATUS_STEPS)]
        dots   = "." * ((f // 8) % 4)

        # ── Scanner bar ──
        # A bright "beam" sweeps left→right→left using a sine wave
        beam_pos = (math.sin(f * 0.07) + 1) / 2  # 0..1
        beam     = int(beam_pos * (BAR_W - 1))

        bar_chars: list[tuple[str, str]] = []
        for i in range(BAR_W):
            dist = abs(i - beam)
            if dist == 0:
                bar_chars.append(("█", C_GREEN))
            elif dist == 1:
                bar_chars.append(("▓", C_GREEN_DIM))
            elif dist == 2:
                bar_chars.append(("▒", "#143d25"))
            else:
                bar_chars.append(("░", "#0f2019"))

        scanner_line = Text()
        for ch, col in bar_chars:
            scanner_line.append(ch, style=col)

        # ── Activity waveform (two rows, 20 cols of braille) ──
        WAVE_W = 24
        wave_top = Text()
        wave_bot = Text()
        for i in range(WAVE_W):
            # Each column oscillates at its own phase
            phase  = f * 0.18 + i * 0.7
            level  = (math.sin(phase) + 1) / 2  # 0..1
            idx    = int(level * (len(BRAILLE_COLS) - 1))
            col    = BRAILLE_COLS[idx]
            # Colour intensity follows level
            bright = int(0x26 + level * (0x4a - 0x26))
            hex_c  = f"#{bright:02x}{int(level * 0xde):02x}{int(level * 0x80):02x}"
            wave_top.append(col, style=hex_c)

        # ── File path ──
        path_str = str(self._log_path)
        max_path = BAR_W - 2
        if len(path_str) > max_path:
            path_str = "…" + path_str[-(max_path - 1):]

        # ── Corner timestamp-style counter ──
        tick_str = f"frame {f:05d}"

        # ── Assemble content group ──
        content = Group(
            # --- status row ---
            Text.from_markup(
                f"  [{C_GREEN}]{spin}[/]  "
                f"[bold white]{status}[/]"
                f"[{C_GREY}]{dots:<3}[/]"
            ),
            Text(""),
            # --- scanner bar ---
            Text.from_markup(f"  [{C_GREY_DIM}]▕[/]") + scanner_line + Text.from_markup(f"[{C_GREY_DIM}]▏[/]"),
            Text(""),
            # --- activity waveform label ---
            Text.from_markup(f"  [{C_GREY}]activity[/]"),
            Text.from_markup("  ") + wave_top,
            Text(""),
            # --- divider ---
            Text.from_markup(f"  [{C_GREY_DIM}]{'─' * (BAR_W + 2)}[/]"),
            Text(""),
            # --- file path ---
            Text.from_markup(
                f"  [{C_GREY}]file   [/]  [{C_CYAN}]{path_str}[/]"
            ),
            # --- subtle frame counter ---
            Text.from_markup(
                f"  [{C_GREY_DIM}]{tick_str:>{BAR_W - 2}}[/]"
            ),
            Text(""),
        )

        return Panel(
            content,
            title=f"[bold {C_GOLD}] ◉  LOADING [/]",
            subtitle=f"[{C_GREY}] esc to cancel [/]",
            border_style=C_BORDER,
            box=ROUNDED,
            padding=(1, 1),
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._interval = self.set_interval(0.07, self._tick)

    def on_unmount(self) -> None:
        if self._interval:
            self._interval.stop()

    def _tick(self) -> None:
        self._frame += 1
        try:
            self.query_one("#panel-block", Static).update(self._render_panel())
        except Exception:
            pass