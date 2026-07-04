#!/usr/bin/env python3
"""
CLI administration tool for Friday SaaS.

Usage::

    python interface/cli_admin.py setup
    python interface/cli_admin.py gen-key [--label "My Key"]
"""

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.saas import SaaSService


def cmd_setup(args):
    """Set or update the admin password."""
    saas = SaaSService()

    password = getpass.getpass("Enter admin password: ")
    if len(password) < 8:
        print("Error: Password must be at least 8 characters")
        sys.exit(1)

    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Error: Passwords do not match")
        sys.exit(1)

    pw_hash = saas.auth.hash_password(password)
    existing = saas.db.get_user_by_email("admin@friday.local")

    if existing and existing.get("password_hash"):
        saas.db.update_user(existing["id"], password_hash=pw_hash)
        print("Admin password updated.")
    elif existing:
        saas.db.update_user(existing["id"], password_hash=pw_hash, role="admin")
        print("Admin password set.")
    else:
        user_id = saas.db.create_user("admin@friday.local", pw_hash, "Admin")
        saas.db.update_user(user_id, role="admin")
        print(f"Admin user created (ID: {user_id}) with password set.")


def cmd_gen_key(args):
    """Generate a universal API key after admin password verification."""
    saas = SaaSService()

    password = getpass.getpass("Enter admin password: ")

    user = saas.db.get_user_by_email("admin@friday.local")
    if not user:
        print("Error: Admin user not found. Run 'setup' first.")
        sys.exit(1)
    if user.get("role") != "admin":
        print("Error: User is not an admin.")
        sys.exit(1)
    if not saas.auth.verify_password(password, user["password_hash"]):
        print("Error: Invalid password")
        sys.exit(1)

    label = args.label or "CLI-generated"
    full_key, display = saas.keys.generate_key(user["id"], label=label)

    print("\n" + "=" * 60)
    print("  NEW UNIVERSAL API KEY")
    print("  " + "=" * 50)
    print(f"\n  {full_key}\n")
    print("  Save this key now \u2014 it will not be shown again.")
    print("=" * 60)
    print(f"\n  Label:  {display['label']}")
    print(f"  ID:     {display['id']}")
    print(f"  Prefix: {display['key_prefix']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Friday Admin CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("setup", help="Set or update admin password")

    genkey_parser = subparsers.add_parser("gen-key", help="Generate a universal API key")
    genkey_parser.add_argument("--label", help="Label for the API key")

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup(args)
    elif args.command == "gen-key":
        cmd_gen_key(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
