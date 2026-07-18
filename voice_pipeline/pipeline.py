"""
Voice Pipeline Orchestrator
============================
Main pipeline that wires together all stages:
Microphone → VAD → Noise Reduction → STT → Text Cleaning → AI → TTS → Playback

Handles barge-in, streaming, error recovery, and session management.
"""

from __future__ import annotations

import os
import signal
import sys
import time
import threading
from typing import Optional

import numpy as np

from .config import VoiceConfig
from .logger import VoiceLogger
from .audio.capture import AudioCapture, AudioCaptureError
from .audio.vad import VoiceActivityDetector, VADError
from .audio.processing import AudioProcessor
from .audio.playback import AudioPlayback, PlaybackError
from .stt.engine import SpeechToText, STTError
from .stt.cleaner import TextCleaner
from .tts.engine import TextToSpeech, TTSError
from .ai.bridge import FridayBridge, FridayBridgeError
from .conversation.manager import ConversationManager


class PipelineError(Exception):
    """Raised on unrecoverable pipeline failures."""


class VoicePipeline:
    """Orchestrates the full voice interaction pipeline.

    Stages executed in order:
    Capture → VAD → Audio Processing → STT → Text Cleaning → AI → TTS → Playback

    Pipeline states:
    - ``idle``: waiting for user speech
    - ``listening``: user speech detected, accumulating
    - ``processing``: transcribing, querying AI, synthesising
    - ``playing``: TTS audio playback active
    """

    # ── Lifecycle ───────────────────────────────────────────────────────

    def __init__(
        self,
        config: Optional[VoiceConfig] = None,
        log: Optional[VoiceLogger] = None,
    ):
        self.cfg = config or VoiceConfig.from_env()
        self.log = log or VoiceLogger(
            name="voice_pipeline",
            level=self.cfg.log_level,
            log_file=self.cfg.log_file,
            log_metrics=self.cfg.log_metrics,
        )

        # Runtime state
        self._running = False
        self._paused = False
        self._state: str = "idle"
        self._state_lock = threading.Lock()
        self._shutdown_event = threading.Event()

        # Modules (lazy initialised in _init_modules)
        self._capture: Optional[AudioCapture] = None
        self._vad: Optional[VoiceActivityDetector] = None
        self._processor: Optional[AudioProcessor] = None
        self._stt: Optional[SpeechToText] = None
        self._cleaner: Optional[TextCleaner] = None
        self._bridge: Optional[FridayBridge] = None
        self._tts: Optional[TextToSpeech] = None
        self._playback: Optional[AudioPlayback] = None
        self._conversation: Optional[ConversationManager] = None

        # Metrics
        self._total_turns = 0
        self._total_errors = 0
        self._start_time: float = 0.0

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        with self._state_lock:
            return self._state

    @state.setter
    def state(self, value: str) -> None:
        with self._state_lock:
            self._state = value

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def conversation(self) -> Optional[ConversationManager]:
        return self._conversation

    @property
    def stats(self) -> dict:
        elapsed = time.time() - self._start_time if self._start_time else 0
        return {
            "state": self.state,
            "uptime_seconds": round(elapsed, 1),
            "total_turns": self._total_turns,
            "total_errors": self._total_errors,
        }

    # ── Initialisation ──────────────────────────────────────────────────

    def _init_modules(self) -> None:
        """Create all pipeline module instances."""
        self.log.info("Initialising voice pipeline modules")

        # Audio capture
        self._capture = AudioCapture(self.cfg, self.log)

        # VAD with barge-in callback
        self._vad = VoiceActivityDetector(
            self.cfg,
            self.log,
            on_speech_start=self._on_speech_start,
            on_speech_end=self._on_speech_end,
        )

        # Audio processing
        self._processor = AudioProcessor(self.cfg, self.log)

        # STT
        self._stt = SpeechToText(self.cfg, self.log)

        # Text cleaning
        self._cleaner = TextCleaner(self.cfg, self.log)

        # Friday AI bridge
        self._bridge = FridayBridge(self.cfg, self.log)

        # TTS
        self._tts = TextToSpeech(self.cfg, self.log)

        # Playback
        self._playback = AudioPlayback(
            self.cfg,
            self.log,
            on_playback_start=self._on_playback_start,
            on_playback_end=self._on_playback_end,
        )

        # Conversation manager
        self._conversation = ConversationManager(self.cfg, self.log)

        self.log.info("All pipeline modules created")

    def _start_modules(self) -> None:
        """Start all modules that require background threads."""
        self._capture.start()
        self._vad.start()
        self._playback.start()
        self.log.info("Pipeline modules started")

    def _stop_modules(self) -> None:
        """Gracefully stop all modules."""
        self.log.info("Stopping pipeline modules")

        if self._playback:
            self._playback.stop()
        if self._capture:
            self._capture.stop()
        if self._conversation:
            self._conversation.save()

        self.log.info("Pipeline modules stopped")

    # ── VAD Callbacks ───────────────────────────────────────────────────

    def _on_speech_start(self) -> None:
        """Called by VAD when speech onset is detected.

        Triggers barge-in if currently playing back or processing.
        """
        current_state = self.state
        if current_state == "playing":
            self.log.info("Barge-in: speech detected during playback")
            self._conversation.signal_interruption()
        elif current_state == "processing":
            self.log.info("Barge-in: speech detected during processing")
            self._conversation.signal_interruption()

    def _on_speech_end(self) -> None:
        """Called by VAD when speech offset is detected."""
        pass

    # ── Playback Callbacks ──────────────────────────────────────────────

    def _on_playback_start(self) -> None:
        self.state = "playing"
        self._conversation.is_speaking = True
        self.log.info("Playback started")

    def _on_playback_end(self) -> None:
        self.state = "idle"
        self._conversation.is_speaking = False
        self.log.info("Playback ended")

    # ── Barge-in Handling ───────────────────────────────────────────────

    def _handle_barge_in(self) -> None:
        """Cancel playback and reset for new input."""
        self.log.info("Handling barge-in")

        # Cancel any ongoing playback
        if self._playback:
            self._playback.cancel()
            self._playback.clear_queue()

        # Reset VAD state so it starts fresh
        if self._vad:
            self._vad.reset()

        self.state = "idle"
        self._conversation.is_speaking = False
        self.log.info("Barge-in handled, ready for new input")

    # ── Main Processing Pipeline ────────────────────────────────────────

    def _process_segment(self, segment: np.ndarray) -> None:
        """Run a complete speech segment through the pipeline.

        Stages: audio process → STT → clean → AI → TTS → playback
        """
        self.state = "processing"

        try:
            # ── Stage 1: Audio Processing ───────────────────────────────
            with self.log.timer("audio_process"):
                processed = self._processor.process(segment, is_speech=True)
            self.log.debug(f"Audio processed: {len(processed)} samples")

            # ── Stage 2: Speech-to-Text ─────────────────────────────────
            text = ""
            with self.log.timer("stt_transcribe"):
                text = self._stt.transcribe(processed)

            if not text:
                self.log.info("STT returned empty, skipping turn")
                self.state = "idle"
                return

            # ── Stage 3: Text Cleaning ─────────────────────────────────
            with self.log.timer("text_clean"):
                cleaned = self._cleaner.clean(text)

            if not cleaned:
                self.log.info("Cleaned text empty, skipping turn")
                self.state = "idle"
                return

            self.log.info(f"User said: {cleaned}")

            # ── Stage 4: Conversation Tracking ─────────────────────────
            self._conversation.add_user_turn(cleaned)

            # Check for interruption that happened during STT
            if self._conversation.consume_interruption():
                self.log.info("Interruption during STT → discarding turn")
                self.state = "idle"
                return

            # ── Stage 5: Friday AI ─────────────────────────────────────
            self._bridge.set_context(self._conversation.get_context())

            response: Optional[str] = None
            if self.cfg.friday_stream:
                response = self._process_ai_stream(cleaned)
            else:
                response = self._get_ai_response(cleaned)

            if not response:
                self.log.info("AI returned empty response")
                self.state = "idle"
                return

            self.log.info(f"AI response: {response[:120]}...")
            self._conversation.add_assistant_turn(response)

            # Check for interruption during AI response
            if self._conversation.consume_interruption():
                self.log.info("Interruption after AI response → skipping TTS")
                self.state = "idle"
                return

            # ── Stage 6: TTS + Playback ────────────────────────────────
            if self.cfg.tts_streaming:
                self._synthesize_and_play_stream(response)
            else:
                self._synthesize_and_play_full(response)

            # ── Stage 7: Persist ───────────────────────────────────────
            self._conversation.save()
            self._total_turns += 1

        except STTError as exc:
            self._total_errors += 1
            self.log.error(f"STT failed: {exc}")
        except FridayBridgeError as exc:
            self._total_errors += 1
            self.log.error(f"AI bridge failed: {exc}")
        except TTSError as exc:
            self._total_errors += 1
            self.log.error(f"TTS failed: {exc}")
        except PlaybackError as exc:
            self._total_errors += 1
            self.log.error(f"Playback failed: {exc}")
        except Exception as exc:
            self._total_errors += 1
            self.log.exception(f"Unexpected pipeline error: {exc}")
        finally:
            if self.state == "processing":
                self.state = "idle"
            self._conversation.mark_processing_end()

    def _get_ai_response(self, text: str) -> Optional[str]:
        """Get a full (non-streaming) response from Friday AI."""
        self._conversation.mark_processing_start()
        with self.log.timer("ai_response"):
            try:
                return self._bridge.get_response(text)
            except FridayBridgeError:
                raise

    def _process_ai_stream(self, text: str) -> Optional[str]:
        """Stream response from Friday AI, accumulating full text.

        Returns the complete response, or ``None`` on failure.
        """
        self._conversation.mark_processing_start()
        chunks: list[str] = []

        with self.log.timer("ai_stream"):
            try:
                for chunk in self._bridge.get_response_stream(text):
                    if self._conversation.consume_interruption():
                        self.log.info("AI stream interrupted by barge-in")
                        break
                    chunks.append(chunk)
            except FridayBridgeError:
                raise

        if not chunks:
            return None

        return "".join(chunks).strip()

    def _synthesize_and_play_full(self, text: str) -> None:
        """Synthesise full response and enqueue for playback.

        Returns immediately — playback is handled by the background worker
        thread while the main loop continues monitoring VAD for barge-in.
        """
        with self.log.timer("tts_synthesize"):
            audio = self._tts.synthesize(text)

        if audio is None or len(audio) == 0:
            self.log.warning("TTS produced no audio")
            return

        # Resample from Kokoro native 24 kHz to config sample rate
        if self.cfg.sample_rate != 24000:
            audio = TextToSpeech.resample_to_rate(audio, 24000, self.cfg.sample_rate)

        self._playback.play(audio)
        # Don't block — main loop handles VAD monitoring for barge-in

    def _synthesize_and_play_stream(self, text: str) -> None:
        """Stream TTS audio sentence-by-sentence during playback.

        Checks for interruption between each sentence chunk.
        Returns to the main loop immediately after enqueueing.
        """
        for audio_chunk in self._tts.synthesize_stream(text):
            # Check interruption between chunks
            if self._conversation.consume_interruption():
                self.log.info("TTS stream interrupted by barge-in")
                self._playback.cancel()
                self._playback.clear_queue()
                break

            if audio_chunk is None or len(audio_chunk) == 0:
                continue

            # Resample from 24 kHz Kokoro native rate
            if self.cfg.sample_rate != 24000:
                audio_chunk = TextToSpeech.resample_to_rate(
                    audio_chunk, 24000, self.cfg.sample_rate
                )

            self._playback.play(audio_chunk)

        # Don't block — main loop handles VAD monitoring for barge-in

    # ── Main Loop ───────────────────────────────────────────────────────

    def run(self) -> None:
        """Enter the main pipeline loop.

        Blocks until ``stop()`` is called or a fatal error occurs.
        """
        if self._running:
            self.log.warning("Pipeline already running")
            return

        self._running = True
        self._start_time = time.time()
        self.state = "idle"

        # Validate config
        valid, msg = self.cfg.validate()
        if not valid:
            self.log.error(f"Invalid configuration: {msg}")
            raise PipelineError(f"Config validation failed: {msg}")

        # Initialise modules
        try:
            self._init_modules()
            self._start_modules()

            # Pre-load heavy models
            self.log.info("Pre-loading models...")
            try:
                self._stt.load_model()
            except STTError as exc:
                self.log.warning(f"STT model pre-load failed (will retry): {exc}")
            try:
                self._bridge.initialise()
            except FridayBridgeError as exc:
                self.log.warning(f"Friday AI pre-load failed (will retry): {exc}")

            self.log.info("Pipeline ready")
        except Exception as exc:
            self._running = False
            raise PipelineError(f"Pipeline initialisation failed: {exc}") from exc

        # ── Capture Loop ────────────────────────────────────────────────
        frames_since_segment = 0
        noise_collecting = True

        while self._running and not self._shutdown_event.is_set():
            try:
                # Read one audio frame
                frame = self._capture.read(block=True, timeout=0.2)
                if frame is None:
                    continue

                # Check for interruption signal (from VAD callback)
                if self._conversation.consume_interruption():
                    if self.state in ("playing", "processing"):
                        self._handle_barge_in()
                    continue

                # Feed noise samples during silence / initial
                if noise_collecting and self.state == "idle":
                    self._processor.process(frame, is_speech=False)
                    frames_since_segment += 1
                    if frames_since_segment > 100:  # ~3 seconds at 32ms frames
                        noise_collecting = False
                        self.log.info("Initial noise profile collected")

                # Feed frame to VAD for speech detection
                segment = self._vad.process_frame(frame)

                if segment is not None:
                    # Complete speech segment received
                    noise_collecting = False
                    frames_since_segment = 0

                    self.log.info(
                        f"Speech segment: {len(segment)/self.cfg.sample_rate:.1f}s, "
                        f"{len(segment)} samples"
                    )
                    self._process_segment(segment)

            except AudioCaptureError as exc:
                self._total_errors += 1
                self.log.error(f"Capture error: {exc}")
                # Try to re-initialise capture
                self._reinit_module("capture")
            except Exception as exc:
                self._total_errors += 1
                self.log.exception(f"Pipeline loop error: {exc}")
                time.sleep(0.5)

        # ── Shutdown ────────────────────────────────────────────────────
        self._stop_modules()
        self.log.info(
            f"Pipeline finished: {self._total_turns} turns, "
            f"{self._total_errors} errors"
        )

    def stop(self) -> None:
        """Signal the pipeline to stop."""
        self._running = False
        self._shutdown_event.set()
        self.log.info("Pipeline stop signalled")

    # ── Module Re-initialisation ────────────────────────────────────────

    def _reinit_module(self, module: str) -> None:
        """Attempt to re-create and restart a failed module."""
        self.log.info(f"Re-initialising module: {module}")
        try:
            if module == "capture":
                self._capture = AudioCapture(self.cfg, self.log)
                self._capture.start()
            elif module == "playback":
                self._playback = AudioPlayback(
                    self.cfg,
                    self.log,
                    on_playback_start=self._on_playback_start,
                    on_playback_end=self._on_playback_end,
                )
                self._playback.start()
            elif module == "vad":
                self._vad = VoiceActivityDetector(
                    self.cfg,
                    self.log,
                    on_speech_start=self._on_speech_start,
                    on_speech_end=self._on_speech_end,
                )
                self._vad.start()
            self.log.info(f"Module '{module}' re-initialised")
        except Exception as exc:
            self.log.error(f"Failed to re-initialise '{module}': {exc}")

    # ── Session Management ──────────────────────────────────────────────

    def load_session(self, session_id: str) -> bool:
        """Load a previous conversation session."""
        if self._conversation is None:
            return False
        return self._conversation.load(session_id)

    def reset_session(self) -> None:
        """Reset conversation state."""
        if self._conversation:
            self._conversation.reset_session()
        self._total_turns = 0
        self._total_errors = 0
        self.log.info("Session reset")

    def list_sessions(self) -> list[dict]:
        """List all saved conversation sessions."""
        if self._conversation is None:
            return []
        return self._conversation.list_sessions()

    # ── Context Manager ─────────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stop()
