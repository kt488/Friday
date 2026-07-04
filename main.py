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
    cli.system("Booting API server...")
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


# ── Keys ──

def cmd_keys(args):
    """Manage API keys."""
    from core.saas import SaaSService
    saas = SaaSService()

    if args.action == "create":
        full_key, display = saas.keys.generate_key(
            user_id=args.user_id,
            label=args.label or "Default",
        )
        print("Generated API Key:")
        print(f"  Full Key: {full_key}")
        print(f"  ID:       {display['id']}")
        print(f"  Prefix:   {display['key_prefix']}")
        print(f"  Label:    {display['label']}")
        print()
        print("IMPORTANT: Save this key now. It will not be shown again.")

    elif args.action == "list":
        keys = saas.keys.list_keys(args.user_id)
        if not keys:
            print(f"No API keys found for user {args.user_id}.")
            return
        print(f"API Keys for user {args.user_id}:")
        print(f"{'ID':<5} {'Prefix':<30} {'Label':<20} {'Revoked':<10}")
        print("-" * 65)
        for k in keys:
            revoked = "Yes" if k["is_revoked"] else "No"
            print(f"{k['id']:<5} {k['key_prefix']:<30} {k['label']:<20} {revoked:<10}")

    elif args.action == "revoke":
        saas.keys.revoke_key(args.key_id)
        print(f"API key {args.key_id} revoked.")

    elif args.action == "user-list":
        users = saas.db.list_users()
        print("Users:")
        print(f"{'ID':<5} {'Email':<30} {'Name':<20} {'Role':<10}")
        print("-" * 65)
        for u in users:
            print(f"{u['id']:<5} {u['email']:<30} {u['name']:<20} {u['role']:<10}")


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

    # ── keys ──
    p_keys = subparsers.add_parser("keys", help="Manage API keys")
    p_keys_sub = p_keys.add_subparsers(dest="action", required=True)

    p_keys_create = p_keys_sub.add_parser("create", help="Create a new API key")
    p_keys_create.add_argument("--user-id", type=int, default=1, help="User ID (default: 1)")
    p_keys_create.add_argument("--label", default="CLI Key", help="Label for the key")
    p_keys_create.set_defaults(func=cmd_keys)

    p_keys_list = p_keys_sub.add_parser("list", help="List API keys for a user")
    p_keys_list.add_argument("--user-id", type=int, default=1, help="User ID (default: 1)")
    p_keys_list.set_defaults(func=cmd_keys)

    p_keys_revoke = p_keys_sub.add_parser("revoke", help="Revoke an API key")
    p_keys_revoke.add_argument("key_id", type=int, help="Key ID to revoke")
    p_keys_revoke.set_defaults(func=cmd_keys)

    p_keys_users = p_keys_sub.add_parser("user-list", help="List all registered users")
    p_keys_users.set_defaults(func=cmd_keys)

    args = parser.parse_args()

    if args.command is None:
        cmd_chat(args)
        return

    args.func(args)


if __name__ == "__main__":
    main()
