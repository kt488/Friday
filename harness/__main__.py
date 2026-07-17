"""Friday AI Runtime Harness — CLI Entry Point.

Run the harness from command line for quick testing, research queries,
and interactive execution.

Usage:
    python -m harness "your prompt here"
    python -m harness --mode research "research topic"
    python -m harness --mode coding "write a function"
    python -m harness --interactive
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from . import __version__, RuntimeHarness, HarnessConfig, ExecutionMode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Friday AI Runtime Harness — Execute AI prompts through the runtime pipeline.",
    )
    parser.add_argument("prompt", nargs="*", help="The prompt to execute")
    parser.add_argument(
        "-m", "--mode",
        choices=[m.value for m in ExecutionMode],
        default="standard",
        help="Execution mode (default: standard)",
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Run in interactive mode (REPL)",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Maximum steps per plan (overrides config)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show execution statistics after run",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"harness {__version__}",
    )
    return parser


def run_once(prompt: str, args: argparse.Namespace) -> dict:
    """Execute a single prompt and return the result."""
    config = HarnessConfig()
    harness = RuntimeHarness(config)

    mode = ExecutionMode(args.mode.lower())
    result = harness.execute(
        prompt=prompt,
        mode=mode,
        max_steps=args.max_steps,
    )

    return result


def interactive_mode(args: argparse.Namespace) -> None:
    """Run in interactive REPL mode."""
    config = HarnessConfig()
    harness = RuntimeHarness(config)

    print(f"Friday Harness v{__version__} — Interactive Mode")
    print(f"Mode: {args.mode} | Type 'quit' to exit, 'stats' for stats\n")

    while True:
        try:
            prompt = input("friday> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not prompt:
            continue
        if prompt.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break
        if prompt.lower() == "stats":
            stats = harness.get_stats()
            print(json.dumps(stats, indent=2, default=str))
            continue
        if prompt.lower() == "history":
            for entry in harness.get_history():
                print(f"  [{entry['mode']}] {entry['steps']} steps, {entry['tokens']} tokens, {entry['duration_ms']:.0f}ms")
            continue

        mode = ExecutionMode(args.mode.lower())
        result = harness.execute(
            prompt=prompt,
            mode=mode,
            max_steps=args.max_steps,
        )

        if args.json:
            out = {
                "success": result.success,
                "response": result.response,
                "steps_completed": result.steps_completed,
                "steps_total": result.steps_total,
                "total_tokens": result.total_tokens,
                "duration_ms": result.duration_ms,
                "error": result.error,
            }
            print(json.dumps(out, indent=2, default=str))
        else:
            print(f"\n{result.response}\n")
            print(f"  [{result.steps_completed}/{result.steps_total} steps | {result.total_tokens} tokens | {result.duration_ms:.0f}ms]")
            if result.error:
                print(f"  ERROR: {result.error}")
            print()


def main(argv: List[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.interactive:
        interactive_mode(args)
        return

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        parser.print_help()
        sys.exit(1)

    result = run_once(prompt, args)

    if args.json:
        out = {
            "success": result.success,
            "response": result.response,
            "steps_completed": result.steps_completed,
            "steps_total": result.steps_total,
            "total_tokens": result.total_tokens,
            "total_cost": result.total_cost,
            "duration_ms": result.duration_ms,
            "mode": result.mode.value,
            "error": result.error,
            "validation": vars(result.validation) if result.validation else None,
        }
        print(json.dumps(out, indent=2, default=str))
    else:
        print(result.response)
        if result.error:
            print(f"\nError: {result.error}", file=sys.stderr)

    if args.stats:
        stats = result.plan.metadata if result.plan and result.plan.metadata else {}
        print(f"\nExecution: {result.steps_completed}/{result.steps_total} steps | {result.total_tokens} tokens | {result.duration_ms:.0f}ms")

    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
