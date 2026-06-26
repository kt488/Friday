"""Friday CLI — Modern robotic terminal interface."""

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


# ── Palette ──

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
    """Minimal, modern robotic terminal interface."""

    def __init__(self, version="2.0.0"):
        self.version = version
        self.console = Console(highlight=False)
        self.session = PromptSession(
            history=InMemoryHistory(),
            auto_suggest=AutoSuggestFromHistory(),
        )
        self.msg_count = 0
        self._start_time = time.time()

    # ── Header ──

    def header(self):
        """Render the FRIDAY header panel."""
        self.console.print()
        self.console.print(Panel(
            Align.center(Text.assemble(
                ("FRIDAY  ", f"bold {CYAN}"),
                (f"v{self.version}", DIM),
            )),
            subtitle=Text("SYSTEM ONLINE — AWAITING INPUT", style=f"dim {DIM}"),
            border_style=CYAN,
            box=box.ROUNDED,
            padding=(0, 2),
            width=52,
        ))
        self.console.print()

    # ── Prompt ──

    def get_input(self):
        """Show prompt, return stripped input."""
        style = PTStyle([
            ("friday", f"bold {CYAN}"),
            ("prompt", f"{DIM}"),
        ])
        try:
            raw = self.session.prompt(
                [("class:friday", "FRIDAY"), ("class:prompt", " > ")],
                style=style,
            )
            return raw.strip()
        except (KeyboardInterrupt, EOFError):
            return "/exit"

    # ── Chat exchange ──

    def user_message(self, text):
        """Display user message in a dim panel."""
        self.console.print()
        self.console.print(Panel(
            Text(text, style=WHITE),
            title=Text("YOU", style=f"bold {DIM}"),
            title_align="left",
            border_style=DIM,
            box=box.MINIMAL,
            padding=(0, 1),
            width=60,
        ))

    def _strip_tool_markers(self, text):
        """Remove raw tool/sendfile markers from displayed text."""
        import re
        # Strip [TOOL: ...] tags
        text = re.sub(r'\s*\[TOOL:\s*\w+\(.*?\)\]\s*', ' ', text, flags=re.DOTALL)
        # Strip **TOOL: ...** tags
        text = re.sub(r'\s*\*\*TOOL:\s*\w+\(.*?\)\*\*\s*', ' ', text, flags=re.DOTALL)
        # Strip [Executed ...] markers
        text = re.sub(r'\s*\[Executed\s+\w+:.*?\]\s*', ' ', text, flags=re.DOTALL)
        # Strip [SEND_FILE_NOW: ...] markers
        text = re.sub(r'\s*\[SEND_FILE_NOW:.*?\]\s*', ' ', text, flags=re.DOTALL)
        # Strip [Error: ...] markers
        text = re.sub(r'\s*\[Error:.*?\]\s*', ' ', text, flags=re.DOTALL)
        # Collapse multiple spaces
        text = re.sub(r' {2,}', ' ', text)
        return text.strip()

    def stream_response(self, generator):
        """Stream AI response in a live-updating markdown panel.

        Tool markers are stripped from display. Execution results
        are shown in a separate panel after streaming completes.
        Yields each cleaned chunk for callers that need it.
        """
        collected = []
        exec_results = []
        file_notifications = []

        # Brief processing indicator
        self.console.print(f"  [{CYAN}]⟐[/] processing...", end="\r")

        with Live(console=self.console, refresh_per_second=10,
                  vertical_overflow="visible", transient=True) as live:
            first = True
            for chunk in generator:
                if first:
                    first = False
                collected.append(chunk)

                # Capture execution results for display
                if chunk.startswith("[SEND_FILE_NOW:"):
                    file_notifications.append(chunk)
                    live.update(Panel(
                        Markdown("_delivering file..._", code_theme="monokai"),
                        title=Text("FRIDAY", style=f"bold {CYAN}"),
                        title_align="left",
                        border_style=CYAN,
                        box=box.ROUNDED,
                        padding=(0, 1),
                        width=60,
                    ))
                    yield chunk
                    continue

                if chunk.startswith("[Executed "):
                    exec_results.append(chunk)
                    live.update(Panel(
                        Markdown("_command executed_", code_theme="monokai"),
                        title=Text("FRIDAY", style=f"bold {CYAN}"),
                        title_align="left",
                        border_style=CYAN,
                        box=box.ROUNDED,
                        padding=(0, 1),
                        width=60,
                    ))
                    yield chunk
                    continue

                text = self._strip_tool_markers("".join(collected))
                if text:
                    live.update(Panel(
                        Markdown(text, code_theme="monokai"),
                        title=Text("FRIDAY", style=f"bold {CYAN}"),
                        title_align="left",
                        border_style=CYAN,
                        box=box.ROUNDED,
                        padding=(0, 1),
                        width=60,
                    ))
                yield chunk

        # Final panel — cleaned text only
        final = self._strip_tool_markers("".join(collected))
        self.console.print()
        if final.strip():
            self.console.print(Panel(
                Markdown(final, code_theme="monokai"),
                title=Text("FRIDAY", style=f"bold {CYAN}"),
                title_align="left",
                border_style=CYAN,
                box=box.ROUNDED,
                padding=(0, 1),
                width=60,
            ))
        self.console.print()

        # Display execution results as styled panels
        for result in exec_results:
            self._show_exec_result(result)

        # Display file delivery notifications
        for notification in file_notifications:
            self._show_file_notification(notification)

    def _show_exec_result(self, marker):
        """Parse [Executed tool: output] and display as a styled panel."""
        import re
        m = re.match(r'\s*\[Executed\s+(\w+):\s*(.*?)\]\s*', marker, re.DOTALL)
        if not m:
            return
        tool = m.group(1)
        output = m.group(2).strip()
        self.console.print(Panel(
            Text(output or "(no output)", style=WHITE),
            title=Text(f"⚡ {tool}", style=f"bold {BLUE}"),
            title_align="left",
            border_style=BLUE,
            box=box.MINIMAL,
            padding=(0, 1),
            width=60,
        ))
        self.console.print()

    def _show_file_notification(self, marker):
        """Parse [SEND_FILE_NOW: path] and display a clean delivery notice."""
        import re, os
        m = re.match(r'\s*\[SEND_FILE_NOW:\s*(.*?)\]\s*', marker, re.DOTALL)
        if not m:
            return
        path = m.group(1).strip()
        if (path.startswith('"') and path.endswith('"')) or \
           (path.startswith("'") and path.endswith("'")):
            path = path[1:-1]
        filename = os.path.basename(path)
        self.console.print(Panel(
            Text(f"File delivered: {filename}", style=GREEN),
            title=Text("FRIDAY", style=f"bold {CYAN}"),
            title_align="left",
            border_style=CYAN,
            box=box.ROUNDED,
            padding=(0, 1),
            width=60,
        ))
        self.console.print()

    # ── Shell command output (from user !command) ──

    def shell_output(self, command, output, returncode=0):
        """Show user-executed shell command and its output."""
        status = GREEN if returncode == 0 else RED
        self.console.print()
        # Command line
        self.console.print(Panel(
            Text(f"$ {command}", style=f"bold {WHITE}"),
            title=Text("CMD", style=f"bold {CYAN}"),
            title_align="left",
            border_style=CYAN,
            box=box.MINIMAL,
            padding=(0, 1),
            width=60,
        ))
        # Output
        if output.strip():
            self.console.print(Panel(
                Text(output.strip(), style=WHITE),
                border_style=DIM,
                box=box.MINIMAL,
                padding=(0, 1),
                width=60,
            ))
        # Exit code
        self.console.print(f"  [{DIM}]exit code: [/][{status}]{returncode}[/]")
        self.console.print()

    # ── Non-streaming response ──

    def response(self, text):
        """Render AI response markdown panel."""
        if not text.strip():
            return
        self.console.print()
        self.console.print(Panel(
            Markdown(text, code_theme="monokai"),
            title=Text("FRIDAY", style=f"bold {CYAN}"),
            title_align="left",
            border_style=CYAN,
            box=box.ROUNDED,
            padding=(0, 1),
            width=60,
        ))
        self.console.print()

    # ── Status bar (for /status command) ──

    def status_bar(self, cpu=42, memory=56, network="ONLINE", agent="READY"):
        """Compact system status bar."""
        def _bar(pct, w=8):
            f = int(pct / 100 * w)
            c = GREEN if pct > 70 else YELLOW if pct > 40 else CYAN
            return f"[{c}]{'█' * f}{'░' * (w - f)}[/]"

        uptime = int(time.time() - self._start_time)
        self.console.print()
        self.console.print(Panel(
            Text.assemble(
                (" CPU ", DIM), (_bar(cpu), ""), (f" {cpu}%  ", WHITE),
                (" MEM ", DIM), (_bar(memory), ""), (f" {memory}%  ", WHITE),
                (" NET ", DIM), (f"{network}  ", GREEN if network == "ONLINE" else RED),
                (" AGENT ", DIM), (f"{agent}  ", CYAN if agent == "READY" else YELLOW),
                (" UP ", DIM), (f"{uptime}s", DIM),
            ),
            border_style=CYAN,
            box=box.MINIMAL,
            padding=(0, 1),
        ))

    # ── Tagged log (for non-chat commands) ──

    def log(self, tag, text, colour):
        """Print a tagged log line (used by ask/api/bot/history/etc)."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.console.print(f"  [{DIM}]{ts}[/] [{colour}][{tag}][/] {text}")

    def info(self, text):     self.log("INFO", text, CYAN)
    def success(self, text):  self.log("SUCCESS", text, GREEN)
    def warning(self, text):  self.log("WARNING", text, YELLOW)
    def error(self, text):    self.log("ERROR", text, RED)
    def system(self, text):   self.log("SYSTEM", text, BLUE)

    # ── Help ──

    def show_help(self):
        """Command reference panel."""
        self.console.print()
        self.console.print(Panel(
            Text.assemble(
                ("COMMANDS\n", f"bold {CYAN}"),
                ("\n", ""),
                *sum([
                    [(f"  /{cmd:<14}", f"{CYAN}"), (f"{desc}\n", DIM)]
                    for cmd, desc in [
                        ("clear",  "clear conversation"),
                        ("status", "system status"),
                        ("agent",  "switch personality"),
                        ("help",   "this list"),
                        ("exit",   "quit"),
                    ]
                ], []),
            ),
            border_style=CYAN,
            box=box.ROUNDED,
            padding=(0, 2),
            width=52,
        ))
        self.console.print()

    # ── Misc ──

    def divider(self):
        """Thin separator line."""
        self.console.print(Rule(char="─", style=DIM))

    def raw(self, text):
        """Print raw text."""
        self.console.print(f"  {text}")

    # ── Shutdown ──

    def shutdown(self):
        """Session summary on exit."""
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
            width=52,
        ))
        self.console.print()
