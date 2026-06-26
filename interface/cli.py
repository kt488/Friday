"""Friday CLI — Futuristic AI terminal interface.

Cyberpunk-inspired design with cyan/dark aesthetic, live status bar,
typed-prefix logging, and smooth streaming responses.
"""

import time
from datetime import datetime

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style as PTStyle
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.markdown import Markdown
from rich.rule import Rule
from rich.table import Table
from rich.style import Style as RichStyle
from rich import box
from rich.align import Align


# ── Colour palette ──

CYAN = "#00e5ff"
BLUE = "#2979ff"
WHITE = "#e0e0e0"
DIM = "#5a5a7a"
GRAY = "#1e1e2e"
DARK = "#12121e"
GREEN = "#00e676"
RED = "#ff1744"
YELLOW = "#ffd600"
MAGENTA = "#d500f9"


class FridayCLI:
    """Futuristic AI terminal with cyberpunk aesthetic."""

    HEADER = """
╔══════════════════════════════════════════════╗
║         FRIDAY AI OPERATING SYSTEM           ║
║                                             ║
║  Version: 5.x  │  Status: ONLINE  │  Mode:   ║
╚══════════════════════════════════════════════╝"""

    def __init__(self, version="2.0.0"):
        self.version = version
        self.console = Console(highlight=False)
        self.session = PromptSession(
            history=InMemoryHistory(),
            auto_suggest=AutoSuggestFromHistory(),
        )
        self.msg_count = 0
        self._start_time = time.time()
        self._welcome()

    # ── Welcome / Header ──

    def _welcome(self):
        """Render the cyberpunk header banner."""
        self.console.print()
        self.console.print(Panel(
            Align.center(
                Text(
                    f"FRIDAY AI OPERATING SYSTEM v{self.version}",
                    style=f"bold {CYAN}",
                )
            ),
            subtitle=Text(
                f"STATUS: ONLINE  │  MODE: ASSISTANT",
                style=f"dim {DIM}",
            ),
            border_style=CYAN,
            box=box.ROUNDED,
            padding=(0, 2),
            width=58,
        ))
        self.console.print()

    # ── Prompt ──

    def get_input(self):
        """Show the FRIDAY > prompt with blinking cursor, return input."""
        style = PTStyle([
            ("friday", f"bold {CYAN}"),
            ("friday.blink", f"bold {CYAN} blink"),
            ("prompt", f"{DIM}"),
        ])
        try:
            raw = self.session.prompt(
                [
                    ("class:friday.blink", "FRIDAY"),
                    ("class:prompt", " > "),
                ],
                style=style,
            )
            return raw.strip()
        except (KeyboardInterrupt, EOFError):
            return "/exit"

    # ── Tagged log messages ──

    def _log(self, tag, text, colour, icon=""):
        """Print a timestamped, tagged log line."""
        ts = datetime.now().strftime("%H:%M:%S")
        tag_str = f"[{tag}]"
        self.console.print(
            f"  [{DIM}]{ts}[/] [{colour}]{tag_str:<10}[/] {icon}{text}"
        )

    def info(self, text):
        self._log("INFO", text, CYAN, "ℹ ")

    def success(self, text):
        self._log("SUCCESS", text, GREEN, "✓ ")

    def warning(self, text):
        self._log("WARNING", text, YELLOW, "⚠ ")

    def error(self, text):
        self._log("ERROR", text, RED, "✖ ")

    def system(self, text):
        self._log("SYSTEM", text, BLUE, "⚙ ")

    def task(self, text):
        self._log("TASK", text, MAGENTA, "▸ ")

    def search(self, text):
        self._log("SEARCH", text, CYAN, "◉ ")

    def analysis(self, text):
        self._log("ANALYSIS", text, f"bold {BLUE}", "▣ ")

    # ── Raw output ──

    def raw(self, text):
        """Print raw text without formatting."""
        self.console.print(f"  {text}")

    # ── AI Response (streaming) ──

    def stream_response(self, generator):
        """Live-updating markdown panel with typing animation.

        Yields each chunk for callers that need it.
        """
        collected = []

        # ── Spinner while waiting for first chunk ──
        spinner = self._spinner()
        first = True

        with Live(
            console=self.console,
            refresh_per_second=10,
            vertical_overflow="visible",
            transient=True,
        ) as live:
            for chunk in generator:
                if first:
                    first = False
                    spinner.close()
                collected.append(chunk)
                text = "".join(collected)
                md = Markdown(text, code_theme="monokai")
                p = Panel(
                    md,
                    border_style=CYAN,
                    box=box.ROUNDED,
                    padding=(0, 1),
                    width=60,
                )
                live.update(p)
                yield chunk

        # ── Final panel stays in scrollback ──
        final = "".join(collected)
        if final.strip():
            self.console.print()
            self.console.print(Panel(
                Markdown(final, code_theme="monokai"),
                border_style=CYAN,
                box=box.ROUNDED,
                padding=(0, 1),
            ))
        else:
            self.console.print()

    def _spinner(self):
        """Return a simple spinner context that runs until .close()."""
        import itertools
        import threading

        spinner_chars = itertools.cycle(["◐", "◓", "◑", "◒"])
        stop = threading.Event()

        def _spin():
            while not stop.is_set():
                self.console.print(
                    f"  [{CYAN}]{next(spinner_chars)}[/] processing...",
                    end="\r",
                )
                time.sleep(0.15)
            self.console.print(" " * 30, end="\r")  # clear line

        t = threading.Thread(target=_spin, daemon=True)
        t.start()
        return type("Spin", (), {"close": lambda: stop.set()})()

    # ── Non-streaming response ──

    def markdown(self, text):
        """Render a block of markdown in a cyberpunk panel."""
        if not text.strip():
            return
        self.console.print()
        self.console.print(Panel(
            Markdown(text, code_theme="monokai"),
            border_style=CYAN,
            box=box.ROUNDED,
            padding=(0, 1),
        ))

    # ── Loading bar ──

    def loading(self, steps=5, label="LOADING"):
        """Animated loading progress bar."""
        self.console.print()
        for i in range(1, steps + 1):
            pct = int(i / steps * 100)
            filled = "▓" * i
            empty = "░" * (steps - i)
            self.console.print(
                f"  [{CYAN}]{filled}[/][{DIM}]{empty}[/] [{CYAN}]{pct}%[/]"
                f"  [{DIM}]{label}[/]",
                end="\r" if i < steps else "\n",
            )
            time.sleep(0.08)
        self.console.print()

    # ── Status bar ──

    def status_bar(self, cpu=42, memory=56, network="ONLINE", agent="READY"):
        """Compact cyberpunk status bar."""
        cpu_bar = self._progress_bar(cpu)
        mem_bar = self._progress_bar(memory)
        uptime = int(time.time() - self._start_time)
        self.console.print()
        self.console.print(Panel(
            Text.assemble(
                (" CPU:", DIM), (f" {cpu_bar} {cpu}%  ", WHITE),
                ("MEM:", DIM), (f" {mem_bar} {memory}%  ", WHITE),
                ("NET:", DIM), (f" {network}  ", GREEN if network == "ONLINE" else RED),
                ("AGENT:", DIM), (f" {agent}  ", CYAN if agent == "READY" else YELLOW),
                ("UP:", DIM), (f" {uptime}s", DIM),
            ),
            border_style=CYAN,
            box=box.MINIMAL,
            padding=(0, 1),
        ))

    def _progress_bar(self, pct, width=10):
        """Render a ██░░ progress bar string."""
        filled = int(pct / 100 * width)
        bar = "█" * filled + "░" * (width - filled)
        if pct > 70:
            colour = GREEN
        elif pct > 40:
            colour = YELLOW
        else:
            colour = CYAN
        return f"[{colour}]{bar}[/]"

    # ── Divider ──

    def divider(self):
        """Thin separator line."""
        self.console.print(Rule(char="─", style=DIM))

    # ── Task view ──

    def task_view(self, tasks):
        """Render multi-task status table.

        tasks: list of (name, status) tuples.
               status is one of RUNNING, WAITING, COMPLETED.
        """
        if not tasks:
            return
        table = Table(
            box=box.SIMPLE,
            border_style=DIM,
            padding=(0, 1),
            show_header=False,
        )
        table.add_column("Task", style=WHITE)
        table.add_column("Status", justify="right")
        for name, status in tasks:
            colour = {
                "RUNNING": GREEN,
                "WAITING": YELLOW,
                "COMPLETED": CYAN,
                "FAILED": RED,
            }.get(status.upper(), DIM)
            table.add_row(f"  TASK  {name}", f"[{colour}]{status}[/]")
        self.console.print(table)

    # ── In-chat help ──

    def show_help(self):
        """Cyberpunk-styled command reference."""
        self.console.print()
        self.console.print(Panel(
            Text.assemble(
                ("COMMANDS\n", f"bold {CYAN}"),
                ("\n", ""),
                *sum([
                    [(f"  /{cmd:<14}", f"{CYAN}"), (f"{desc}\n", DIM)]
                    for cmd, desc in [
                        ("clear",  "clear conversation history"),
                        ("status", "show system status"),
                        ("agent",  "switch agent (/agent off)"),
                        ("help",   "show this command list"),
                        ("exit",   "quit Friday"),
                    ]
                ], []),
            ),
            border_style=CYAN,
            box=box.ROUNDED,
            padding=(0, 2),
            width=56,
        ))
        self.console.print()

    # ── Cleanup ──

    def shutdown(self):
        """Final status on exit."""
        uptime = int(time.time() - self._start_time)
        self.divider()
        self.console.print(Panel(
            Align.center(Text(
                f"FRIDAY v{self.version}  │  Session: {uptime}s  │  Messages: {self.msg_count}",
                style=f"dim {DIM}",
            )),
            border_style=DIM,
            box=box.ROUNDED,
            padding=(0, 2),
            width=58,
        ))
        self.console.print()
