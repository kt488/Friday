"""
Audio Processing Module
=======================
Noise reduction and audio normalisation for cleaner ASR input.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from ..config import VoiceConfig
from ..logger import VoiceLogger


class AudioProcessor:
    """Applies noise reduction and level normalisation to audio segments.

    Designed as a processing stage between VAD and STT.
    """

    def __init__(self, config: VoiceConfig, log: Optional[VoiceLogger] = None):
        self.cfg = config
        self.log = log or VoiceLogger(level=config.log_level)
        self._noise_profile: Optional[np.ndarray] = None
        self._noise_samples_collected = 0
        self._noise_target_samples = int(config.sample_rate * config.noise_sample_duration)
        self._initial_noise_collection = True

    # ── Pipeline API ────────────────────────────────────────────────────

    def process(self, audio: np.ndarray, is_speech: bool = True) -> np.ndarray:
        """Run the full processing pipeline on an audio segment.

        Steps:
        1. Noise profiling (if initial and speech=False).
        2. Noise reduction (if enabled and profile exists).
        3. Level normalisation.
        """
        result = audio.copy()

        # Collect noise profile during silence
        if not is_speech and self.cfg.noise_reduce_enabled:
            self._collect_noise_profile(result)

        # Apply noise reduction
        if is_speech and self.cfg.noise_reduce_enabled and self._noise_profile is not None:
            result = self._reduce_noise(result)

        # Normalise
        result = self._normalise(result)

        return result

    def reset_noise_profile(self) -> None:
        """Clear learned noise profile."""
        self._noise_profile = None
        self._noise_samples_collected = 0
        self._initial_noise_collection = True

    # ── Noise Reduction ─────────────────────────────────────────────────

    def _collect_noise_profile(self, audio: np.ndarray) -> None:
        """Accumulate noise samples for spectral profiling."""
        if self._noise_samples_collected >= self._noise_target_samples:
            self._initial_noise_collection = False
            return

        need = self._noise_target_samples - self._noise_samples_collected
        take = min(len(audio), need)

        if self._noise_profile is None:
            self._noise_profile = audio[:take].copy()
        else:
            self._noise_profile = np.concatenate([self._noise_profile, audio[:take]])

        self._noise_samples_collected += take
        self.log.debug(f"Noise profile: {self._noise_samples_collected}/{self._noise_target_samples} samples")

    def _reduce_noise(self, audio: np.ndarray) -> np.ndarray:
        """Spectral-gating noise reduction.

        Uses a simplified spectral subtraction approach
        (works well without external deps).
        """
        if self._noise_profile is None or len(self._noise_profile) < 256:
            return audio

        noise = self._noise_profile.flatten()
        signal = audio.flatten()

        # STFT parameters
        n_fft = 512
        hop_length = 128

        # Compute noise spectrum
        noise_frames = self._stft(noise, n_fft, hop_length)
        noise_mag = np.abs(noise_frames).mean(axis=0)

        # Compute signal spectrum
        signal_frames = self._stft(signal, n_fft, hop_length)
        signal_mag = np.abs(signal_frames)
        signal_phase = np.angle(signal_frames)

        # Spectral subtraction
        strength = self.cfg.noise_reduce_strength
        mag_clean = np.maximum(0, signal_mag - strength * noise_mag[np.newaxis, :])

        # Reconstruct
        clean_frames = mag_clean * np.exp(1j * signal_phase)
        cleaned = self._istft(clean_frames, hop_length, len(signal))

        # Normalise to prevent clipping
        peak = np.max(np.abs(cleaned))
        if peak > 0:
            cleaned = cleaned / peak * 0.95

        return cleaned.reshape(-1, 1).astype(np.float32)

    # ── Normalisation ───────────────────────────────────────────────────

    @staticmethod
    def _normalise(audio: np.ndarray, target_peak: float = 0.9) -> np.ndarray:
        """Normalise peak amplitude to target level."""
        peak = np.max(np.abs(audio))
        if peak < 1e-6:
            return audio
        return (audio / peak * target_peak).astype(np.float32)

    # ── Spectral helpers ────────────────────────────────────────────────

    @staticmethod
    def _stft(signal: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
        """Simple STFT without library dependencies."""
        frames = []
        pad = n_fft // 2
        padded = np.pad(signal, (pad, pad), mode="reflect")
        window = np.hanning(n_fft)
        for start in range(0, len(padded) - n_fft + 1, hop):
            frame = padded[start:start + n_fft] * window
            frames.append(np.fft.rfft(frame))
        return np.array(frames)

    @staticmethod
    def _istft(frames: np.ndarray, hop: int, original_length: int) -> np.ndarray:
        """Inverse STFT."""
        n_fft = (frames.shape[1] - 1) * 2
        pad = n_fft // 2
        window = np.hanning(n_fft)
        signal = np.zeros(original_length + n_fft)
        overlap_count = np.zeros(original_length + n_fft)

        idx = 0
        for frame in frames:
            time = np.fft.irfft(frame) * window
            start = idx
            end = idx + n_fft
            signal[start:end] += time
            overlap_count[start:end] += window
            idx += hop

        # Normalise by overlap count
        overlap_count = np.maximum(overlap_count, 1e-10)
        signal = signal / overlap_count

        return signal[pad:pad + original_length]
