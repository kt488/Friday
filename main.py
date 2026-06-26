#!/usr/bin/env python3
"""Friday AI Assistant — CLI entry point with subcommands.

Usage:
  friday chat              Start interactive session
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
    """Interactive chat session with streaming and in-chat commands."""
    from interface.cli import FridayCLI

    friday = FridayCore()
    cli = FridayCLI(version=VERSION)

    # Track message count for the status display
    msg_count = 0
    try:
        history = friday.db.get_conversation_history(limit=10000)
        msg_count = len(history)
    except Exception:
        pass

    while True:
        user_input = cli.get_input()

        # ── In-chat commands ──
        if user_input.startswith("/"):
            cmd = user_input.lower().split()

            if cmd[0] in ("/exit", "/quit"):
                cli.info("Goodbye!")
                break

            elif cmd[0] == "/clear":
                friday.clear_history()
                msg_count = 0
                cli.info("History cleared.")

            elif cmd[0] == "/status":
                cli.divider()
                cli.panel("model", Config.PRIMARY_MODEL, "cyan")
                if friday._active_agent:
                    cli.panel("agent", friday._active_agent, "green")
                cli.panel("messages", str(msg_count), "white")

            elif cmd[0] == "/agent":
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
                        cli.info(f"Agent '{name}' activated ({len(prompt)} chars).")
                    else:
                        cli.error(f"Agent '{name}' not found.")

            elif cmd[0] == "/help":
                cli.show_help()

            else:
                cli.error(f"Unknown command: {cmd[0]}  (try /help)")

            continue

        # ── Empty input ──
        if not user_input:
            continue

        # ── Normal message ──
        msg_count += 1
        cli.thinking()

        try:
            for _ in cli.stream_response(
                friday.process_message_stream(user_input)
            ):
                pass
        except Exception as e:
            cli.error(str(e))

        # Show a lightweight status line after each response
        agent = friday._active_agent
        cli.divider()


# ── Ask ──

def cmd_ask(args):
    """One-shot question, print response."""
    friday = FridayCore()
    text = " ".join(args.text)
    response, metadata = friday.process_message(text)
    if response:
        from interface.cli import FridayCLI
        cli = FridayCLI(version=VERSION)
        cli.markdown(response)


# ── API ──

def cmd_api(args):
    """Start the REST API server."""
    os.environ.setdefault("FRIDAY_HOST", args.host)
    os.environ.setdefault("FRIDAY_PORT", str(args.port))
    from interface.api import app

    ssl_ctx = None
    if args.cert:
        ssl_ctx = (args.cert, args.key) if args.key else args.cert

    proto = "https" if ssl_ctx else "http"
    print(f"[*] Friday API starting on {proto}://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, ssl_context=ssl_ctx)


# ── Bot ──

def cmd_bot(args):
    """Start the Telegram bot."""
    import subprocess
    ret = subprocess.call([sys.executable, "-m", "interface.telegram_bot"])
    sys.exit(ret)


# ── History ──

def cmd_history(args):
    """View or clear conversation history."""
    friday = FridayCore()

    if args.clear:
        friday.clear_history()
        print("[*] Conversation history cleared.")
        return

    rows = friday.db.get_conversation_history(limit=args.limit)
    if not rows:
        print("[*] No conversation history.")
        return

    print(f"[*] Recent history (last {len(rows)}):\n")
    for role, message, ts in rows:
        prefix = "You" if role == "user" else "Friday"
        label = f"[{ts}] {prefix}:"
        preview = message[:100].replace("\n", " ")
        if len(message) > 100:
            preview += "..."
        print(f"  {label} {preview}")
    print()


# ── Agents ──

def cmd_agents(args):
    """Manage agent personalities."""
    friday = FridayCore()

    if args.action == "list":
        agents = friday.brain.list_agents()
        if not agents:
            print("[*] No agent files found.")
            return
        active = friday._active_agent
        print(f"[*] Available agents ({len(agents)}):")
        for a in agents:
            marker = " *" if a["name"] == active else ""
            print(f"  - {a['name']}{marker}")
        if active:
            print(f"\n  Active: {active}")
        else:
            print("\n  No agent currently active.")

    elif args.action == "load":
        if not args.name:
            print("[!] Agent name required. Usage: friday agents load <name>")
            sys.exit(1)
        prompt = friday.brain.load_agent_prompt(args.name)
        if prompt:
            friday._active_agent = args.name
            print(f"[*] Agent '{args.name}' activated ({len(prompt)} chars).")
        else:
            print(f"[!] Agent '{args.name}' not found.")
            sys.exit(1)

    elif args.action == "clear":
        friday._active_agent = None
        print("[*] Agent deactivated.")


# ── System ──

def cmd_system(args):
    """Show system information and status."""
    friday = FridayCore()
    valid, msg = Config.validate()

    print(f"  Name:      {Config.APP_NAME}")
    print(f"  Version:   {VERSION}")
    print(f"  Model:     {Config.PRIMARY_MODEL}")
    print(f"  Vision:    {Config.VISION_MODEL}")
    print(f"  Agent:     {friday._active_agent or '(none)'}")
    print(f"  Config:    {'OK' if valid else msg}")
    print(f"  Supabase:  {'connected' if friday.executive.supabase.enabled else 'disabled'}")

    mcp_count = len(getattr(friday.executive.mcp, "clients", []))
    print(f"  MCP:       {mcp_count} server(s)")

    try:
        rows = friday.db.get_conversation_history(limit=10000)
        print(f"  Messages:  {len(rows)} in history")
    except Exception:
        pass
    print()


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
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
