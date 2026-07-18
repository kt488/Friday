"""
Voice Pipeline CLI
==================
Command-line entry point with argument parsing, session management,
signal handling, and multiple run modes.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from typing import Optional


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="friday-voice",
        description="Friday AI Voice Pipeline — microphone-to-speech interaction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  friday-voice                          # Start interactive session\n"
            "  friday-voice --list-sessions           # Show all saved sessions\n"
            "  friday-voice --load-session <id>       # Resume previous session\n"
            "  friday-voice --mode oneshot            # Single turn, then exit\n"
            "  friday-voice --reset-session           # Clear history before starting\n"
        ),
    )

    # Session
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List all saved conversation sessions and exit",
    )
    parser.add_argument(
        "--load-session",
        type=str,
        default="",
        metavar="ID",
        help="Load a specific conversation session",
    )
    parser.add_argument(
        "--reset-session",
        action="store_true",
        help="Reset conversation history before starting",
    )

    # Mode
    parser.add_argument(
        "--mode",
        type=str,
        default="interactive",
        choices=["interactive", "oneshot"],
        help="Run mode: 'interactive' (continuous) or 'oneshot' (single turn)",
    )

    # Config overrides
    parser.add_argument("--sample-rate", type=int, default=0, help="Override sample rate")
    parser.add_argument("--model-size", type=str, default="", help="Whisper model size")
    parser.add_argument("--tts-voice", type=str, default="", help="TTS voice profile")
    parser.add_argument("--device", type=str, default="", help="Whisper device (cpu/cuda)")
    parser.add_argument("--log-level", type=str, default="", help="Log level (DEBUG/INFO/WARNING)")
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming (both AI and TTS)",
    )

    # Health
    parser.add_argument(
        "--health",
        action="store_true",
        help="Run a health check and exit",
    )

    return parser


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args


def apply_args_to_config(args: argparse.Namespace) -> None:
    """Apply CLI argument overrides to environment variables (read by VoiceConfig)."""
    overrides = {
        "VOICE_SAMPLE_RATE": args.sample_rate if args.sample_rate > 0 else None,
        "WHISPER_MODEL_SIZE": args.model_size or None,
        "TTS_VOICE": args.tts_voice or None,
        "WHISPER_DEVICE": args.device or None,
        "VOICE_LOG_LEVEL": args.log_level or None,
    }
    if args.no_stream:
        overrides["FRIDAY_STREAM"] = "false"
        overrides["TTS_STREAMING"] = "false"

    for key, value in overrides.items():
        if value is not None:
            os.environ[key] = str(value)


def run_health_check(config) -> dict:
    """Run a health check on all pipeline modules."""
    from .logger import VoiceLogger
    from .audio.capture import AudioCapture
    from .audio.vad import VoiceActivityDetector
    from .audio.processing import AudioProcessor
    from .stt.engine import SpeechToText
    from .stt.cleaner import TextCleaner
    from .tts.engine import TextToSpeech
    from .ai.bridge import FridayBridge
    from .conversation.manager import ConversationManager

    results = {}
    log = VoiceLogger(name="health", level="INFO")

    # Audio Capture
    try:
        cap = AudioCapture(config, log)
        cap.start()
        cap.stop()
        results["capture"] = {"status": "OK"}
    except Exception as e:
        results["capture"] = {"status": "FAIL", "error": str(e)}

    # VAD
    try:
        vad = VoiceActivityDetector(config, log)
        vad.start()
        results["vad"] = {"status": "OK", "backend": vad._backend}
    except Exception as e:
        results["vad"] = {"status": "FAIL", "error": str(e)}

    # Audio Processor
    try:
        ap = AudioProcessor(config, log)
        results["audio_processor"] = {"status": "OK"}
    except Exception as e:
        results["audio_processor"] = {"status": "FAIL", "error": str(e)}

    # STT
    try:
        stt = SpeechToText(config, log)
        stt.load_model()
        results["stt"] = {"status": "OK", "model": config.whisper_model_size}
    except Exception as e:
        results["stt"] = {"status": "FAIL", "error": str(e)}

    # Text Cleaner
    try:
        tc = TextCleaner(config, log)
        results["text_cleaner"] = {"status": "OK"}
    except Exception as e:
        results["text_cleaner"] = {"status": "FAIL", "error": str(e)}

    # TTS
    try:
        tts = TextToSpeech(config, log)
        tts.load_model()
        results["tts"] = {"status": "OK", "voice": config.tts_voice}
    except Exception as e:
        results["tts"] = {"status": "FAIL", "error": str(e)}

    # Friday Bridge
    try:
        bridge = FridayBridge(config, log)
        bridge.initialise()
        health = bridge.health_check()
        results["friday_bridge"] = {
            "status": "OK" if health.get("available") else "WARN",
            "latency_ms": health.get("latency_ms"),
        }
    except Exception as e:
        results["friday_bridge"] = {"status": "FAIL", "error": str(e)}

    # Conversation Manager
    try:
        cm = ConversationManager(config, log)
        results["conversation"] = {"status": "OK"}
    except Exception as e:
        results["conversation"] = {"status": "FAIL", "error": str(e)}

    return results


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    apply_args_to_config(args)

    from .config import VoiceConfig
    from .logger import VoiceLogger

    config = VoiceConfig.from_env()
    valid, msg = config.validate()
    if not valid:
        print(f"Configuration error: {msg}", file=sys.stderr)
        return 1

    log = VoiceLogger(
        name="voice_pipeline",
        level=config.log_level,
        log_file=config.log_file,
        log_metrics=config.log_metrics,
    )

    # ── List sessions ───────────────────────────────────────────────────
    if args.list_sessions:
        from .conversation.manager import ConversationManager

        cm = ConversationManager(config, log)
        sessions = cm.list_sessions()
        if not sessions:
            print("No saved sessions found.")
            return 0

        print(f"{'Session ID':<40} {'Created':<22} {'Turns':<8}")
        print("-" * 70)
        for s in sessions:
            print(f"{s['session_id']:<40} {s.get('created_at', '?'):<22} {s['turn_count']:<8}")
        return 0

    # ── Health check ────────────────────────────────────────────────────
    if args.health:
        results = run_health_check(config)
        print(f"\n{'Module':<25} Status")
        print("-" * 40)
        all_ok = True
        for name, result in results.items():
            status = result.get("status", "?")
            icon = "OK" if status == "OK" else "!"
            print(f"  {name:<25} [{icon}] {status}", end="")
            if "error" in result:
                print(f"  ({result['error']})", end="")
                all_ok = False
            if "backend" in result:
                print(f"  backend={result['backend']}", end="")
            if "model" in result:
                print(f"  model={result['model']}", end="")
            if "latency_ms" in result:
                print(f"  latency={result['latency_ms']}ms", end="")
            print()
        print(f"\nOverall: {'ALL OK' if all_ok else 'SOME CHECKS FAILED'}")
        return 0 if all_ok else 1

    # ── Run Pipeline ────────────────────────────────────────────────────
    from .pipeline import VoicePipeline

    pipeline = VoicePipeline(config=config, log=log)

    # Session management
    if args.reset_session:
        pipeline.reset_session()

    if args.load_session:
        loaded = pipeline.load_session(args.load_session)
        if loaded:
            log.info(f"Loaded session: {args.load_session}")
        else:
            log.warning(f"Session not found: {args.load_session}, starting fresh")

    # Signal handlers
    shutdown_requested = False

    def _handle_signal(signum, frame):
        nonlocal shutdown_requested
        if shutdown_requested:
            log.warning("Forced exit")
            sys.exit(1)
        shutdown_requested = True
        log.info(f"Signal {signum} received, shutting down...")
        pipeline.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Run
    try:
        if args.mode == "oneshot":
            # Single-turn mode: run until one segment is processed
            log.info("Oneshot mode: waiting for one voice input")
            pipeline._total_turns = 0

            # Monkey-patch _process_segment to stop after one turn
            _original_process = pipeline._process_segment

            def _oneshot_process(segment):
                _original_process(segment)
                pipeline.stop()

            pipeline._process_segment = _oneshot_process
            pipeline.run()
        else:
            # Interactive mode: continuous conversation
            log.info("Interactive mode: listening continuously (Ctrl+C to stop)")
            pipeline.run()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as exc:
        log.exception(f"Pipeline error: {exc}")
        return 1
    finally:
        pipeline.stop()
        log.info("Pipeline shutdown complete")

    return 0


if __name__ == "__main__":
    sys.exit(main())
