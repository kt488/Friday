#!/usr/bin/env python3
"""
Friday Terminal — Native Python Shell + AI Assistant
=====================================================
A hybrid terminal: type shell commands directly, or chat naturally with Friday.
Prefix with ! to force shell execution. / commands control the terminal itself.
"""
import os
import sys
import shutil
import shlex
import signal
import time
import stat
import pwd
import grp
import glob
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style as PTStyle
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.markdown import Markdown
from rich.rule import Rule
from rich.syntax import Syntax
from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.layout import Layout

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
ORANGE = "#ff9100"

# ── Built-in shell commands ──

BUILTIN_COMMANDS = {
    "cd", "pwd", "ls", "echo", "cat", "clear", "help", "exit", "quit",
    "mkdir", "rmdir", "rm", "cp", "mv", "touch", "head", "tail", "wc",
    "date", "whoami", "id", "uname", "which", "type", "du", "df", "ps",
    "kill", "ping", "curl", "wget", "grep", "sort", "uniq", "cut",
    "tr", "tee", "env", "export", "alias", "source", "history",
    "chmod", "chown", "ln", "readlink", "realpath", "basename", "dirname",
    "find", "locate", "tree", "whereis", "watch", "sleep", "time",
    "true", "false", "yes", "seq", "printf", "test", "eval",
    "exec", "jobs", "fg", "bg", "file", "stat", "nproc",
    "free", "uptime",
}

FRIDAY_INTERNAL = {"/help", "/clear", "/exit", "/quit", "/status", "/history", "/agent", "/shell", "/newsandbox"}


def _path_completions(text: str) -> list[str]:
    """Basic path glob completion."""
    if not text:
        text = "."
    parts = text.split()
    prefix = parts[-1] if parts else ""
    expanded = os.path.expanduser(prefix)
    dirname = os.path.dirname(expanded) or "."
    basename = os.path.basename(expanded)
    try:
        entries = os.listdir(dirname)
    except OSError:
        return []
    matches = []
    for e in entries:
        if e.startswith(basename):
            full = os.path.join(dirname, e)
            if os.path.isdir(full):
                matches.append(prefix[:len(prefix)-len(basename)] + e + "/")
            else:
                matches.append(prefix[:len(prefix)-len(basename)] + e + " ")
    return matches


class FridayTerminalCompleter(Completer):
    """Tab completer for the Friday Terminal."""
    def __init__(self, commands: set):
        self.commands = commands

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text:
            for cmd in sorted(self.commands):
                yield Completion(cmd, start_position=0)
            return

        # If first word, complete commands
        parts = text.split()
        if len(parts) <= 1 and not text.endswith(" "):
            word = parts[0] if parts else text
            for cmd in sorted(self.commands):
                if cmd.startswith(word) and word:
                    yield Completion(cmd, start_position=-len(word))
            # Also try path completions
            for p in _path_completions(text):
                if p != text:
                    yield Completion(p, start_position=-len(text))
            return

        # Path completion for arguments
        prefix = parts[-1] if parts else ""
        for p in _path_completions(prefix):
            start = len(text) - len(prefix)
            yield Completion(p, start_position=start - len(text))


class FridayTerminal:
    """Hybrid Python shell + Friday AI terminal.

    Operates in an isolated sandbox directory so all file operations
    (shell commands, AI-triggered commands) stay out of Friday's root.
    """

    def __init__(self, version="2.0.0"):
        self.version = version
        self.console = Console(highlight=False)
        self.pt_style = PTStyle.from_dict({
            "prompt": f"bold {CYAN}",
            "prompt.dim": f"dim {DIM}",
        })
        all_commands = FRIDAY_INTERNAL
        self.session = PromptSession(
            history=InMemoryHistory(),
            auto_suggest=AutoSuggestFromHistory(),
            completer=FridayTerminalCompleter(all_commands),
            style=self.pt_style,
            enable_history_search=True,
            complete_while_typing=False,
        )

        # ── Isolated sandbox ──
        sandbox_root = os.environ.get("FRIDAY_SANDBOX")
        if sandbox_root:
            pass
        elif os.access("/tmp", os.W_OK):
            sandbox_root = "/tmp/friday-sandbox"
        else:
            sandbox_root = os.path.expanduser("~/.friday/sandbox")
        self.sandbox_dir = os.path.join(sandbox_root, f"session-{int(time.time())}")
        os.makedirs(self.sandbox_dir, exist_ok=True)
        self.cwd = self.sandbox_dir
        os.chdir(self.cwd)

        self._start_time = time.time()
        self._cmd_history: list[str] = []
        self._friday = None  # Lazy init
        self._conversation_context: list[dict] = [
            {
                "role": "system",
                "message": (
                    f"You are in an isolated sandbox: {self.sandbox_dir}\n"
                    "All file operations and shell commands run here.\n"
                    "Use [TOOL: execute_shell('command')] when you need to run commands.\n"
                    "The user cannot run shell commands directly — only you can."
                ),
            }
        ]
        self._active_agent: Optional[str] = None
        self.running = True

    @property
    def friday(self):
        if self._friday is None:
            try:
                from core.friday import FridayCore
                self._friday = FridayCore()
            except Exception as e:
                self._friday = False
        return self._friday if self._friday else None

    # ── Prompt ──

    def _prompt_text(self) -> str:
        host = os.uname().nodename.split(".")[0]
        user = os.environ.get("USER", "user")
        # Shorten cwd
        cwd = self.cwd
        home = os.path.expanduser("~")
        if cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        return [
            ("class:prompt", f" ┌─"),
            ("class:prompt", f"[{user}@{host}]"),
            ("class:prompt.dim", f" {cwd}"),
            ("class:prompt", f"\n └─❯ "),
        ]

    # ── Display helpers ──

    def print_header(self):
        self.console.print()
        self.console.print(Panel(
            Align.center(Text.assemble(
                ("⚡ FRIDAY TERMINAL  ", f"bold {CYAN}"),
                (f"v{self.version}", DIM),
            )),
            subtitle=Text("SHELL + AI  —  type /help for commands", style=f"dim {DIM}"),
            border_style=CYAN,
            box=box.ROUNDED,
            padding=(0, 2),
            width=58,
        ))
        self.console.print(f" [{DIM}]sandbox:[/] {self.sandbox_dir}")
        self.console.print()

    def print_error(self, msg: str):
        self.console.print(f" [{RED}]ERROR:[/] {msg}")

    def print_info(self, msg: str):
        self.console.print(f" [{CYAN}]∙[/] {msg}")

    def print_success(self, msg: str):
        self.console.print(f" [{GREEN}]✓[/] {msg}")

    def print_warn(self, msg: str):
        self.console.print(f" [{YELLOW}]⚠[/] {msg}")

    def print_system(self, msg: str):
        self.console.print(f" [{DIM}]◆[/] {msg}")

    def print_markdown(self, text: str):
        self.console.print(Markdown(text))

    def divider(self, char="─", width=None):
        w = width or self.console.width
        self.console.print(f" [{DIM}]{char * w}[/]")

    # ── Shell execution ──

    def _exec_shell(self, command: str) -> int:
        """Execute a shell command directly. Returns exit code."""
        if not command.strip():
            return 0

        parts = shlex.split(command)
        cmd = parts[0]
        args = parts[1:]

        # ── Builtins ──

        if cmd == "cd":
            try:
                target = args[0] if args else os.path.expanduser("~")
                os.chdir(target)
                self.cwd = os.getcwd()
            except FileNotFoundError:
                self.print_error(f"cd: {target}: No such directory")
                return 1
            except PermissionError:
                self.print_error(f"cd: {target}: Permission denied")
                return 1
            return 0

        if cmd == "pwd":
            self.console.print(self.cwd)
            return 0

        if cmd == "echo":
            self.console.print(" ".join(args))
            return 0

        if cmd == "clear":
            self.console.clear()
            return 0

        if cmd == "ls":
            return self._builtin_ls(args)

        if cmd == "cat":
            return self._builtin_cat(args)

        if cmd == "mkdir":
            try:
                for d in args:
                    os.makedirs(d, exist_ok=True)
                return 0
            except OSError as e:
                self.print_error(f"mkdir: {e}")
                return 1

        if cmd == "rmdir":
            try:
                for d in args:
                    os.rmdir(d)
                return 0
            except OSError as e:
                self.print_error(f"rmdir: {e}")
                return 1

        if cmd == "rm":
            recursive = "-r" in args or "-rf" in args
            force = "-f" in args or "-rf" in args
            targets = [a for a in args if not a.startswith("-")]
            for t in targets:
                try:
                    p = Path(t)
                    if p.is_dir() and not recursive:
                        self.print_error(f"rm: {t}: is a directory (use -r)")
                        continue
                    if recursive:
                        shutil.rmtree(t, ignore_errors=force)
                    else:
                        p.unlink()
                except OSError as e:
                    if not force:
                        self.print_error(f"rm: {e}")
                        return 1
            return 0

        if cmd == "cp":
            if len(args) < 2:
                self.print_error("cp: missing arguments")
                return 1
            try:
                shutil.copy2(args[0], args[1])
                return 0
            except OSError as e:
                self.print_error(f"cp: {e}")
                return 1

        if cmd == "mv":
            if len(args) < 2:
                self.print_error("mv: missing arguments")
                return 1
            try:
                shutil.move(args[0], args[1])
                return 0
            except OSError as e:
                self.print_error(f"mv: {e}")
                return 1

        if cmd == "touch":
            for f in args:
                try:
                    Path(f).touch()
                except OSError as e:
                    self.print_error(f"touch: {e}")
                    return 1
            return 0

        if cmd == "head":
            return self._builtin_head(args)

        if cmd == "tail":
            return self._builtin_tail(args)

        if cmd == "wc":
            return self._builtin_wc(args)

        if cmd == "date":
            fmt = " ".join(args).strip() or None
            if fmt:
                try:
                    self.console.print(datetime.now().strftime(fmt))
                except ValueError as e:
                    self.print_error(f"date: {e}")
                    return 1
            else:
                self.console.print(datetime.now().strftime("%a %b %d %H:%M:%S %Z %Y"))
            return 0

        if cmd == "whoami":
            self.console.print(os.environ.get("USER", "unknown"))
            return 0

        if cmd == "id":
            self.console.print(f"uid={os.getuid()}({os.environ.get('USER','?')}) "
                               f"gid={os.getgid()}({os.environ.get('USER','?')})")
            return 0

        if cmd == "uname":
            u = os.uname()
            if "-a" in args:
                self.console.print(f"{u.sysname} {u.nodename} {u.release} {u.version} {u.machine}")
            else:
                self.console.print(u.sysname)
            return 0

        if cmd == "which":
            for name in args:
                path = shutil.which(name)
                if path:
                    self.console.print(path)
                else:
                    self.print_error(f"which: {name}: not found")
                    return 1
            return 0

        if cmd == "env":
            for k, v in sorted(os.environ.items()):
                self.console.print(f"{k}={v}")
            return 0

        if cmd == "history":
            for i, c in enumerate(self._cmd_history):
                self.console.print(f"  {i+1:4d}  {c}")
            return 0

        if cmd == "du":
            return self._builtin_du(args)

        if cmd == "df":
            return self._builtin_df(args)

        if cmd == "ps":
            return self._builtin_ps(args)

        if cmd == "free":
            return self._builtin_free()

        if cmd == "uptime":
            uptime_sec = time.time() - self._start_time
            hours, remainder = divmod(int(uptime_sec), 3600)
            minutes, seconds = divmod(remainder, 60)
            self.console.print(f"up {hours}:{minutes:02d}:{seconds:02d}")
            return 0

        if cmd == "file":
            return self._builtin_file(args)

        if cmd == "stat":
            return self._builtin_stat(args)

        if cmd == "true":
            return 0

        if cmd == "false":
            return 1

        if cmd in ("exit", "quit"):
            self.running = False
            return 0

        if cmd == "help":
            self._show_help()
            return 0

        if cmd == "sleep":
            try:
                secs = float(args[0]) if args else 1
                time.sleep(secs)
                return 0
            except (ValueError, IndexError):
                self.print_error("sleep: numeric argument required")
                return 1

        if cmd == "chmod":
            if len(args) < 2:
                self.print_error("chmod: missing arguments")
                return 1
            try:
                mode = int(args[0], 8)
                os.chmod(args[1], mode)
                return 0
            except (ValueError, OSError) as e:
                self.print_error(f"chmod: {e}")
                return 1

        if cmd == "ln":
            if len(args) < 2:
                self.print_error("ln: missing arguments")
                return 1
            symbolic = "-s" in args
            targets = [a for a in args if not a.startswith("-")]
            try:
                if symbolic:
                    os.symlink(targets[0], targets[1])
                else:
                    os.link(targets[0], targets[1])
                return 0
            except OSError as e:
                self.print_error(f"ln: {e}")
                return 1

        # ── Unknown builtin ──
        # Fall through to external execution
        return self._exec_external(command)

    def _exec_external(self, command: str) -> int:
        """Run an external program."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=False,
                timeout=60,
                cwd=self.cwd,
            )
            return result.returncode
        except subprocess.TimeoutExpired:
            self.print_error("Command timed out (60s limit).")
            return 124
        except FileNotFoundError:
            self.print_error(f"Command not found: {command.split()[0]}")
            return 127
        except Exception as e:
            self.print_error(str(e))
            return 1

    # ── Builtin implementations ──

    def _builtin_ls(self, args):
        paths = args if args else ["."]
        show_all = "-a" in args
        long = "-l" in args
        human = "-h" in args
        targets = [a for a in args if not a.startswith("-")] or ["."]

        for ti, target in enumerate(targets):
            try:
                entries = os.listdir(target)
            except OSError as e:
                self.print_error(f"ls: {target}: {e}")
                continue

            if len(targets) > 1:
                if ti > 0:
                    self.console.print()
                self.console.print(f"[{DIM}]{target}:[/]")

            if not show_all:
                entries = [e for e in entries if not e.startswith(".")]

            entries.sort()

            if long:
                for e in entries:
                    fp = os.path.join(target, e)
                    try:
                        st = os.lstat(fp)
                    except OSError:
                        continue
                    perms = stat.filemode(st.st_mode)
                    nlink = st.st_nlink
                    try:
                        pw = pwd.getpwuid(st.st_uid)
                        uid_str = pw.pw_name
                    except KeyError:
                        uid_str = str(st.st_uid)
                    try:
                        gr = grp.getgrgid(st.st_gid)
                        gid_str = gr.gr_name
                    except KeyError:
                        gid_str = str(st.st_gid)
                    size = st.st_size
                    if human:
                        for unit in ["B", "K", "M", "G", "T"]:
                            if size < 1024:
                                break
                            size /= 1024
                        size_str = f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
                    else:
                        size_str = str(st.st_size)
                    mtime = datetime.fromtimestamp(st.st_mtime).strftime("%b %d %H:%M")
                    color = CYAN if stat.S_ISDIR(st.st_mode) else (
                        GREEN if stat.S_ISLNK(st.st_mode) else WHITE)
                    name = e
                    if stat.S_ISLNK(st.st_mode):
                        try:
                            link = os.readlink(fp)
                            name = f"{e} -> {link}"
                        except OSError:
                            pass
                    self.console.print(
                        f"{perms} {nlink:2d} {uid_str:<8} {gid_str:<8} "
                        f"{size_str:>6} {mtime} [bold {color}]{name}[/]"
                    )
            else:
                # Column output
                cols = shutil.get_terminal_size().columns
                max_w = max(len(e) for e in entries) + 2 if entries else 1
                per_row = max(1, cols // max_w)
                for i in range(0, len(entries), per_row):
                    row = entries[i:i+per_row]
                    line = ""
                    for e in row:
                        fp = os.path.join(target, e)
                        is_dir = os.path.isdir(fp)
                        color = CYAN if is_dir else (GREEN if os.path.islink(fp) else WHITE)
                        line += f"[{color}]{e:<{max_w}}[/]"
                    self.console.print(line)
        return 0

    def _builtin_cat(self, args):
        if not args:
            self.print_error("cat: missing filename")
            return 1
        for f in args:
            try:
                with open(f) as fh:
                    content = fh.read()
                self.console.print(content, end="")
            except OSError as e:
                self.print_error(f"cat: {f}: {e}")
                return 1
        return 0

    def _builtin_head(self, args):
        n = 10
        rest = []
        for a in args:
            if a.startswith("-") and a[1:].isdigit():
                n = int(a[1:])
            elif a.startswith("-n") and len(a) > 2:
                n = int(a[2:])
            else:
                rest.append(a)
        files = rest if rest else ["-"]
        for f in files:
            try:
                if f == "-":
                    lines = sys.stdin.read().splitlines()
                else:
                    with open(f) as fh:
                        lines = fh.readlines()
                self.console.print("".join(lines[:n]), end="")
            except OSError as e:
                self.print_error(f"head: {f}: {e}")
                return 1
        return 0

    def _builtin_tail(self, args):
        n = 10
        rest = []
        for a in args:
            if a.startswith("-") and a[1:].isdigit():
                n = int(a[1:])
            elif a.startswith("-n") and len(a) > 2:
                n = int(a[2:])
            else:
                rest.append(a)
        files = rest if rest else ["-"]
        for f in files:
            try:
                if f == "-":
                    lines = sys.stdin.read().splitlines()
                else:
                    with open(f) as fh:
                        lines = fh.readlines()
                self.console.print("".join(lines[-n:]), end="")
            except OSError as e:
                self.print_error(f"tail: {f}: {e}")
                return 1
        return 0

    def _builtin_wc(self, args):
        files = args if args else ["-"]
        total_lines = total_words = total_chars = 0
        for f in files:
            try:
                if f == "-":
                    text = sys.stdin.read()
                else:
                    with open(f) as fh:
                        text = fh.read()
                lines = text.count("\n")
                words = len(text.split())
                chars = len(text)
                self.console.print(f"{lines:6d} {words:6d} {chars:6d} {f}")
                total_lines += lines
                total_words += words
                total_chars += chars
            except OSError as e:
                self.print_error(f"wc: {f}: {e}")
                return 1
        if len(files) > 1:
            self.console.print(f"{total_lines:6d} {total_words:6d} {total_chars:6d} total")
        return 0

    def _builtin_du(self, args):
        targets = [a for a in args if not a.startswith("-")] or ["."]
        for t in targets:
            try:
                total = sum(f.stat().st_size for f in Path(t).rglob("*") if f.is_file())
                self.console.print(f"{total:>8d}  {t}")
            except OSError as e:
                self.print_error(f"du: {t}: {e}")
                return 1
        return 0

    def _builtin_df(self, args):
        targets = [a for a in args if not a.startswith("-")] or ["/"]
        self.console.print(f"{'Filesystem':<20} {'Size':>8} {'Used':>8} {'Avail':>8} {'Use%':>6} {'Mounted':<20}")
        self.divider("-", 70)
        for t in targets:
            try:
                st = os.statvfs(t)
                size = st.f_frsize * st.f_blocks
                free = st.f_frsize * st.f_bfree
                avail = st.f_frsize * st.f_bavail
                used = size - free
                pct = used / size * 100 if size else 0
                self.console.print(
                    f"{'dev':<20} {self._hsize(size):>8} {self._hsize(used):>8} "
                    f"{self._hsize(avail):>8} {pct:5.1f}% {t:<20}"
                )
            except OSError as e:
                self.print_error(f"df: {t}: {e}")
                return 1
        return 0

    def _builtin_ps(self, args):
        try:
            result = subprocess.run(
                ["ps"] + args, capture_output=True, text=True, timeout=5
            )
            self.console.print(result.stdout)
            return result.returncode
        except Exception as e:
            self.print_error(f"ps: {e}")
            return 1

    def _builtin_free(self):
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1])
                    elif line.startswith("MemAvailable:"):
                        avail = int(line.split()[1])
                        break
            used = total - avail
            self.console.print(f"{'':>12} {'total':>8} {'used':>8} {'free':>8}")
            self.console.print(
                f"{'Mem:':>12} {self._hsize(total*1024):>8} "
                f"{self._hsize(used*1024):>8} {self._hsize(avail*1024):>8}"
            )
            return 0
        except Exception:
            self.print_error("free: not available")
            return 1

    def _builtin_file(self, args):
        for f in args:
            try:
                st = os.lstat(f)
                kind = "directory" if stat.S_ISDIR(st.st_mode) else (
                    "symbolic link" if stat.S_ISLNK(st.st_mode) else (
                        "fifo" if stat.S_ISFIFO(st.st_mode) else (
                            "socket" if stat.S_ISSOCK(st.st_mode) else "regular file")))
                self.console.print(f"{f}: {kind}")
            except OSError as e:
                self.print_error(f"file: {f}: {e}")
                return 1
        return 0

    def _builtin_stat(self, args):
        for f in args:
            try:
                st = os.lstat(f)
                self.console.print(f"  File: {f}")
                self.console.print(f"  Size: {st.st_size}")
                self.console.print(f"  Mode: {stat.filemode(st.st_mode)} ({oct(st.st_mode)})")
                self.console.print(f"  UID: {st.st_uid}  GID: {st.st_gid}")
                self.console.print(f"  Birth: {datetime.fromtimestamp(st.st_ctime)}")
                self.console.print(f"  Modify: {datetime.fromtimestamp(st.st_mtime)}")
            except OSError as e:
                self.print_error(f"stat: {f}: {e}")
                return 1
        return 0

    @staticmethod
    def _hsize(n: int) -> str:
        for unit in ["B", "K", "M", "G", "T"]:
            if n < 1024:
                return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
            n /= 1024
        return f"{n:.1f}P"

    # ── Friday AI integration ──

    def _chat_with_friday(self, user_input: str):
        """Send message to Friday AI and stream response."""
        if not self.friday:
            self.print_error("Friday core not available.")
            return

        self._conversation_context.append({"role": "user", "message": user_input})
        self.console.print()
        self.console.print(f" [{CYAN}]┃[/] [bold {WHITE}]Friday[/] [dim]thinking...[/]")
        self.console.print(f" [{CYAN}]┃[/] ", end="")

        full_response = ""
        try:
            for chunk in self.friday.process_message_stream(
                user_input,
                conversation_context=self._conversation_context,
                agent_name=self._active_agent,
            ):
                full_response += chunk
                self.console.print(chunk, end="")
            self.console.print()
            self._conversation_context.append({"role": "assistant", "message": full_response})
        except Exception as e:
            self.console.print()
            self.print_error(f"Friday error: {e}")

    # ── Help ──

    def _show_help(self):
        help_text = f"""
# Friday Terminal — Help

**Sandbox:** All commands run in an isolated directory at `{self.sandbox_dir}`.
Friday's project root is never touched.

## Commands (/)
| Command | Description |
|---------|-------------|
| `/help`  | Show this help |
| `/clear` | Clear the screen |
| `/exit` or `/quit` | Exit the terminal |
| `/status` | Show system status |
| `/history` | Show conversation history |
| `/agent NAME` | Set active agent |
| `/agent off` | Deactivate agent |
| `/newsandbox` | Reset to a fresh sandbox directory |

## AI-Only Mode
Type any message in natural language. Friday AI will respond and can execute
commands in the sandbox when needed. Direct shell access is disabled — all
operations are handled by Friday AI.
"""
        self.console.print(Markdown(help_text))

    def _cmd_status(self):
        """Show terminal system status."""
        self.console.print()
        self.console.print(Panel(
            Text.assemble(
                ("TERMINAL STATUS", f"bold {CYAN}"),
            ),
            border_style=CYAN,
            box=box.ROUNDED,
        ))
        self.divider()
        self.console.print(f"  [{WHITE}]CWD:[/]     {self.cwd}")
        self.console.print(f"  [{WHITE}]Uptime:[/]  {time.time() - self._start_time:.0f}s")
        self.console.print(f"  [{WHITE}]Agent:[/]   {self._active_agent or 'None'}")
        self.console.print(f"  [{WHITE}]History:[/] {len(self._cmd_history)} commands, {len(self._conversation_context)} messages")
        self.console.print(f"  [{WHITE}]Friday:[/]  {'Online' if self.friday else 'Offline'}")

        if self.friday:
            try:
                from core.config import Config
                self.console.print(f"  [{WHITE}]Model:[/]   {Config.PRIMARY_MODEL}")
            except Exception:
                pass
        self.divider()

    def _cmd_history_display(self):
        """Show conversation history."""
        if not self._conversation_context:
            self.print_info("No conversation history.")
            return
        self.divider()
        for msg in self._conversation_context[-20:]:
            role = msg.get("role", "?")
            text = msg.get("message", "")[:200]
            color = CYAN if role == "user" else GREEN
            self.console.print(f" [{color}]{role:<10}[/] {text}")
        self.divider()

    # ── Main loop ──

    def run(self):
        """Main terminal loop."""
        self.print_header()
        self.print_info("Type /help for commands. AI-only mode — chat naturally with Friday.\n")

        while self.running:
            try:
                user_input = self.session.prompt(
                    self._prompt_text,
                    vi_mode=False,
                )
            except (EOFError, KeyboardInterrupt):
                self.console.print()
                continue

            stripped = user_input.strip()

            if not stripped:
                continue

            self._cmd_history.append(stripped)

            # ── Internal terminal commands ──

            if stripped.startswith("/"):
                cmd = stripped.lower().split()

                if cmd[0] in ("/exit", "/quit"):
                    break

                elif cmd[0] == "/clear":
                    self.console.clear()

                elif cmd[0] == "/help":
                    self._show_help()

                elif cmd[0] == "/status":
                    self._cmd_status()

                elif cmd[0] == "/history":
                    self._cmd_history_display()

                elif cmd[0] == "/agent":
                    if len(cmd) < 2:
                        self.print_error("Usage: /agent NAME | off")
                        continue
                    if cmd[1] == "off":
                        self._active_agent = None
                        self.print_success("Agent deactivated.")
                    elif self.friday:
                        prompt = self.friday.brain.load_agent_prompt(cmd[1])
                        if prompt:
                            self._active_agent = cmd[1]
                            self.print_success(f"Agent '{cmd[1]}' activated.")
                        else:
                            self.print_error(f"Agent '{cmd[1]}' not found.")
                    else:
                        self.print_error("Friday core not available.")

                elif cmd[0] == "/newsandbox":
                    old_dir = self.sandbox_dir
                    root = os.environ.get("FRIDAY_SANDBOX")
                    if not root:
                        root = "/tmp/friday-sandbox" if os.access("/tmp", os.W_OK) else os.path.expanduser("~/.friday/sandbox")
                    self.sandbox_dir = os.path.join(root, f"session-{int(time.time())}")
                    os.makedirs(self.sandbox_dir, exist_ok=True)
                    self.cwd = self.sandbox_dir
                    os.chdir(self.cwd)
                    self.print_success(f"Sandbox reset: {old_dir} → {self.sandbox_dir}")

                else:
                    self.print_error(f"Unknown: {cmd[0]}  (try /help)")

                continue

            # ── AI-only: all non-/ input goes to Friday AI ──

            self._chat_with_friday(stripped)

        # Shutdown
        self.console.print()
        self.console.print(Panel(
            Align.center(Text.assemble(
                ("FRIDAY TERMINAL", f"bold {CYAN}"),
                (" — SESSION ENDED", DIM),
            )),
            border_style=DIM,
            box=box.ROUNDED,
            padding=(0, 2),
            width=48,
        ))
        self.console.print()


def main():
    """Entry point for the Friday Terminal."""
    import argparse

    parser = argparse.ArgumentParser(description="Friday Terminal — Hybrid Shell + AI")
    parser.add_argument("--version", "-v", action="store_true", help="Show version")
    args, _ = parser.parse_known_args()

    if args.version:
        print("Friday Terminal v2.0.0")
        return

    # Handle SIGINT gracefully
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    term = FridayTerminal()
    term.run()


if __name__ == "__main__":
    main()
