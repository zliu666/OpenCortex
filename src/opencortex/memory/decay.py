"""Memory decay manager for tiered memories."""

from __future__ import annotations

import logging
from typing import Any

from opencortex.memory.tiered_store import MemoryTier, TieredMemoryStore

logger = logging.getLogger(__name__)

DEFAULT_RULES: dict[MemoryTier, dict[str, Any]] = {
    MemoryTier.CORE: {"ttl_days": 0, "downgrade_to": None},
    MemoryTier.SESSION: {"ttl_days": 7, "downgrade_to": MemoryTier.PROJECT},
    MemoryTier.USER: {"ttl_days": 0, "downgrade_to": None},
    MemoryTier.PROJECT: {"ttl_days": 30, "downgrade_to": MemoryTier.ARCHIVE},
    MemoryTier.ARCHIVE: {"ttl_days": 0, "downgrade_to": None},
}


class MemoryDecayManager:
    """Manages memory decay: downgrade memories that exceed their tier's TTL."""

    def __init__(
        self,
        store: TieredMemoryStore,
        rules: dict[MemoryTier, dict[str, Any]] | None = None,
    ) -> None:
        self._store = store
        self._rules = rules or DEFAULT_RULES

    def check_and_decay(self) -> list[dict[str, Any]]:
        """Check all tiers and decay expired entries. Returns list of decay records."""
        records: list[dict[str, Any]] = []

        for tier, rule in self._rules.items():
            ttl = rule.get("ttl_days", 0)
            target = rule.get("downgrade_to")
            if ttl == 0 or target is None:
                continue

            expired = self._store._get_expired_entries(tier, ttl)
            for entry in expired:
                self._store._move_entry(entry["id"], target)
                record = {
                    "entry_id": entry["id"],
                    "from_tier": tier.value,
                    "to_tier": target.value,
                    "content_preview": entry["content"][:80],
                }
                records.append(record)
                logger.info("Decayed memory %d: %s → %s", entry["id"], tier.value, target.value)

        return records

    def force_decay(self, entry_id: int, target_tier: MemoryTier) -> bool:
        """Force decay a specific entry to the target tier."""
        return self._store._move_entry(entry_id, target_tier)
