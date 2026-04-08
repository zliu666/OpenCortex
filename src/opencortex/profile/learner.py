"""Preference learner — extracts user preferences from interactions."""

from __future__ import annotations

import logging
import re
from typing import Any

from opencortex.profile.store import ProfileStore

logger = logging.getLogger(__name__)

# Patterns that signal user preferences
_PREFERENCE_PATTERNS: list[tuple[str, str, str]] = [
    # (regex, category, key_template)
    (r"(?:i |i'm |my name is |call me )(\w+)", "identity", "name"),
    (r"(?:i (?:prefer|like|want|love) )(.*?)(?:\.|$)", "preference", "preference"),
    (r"(?:i (?:hate|dislike|don't like|don't want) )(.*?)(?:\.|$)", "preference", "dislike"),
    (r"(?:always|never) (?:use|do|show) (.*?)(?:\.|$)", "instruction", "instruction"),
    (r"(?:my (?:timezone|tz) is )([\w/+_-]+)", "identity", "timezone"),
    (r"(?:i (?:work|live) (?:in |at )([\w\s]+))", "identity", "location"),
    (r"(?:speak|respond|reply|answer) (?:in|using) (\w+)", "communication", "language"),
    (r"(?:be (?:more|less) )([\w]+)", "communication", "style"),
]


class PreferenceLearner:
    """Analyzes user messages to learn and store preferences."""

    def __init__(self, store: ProfileStore | None = None) -> None:
        self._store = store or ProfileStore()

    def analyze_message(self, message: str) -> list[dict[str, Any]]:
        """Extract preferences from a user message.

        Returns a list of detected preferences that were stored.
        """
        detected: list[dict[str, Any]] = []
        lower_msg = message.lower().strip()

        for pattern, category, key_template in _PREFERENCE_PATTERNS:
            match = re.search(pattern, lower_msg, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if not value or len(value) < 2:
                    continue

                key = f"{key_template}:{value[:50]}" if key_template == "preference" else key_template

                # Check if we already have this preference
                existing = self._store.get(key)
                confidence = 0.7 if existing else 0.5  # Increase confidence on repetition

                self._store.set(
                    key=key,
                    value=value,
                    category=category,
                    confidence=confidence,
                    source="learned",
                )
                detected.append(
                    {
                        "key": key,
                        "value": value,
                        "category": category,
                        "confidence": confidence,
                    }
                )

        return detected

    def get_profile_prompt(self) -> str:
        """Return the formatted user profile for system prompts."""
        return self._store.format_for_prompt()

    @property
    def store(self) -> ProfileStore:
        return self._store
