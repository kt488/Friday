"""
Text Cleaning Module
====================
Post-processes ASR output to produce clean, well-formatted text for the AI.
"""

from __future__ import annotations

import re
from typing import Optional

from ..config import VoiceConfig
from ..logger import VoiceLogger


class TextCleaner:
    """Cleans and normalises ASR transcription text.

    Operations (each can be individually disabled):
    - Fill word removal (um, uh, like, you know, etc.)
    - Disfluency repair removal
    - Punctuation normalisation
    - Capitalisation restoration
    - Number/date normalisation (optional)
    """

    # ── Filler words ────────────────────────────────────────────────────

    FILLER_WORDS = re.compile(
        r"\b(?:"
        r"um|uh|uhh|umm|er|ah|hmm|mm-hmm|uh-huh|"
        r"like|you know|i mean|well|actually|basically|"
        r"literally|honestly|sort of|kind of|you see|"
        r"i guess|i suppose|right|okay so|so yeah|"
        r"yeah no|no no|wait|hold on|let me see"
        r")\b[,\s]*",
        re.IGNORECASE,
    )

    # ── Disfluencies ────────────────────────────────────────────────────

    # Repeated words: "I I went to the the store"
    REPEATED_WORDS = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)

    # False starts: "I wanted to — I went to the store"
    FALSE_START = re.compile(
        r"\b\w+\s+\w+\s+\w+\s*—\s*", re.IGNORECASE
    )

    # Incomplete trailing words: "I went to the sto—"
    TRAILING_HYPHEN = re.compile(r"\w+—\s*")

    # ── Punctuation ─────────────────────────────────────────────────────

    MULTI_SPACE = re.compile(r"\s{2,}")
    MULTI_PERIOD = re.compile(r"\.{2,}")
    SPACE_BEFORE_PUNCT = re.compile(r'\s+([.,!?;:])')
    MISSING_SPACE_AFTER_PUNCT = re.compile(r'([.,!?;:])([A-Za-z])')

    # ── Contractions ────────────────────────────────────────────────────

    CONTRACTIONS = {
        "im": "I'm", "ive": "I've", "ill": "I'll", "id": "I'd",
        "dont": "don't", "cant": "can't", "wont": "won't",
        "isnt": "isn't", "arent": "aren't", "wasnt": "wasn't",
        "werent": "weren't", "hasnt": "hasn't", "havent": "haven't",
        "hadnt": "hadn't", "doesnt": "doesn't", "didnt": "didn't",
        "couldnt": "couldn't", "wouldnt": "wouldn't", "shouldnt": "shouldn't",
        "mightnt": "mightn't", "mustnt": "mustn't",
        "its": "it's", "thats": "that's", "whats": "what's",
        "theres": "there's", "heres": "here's", "wheres": "where's",
        "whos": "who's", "hows": "how's", "lets": "let's",
        "youd": "you'd", "youll": "you'll", "youve": "you've",
        "theyre": "they're", "theyd": "they'd", "theyll": "they'll",
        "weve": "we've", "werell": "we'll", "wed": "we'd",
        "shes": "she's", "hed": "he'd", "hell": "he'll",
    }

    def __init__(self, config: VoiceConfig, log: Optional[VoiceLogger] = None):
        self.cfg = config
        self.log = log or VoiceLogger(level=config.log_level)

    # ── Main API ────────────────────────────────────────────────────────

    def clean(self, text: str) -> str:
        """Run all enabled cleaning passes on transcribed text."""
        if not text:
            return ""

        original = text
        result = text

        # 1. Remove filler words
        if self.cfg.clean_filler_words:
            result = self._remove_fillers(result)

        # 2. Remove disfluencies
        if self.cfg.clean_disfluencies:
            result = self._remove_disfluencies(result)

        # 3. Fix punctuation
        if self.cfg.fix_punctuation:
            result = self._fix_punctuation(result)

        # 4. Normalise numbers
        if self.cfg.normalize_numbers:
            result = self._normalize_numbers(result)

        # 5. Capitalise
        if self.cfg.capitalize:
            result = self._capitalize(result)

        # 6. Final whitespace cleanup
        result = result.strip()
        result = self.MULTI_SPACE.sub(" ", result)

        if result != original:
            self.log.debug(f"Cleaned text ({len(original)} → {len(result)} chars): '{result[:120]}'")

        return result

    # ── Processing passes ───────────────────────────────────────────────

    def _remove_fillers(self, text: str) -> str:
        return self.FILLER_WORDS.sub("", text)

    def _remove_disfluencies(self, text: str) -> str:
        result = text
        # Remove repeated words (multi-pass for chains)
        for _ in range(3):
            prev = result
            result = self.REPEATED_WORDS.sub(r"\1", result)
            if result == prev:
                break
        # Remove false starts with em-dash
        result = self.FALSE_START.sub("", result)
        # Remove trailing hyphens
        result = self.TRAILING_HYPHEN.sub("", result)
        return result

    def _fix_punctuation(self, text: str) -> str:
        result = text
        result = self.SPACE_BEFORE_PUNCT.sub(r"\1", result)
        result = self.MULTI_PERIOD.sub(".", result)
        result = self.MISSING_SPACE_AFTER_PUNCT.sub(r"\1 \2", result)
        # Ensure sentence ends with punctuation
        if result and result[-1] not in ".!?":
            result += "."
        return result

    @staticmethod
    def _normalize_numbers(text: str) -> str:
        """Basic number normalisation."""
        # Replace digit sequences with their word form for TTS
        # Keep as-is — TTS systems handle digits natively
        return text

    def _capitalize(self, text: str) -> str:
        """Restore proper capitalisation."""
        result = text

        # Fix common contractions (lowercase → capitalised form)
        for lower, correct in self.CONTRACTIONS.items():
            # Word boundary replacement
            result = re.sub(rf"\b{lower}\b", correct, result, flags=re.IGNORECASE)

        # Capitalise "i" → "I"
        result = re.sub(r"\bi\b", "I", result)

        # Capitalise first word of sentences
        sentences = re.split(r"(?<=[.!?])\s+", result)
        capitalised = []
        for s in sentences:
            s = s.strip()
            if s and s[0].islower():
                s = s[0].upper() + s[1:]
            capitalised.append(s)
        result = " ".join(capitalised)

        return result
