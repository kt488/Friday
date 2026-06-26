#!/usr/bin/env python3
"""Friday AI Assistant — CLI entry point.

Usage:
  friday                   Start interactive session (default)
  friday ask 'message'     One-shot question
  friday api               Start REST API
  friday bot               Start Telegram bot
  friday history           View conversation history
  friday agents list       List available agents
  friday system            Show system status
"""

import argparse
import os
import sys

from core.friday import FridayCore
from core.config import Config

VERSION = "2.0.0"


# ── Chat ──

def cmd_chat(args):
    """Interactive chat with modern robotic interface."""
    from interface.cli import FridayCLI

    friday = FridayCore()
    cli = FridayCLI(version=VERSION)
    cli.header()

    # Count existing messages
    try:
        rows = friday.db.get_conversation_history(limit=10000)
        cli.msg_count = len(rows)
    except Exception:
        pass

    while True:
        user_input = cli.get_input()

        # ── In-chat commands ──
        if user_input.startswith("/"):
            cmd = user_input.lower().split()
            tag = cmd[0]

            if tag in ("/exit", "/quit"):
                break

            elif tag == "/clear":
                friday.clear_history()
                cli.msg_count = 0
                cli.info("Conversation cleared.")

            elif tag == "/status":
                cli.status_bar(
                    cpu=42,
                    memory=56,
                    network="ONLINE" if friday.executive.supabase.enabled else "DISABLED",
                    agent=friday._active_agent or "STANDBY",
                )

            elif tag == "/agent":
                if len(cmd) < 2:
                    cli.error("Usage: /agent NAME  (use /agent off to disable)")
                    continue
                name = cmd[1]
                if name == "off":
                    friday._active_agent = None
                    cli.info("Agent deactivated.")
                else:
                    prompt = friday.brain.load_agent_prompt(name)
                    if prompt:
                        friday._active_agent = name
                        cli.success(f"Agent '{name}' activated.")
                    else:
                        cli.error(f"Agent '{name}' not found.")

            elif tag == "/help":
                cli.show_help()

            else:
                cli.error(f"Unknown: {cmd[0]}  (try /help)")

            continue

        # ── User shell command (e.g. !ls -la) ──
        if user_input.startswith("!"):
            import subprocess
            command = user_input[1:]
            cli.msg_count += 1
            try:
                result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
                )
                output = result.stdout + result.stderr
                cli.shell_output(command, output, result.returncode)
            except subprocess.TimeoutExpired:
                cli.error("Command timed out (30s limit).")
            except Exception as e:
                cli.error(str(e))
            continue

        # ── Empty input ──
        if not user_input:
            continue

        # ── Normal message ──
        cli.msg_count += 1
        cli.user_message(user_input)

        try:
            for _ in cli.stream_response(
                friday.process_message_stream(user_input)
            ):
                pass
        except Exception as e:
            cli.error(str(e))

    cli.shutdown()


# ── Ask ──

def cmd_ask(args):
    """One-shot question, print response."""
    from interface.cli import FridayCLI
    cli = FridayCLI(version=VERSION)
    friday = FridayCore()

    text = " ".join(args.text)
    cli.system("Processing request...")

    try:
        response, metadata = friday.process_message(text)
        if response:
            cli.response(response)
    except Exception as e:
        cli.error(str(e))


# ── API ──

def cmd_api(args):
    """Start the REST API server."""
    from interface.cli import FridayCLI
    cli = FridayCLI(version=VERSION)

    os.environ.setdefault("FRIDAY_HOST", args.host)
    os.environ.setdefault("FRIDAY_PORT", str(args.port))
    from interface.api import app

    ssl_ctx = None
    if args.cert:
        ssl_ctx = (args.cert, args.key) if args.key else args.cert

    proto = "https" if ssl_ctx else "http"
    cli.system(f"Starting API server on {proto}://{args.host}:{args.port}")
    cli.info(f"Debug: {'ON' if args.debug else 'OFF'}")
    cli.info(f"SSL: {'Enabled' if ssl_ctx else 'Disabled'}")
    cli.loading(steps=5, label="BOOTING")
    cli.success("API server is running.")
    app.run(host=args.host, port=args.port, debug=args.debug, ssl_context=ssl_ctx)


# ── Bot ──

def cmd_bot(args):
    """Start the Telegram bot."""
    from interface.cli import FridayCLI
    cli = FridayCLI(version=VERSION)
    import subprocess

    cli.system("Starting Telegram bot...")
    cli.loading(steps=4, label="CONNECTING")
    cli.success("Bot process launched.")
    ret = subprocess.call([sys.executable, "-m", "interface.telegram_bot"])
    sys.exit(ret)


# ── History ──

def cmd_history(args):
    """View or clear conversation history."""
    from interface.cli import FridayCLI
    cli = FridayCLI(version=VERSION)
    friday = FridayCore()

    if args.clear:
        friday.clear_history()
        cli.success("Conversation history cleared.")
        return

    rows = friday.db.get_conversation_history(limit=args.limit)
    if not rows:
        cli.info("No conversation history.")
        return

    cli.system(f"Recent history (last {len(rows)}):")
    cli.divider()
    for role, message, ts in rows:
        prefix = "YOU" if role == "user" else "FRIDAY"
        preview = message[:120].replace("\n", " ")
        if len(message) > 120:
            preview += "..."
        cli.raw(f"  [{ts}] [{prefix:<7}] {preview}")
    cli.divider()


# ── Agents ──

def cmd_agents(args):
    """Manage agent personalities."""
    from interface.cli import FridayCLI
    cli = FridayCLI(version=VERSION)
    friday = FridayCore()

    if args.action == "list":
        agents = friday.brain.list_agents()
        if not agents:
            cli.info("No agent files found.")
            return
        active = friday._active_agent
        cli.system(f"Available agents ({len(agents)}):")
        cli.divider()
        for a in agents:
            marker = " ◄ ACTIVE" if a["name"] == active else ""
            cli.raw(f"  {a['name']}{marker}")
        cli.divider()
        if active:
            cli.info(f"Active agent: {active}")
        else:
            cli.info("No agent currently active.")

    elif args.action == "load":
        if not args.name:
            cli.error("Agent name required. Usage: friday agents load <name>")
            sys.exit(1)
        prompt = friday.brain.load_agent_prompt(args.name)
        if prompt:
            friday._active_agent = args.name
            cli.success(f"Agent '{args.name}' activated ({len(prompt)} chars).")
        else:
            cli.error(f"Agent '{args.name}' not found.")
            sys.exit(1)

    elif args.action == "clear":
        friday._active_agent = None
        cli.info("Agent deactivated.")


# ── System ──

def cmd_system(args):
    """Show system information and status."""
    from interface.cli import FridayCLI
    cli = FridayCLI(version=VERSION)
    friday = FridayCore()
    valid, msg = Config.validate()

    cli.system("System Status Report")
    cli.divider()
    cli.raw(f"  Name:      {Config.APP_NAME}")
    cli.raw(f"  Version:   {VERSION}")
    cli.raw(f"  Model:     {Config.PRIMARY_MODEL}")
    cli.raw(f"  Vision:    {Config.VISION_MODEL}")
    cli.raw(f"  Agent:     {friday._active_agent or '(none)'}")
    cli.raw(f"  Config:    {'OK' if valid else msg}")
    cli.raw(f"  Supabase:  {'connected' if friday.executive.supabase.enabled else 'disabled'}")
    mcp_count = len(getattr(friday.executive.mcp, "clients", []))
    cli.raw(f"  MCP:       {mcp_count} server(s)")
    try:
        rows = friday.db.get_conversation_history(limit=10000)
        cli.raw(f"  Messages:  {len(rows)} in history")
    except Exception:
        pass
    cli.divider()
    cli.status_bar(
        cpu=42,
        memory=56,
        network="ONLINE" if friday.executive.supabase.enabled else "DISABLED",
        agent=friday._active_agent or "STANDBY",
    )


# ── Main CLI parser ──

def main():
    parser = argparse.ArgumentParser(
        prog="friday",
        description="Friday AI Assistant — CLI interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  friday chat              Start interactive session\n"
            "  friday ask 'Hello'       One-shot question\n"
            "  friday api               Start REST API\n"
            "  friday bot               Start Telegram bot\n"
            "  friday history           View conversation history\n"
            "  friday agents list       List available agents\n"
            "  friday agents load auto  Activate auto-agent\n"
            "  friday system            Show system status\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── chat ──
    p_chat = subparsers.add_parser("chat", help="Start interactive chat session")
    p_chat.set_defaults(func=cmd_chat)

    # ── ask ──
    p_ask = subparsers.add_parser("ask", help="Ask a one-shot question")
    p_ask.add_argument("text", nargs="+", help="Your question or message")
    p_ask.set_defaults(func=cmd_ask)

    # ── api ──
    p_api = subparsers.add_parser("api", help="Start the REST API server")
    p_api.add_argument("--host", default=os.environ.get("FRIDAY_HOST", "0.0.0.0"), help="Host to bind")
    p_api.add_argument("--port", type=int, default=int(os.environ.get("FRIDAY_PORT", "5000")), help="Port to bind")
    p_api.add_argument("--debug", action="store_true", default=os.environ.get("FRIDAY_DEBUG", "").lower() == "true", help="Enable debug mode")
    p_api.add_argument("--cert", default=os.environ.get("FRIDAY_SSL_CERT"), help="SSL certificate path")
    p_api.add_argument("--key", default=os.environ.get("FRIDAY_SSL_KEY"), help="SSL private key path")
    p_api.set_defaults(func=cmd_api)

    # ── bot ──
    p_bot = subparsers.add_parser("bot", help="Start the Telegram bot")
    p_bot.set_defaults(func=cmd_bot)

    # ── history ──
    p_history = subparsers.add_parser("history", help="View or clear conversation history")
    p_history.add_argument("--clear", action="store_true", help="Clear all history")
    p_history.add_argument("--limit", type=int, default=20, help="Number of entries to show (default 20)")
    p_history.set_defaults(func=cmd_history)

    # ── agents ──
    p_agents = subparsers.add_parser("agents", help="Manage agent personalities")
    p_agents.add_argument("action", choices=["list", "load", "clear"], help="Action to perform")
    p_agents.add_argument("name", nargs="?", help="Agent name (required for 'load')")
    p_agents.set_defaults(func=cmd_agents)

    # ── system ──
    p_system = subparsers.add_parser("system", help="Show system information and status")
    p_system.set_defaults(func=cmd_system)

    args = parser.parse_args()

    if args.command is None:
        cmd_chat(args)
        return

    args.func(args)


if __name__ == "__main__":
    main()
