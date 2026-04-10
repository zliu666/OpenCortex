"""Auto Dream: memory consolidation engine."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from opencortex.memory.tiered_store import MemoryTier, TieredMemoryStore

logger = logging.getLogger(__name__)


class MemoryDream:
    """Memory consolidation engine (Auto Dream).

    Executes a 4-phase process:
      Phase 1: Inventory — catalog all memories
      Phase 2: Signal gathering — detect duplicates, contradictions, staleness
      Phase 3: Consolidation — plan merges, deduplication, resolution
      Phase 4: Output — apply changes to the store
    """

    def __init__(self, store: TieredMemoryStore) -> None:
        self._store = store

    async def dream(self) -> dict[str, Any]:
        """Execute the full dream cycle. Returns a summary dict."""
        inventory = self._inventory()
        signals = self._gather_signals(inventory)
        plan = self._consolidate(signals)
        result = self._output(plan)
        result["inventory_summary"] = {
            k: v["count"] for k, v in inventory.items()
        }
        result["signals_found"] = len(signals)
        return result

    # ------------------------------------------------------------------
    # Phase 1: Inventory
    # ------------------------------------------------------------------

    def _inventory(self) -> dict[str, dict[str, Any]]:
        """Catalog all memories across tiers."""
        stats = self._store.get_tier_stats()
        inventory: dict[str, dict[str, Any]] = {}
        for tier in MemoryTier:
            count = stats[tier]["count"]
            entries: list[dict[str, Any]] = []
            if count > 0:
                conn = self._store._connect()
                rows = conn.execute(
                    "SELECT * FROM tiered_memories WHERE tier = ? ORDER BY updated_at DESC LIMIT 500",
                    (tier.value,),
                ).fetchall()
                entries = [self._store._row_to_dict(r) for r in rows]
            inventory[tier.value] = {"count": count, "entries": entries}
        return inventory

    # ------------------------------------------------------------------
    # Phase 2: Signal gathering
    # ------------------------------------------------------------------

    def _gather_signals(self, inventory: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Detect duplicate and near-duplicate signals across all tiers."""
        signals: list[dict[str, Any]] = []
        all_entries: list[dict[str, Any]] = []

        for tier_data in inventory.values():
            all_entries.extend(tier_data["entries"])

        # Simple dedup: compare content similarity via substring overlap
        seen_hashes: set[int] = set()
        for i, entry in enumerate(all_entries):
            content_lower = entry["content"].lower().strip()
            content_hash = hash(content_lower)
            if content_hash in seen_hashes:
                signals.append({
                    "type": "duplicate",
                    "entry_id": entry["id"],
                    "content_preview": content_lower[:80],
                })
                continue
            seen_hashes.add(content_hash)

            # Check for near-duplicates (one content is substring of another)
            for j, other in enumerate(all_entries):
                if i >= j:
                    continue
                other_lower = other["content"].lower().strip()
                if len(content_lower) > 20 and content_lower in other_lower:
                    signals.append({
                        "type": "near_duplicate",
                        "entry_ids": [entry["id"], other["id"]],
                        "content_preview": content_lower[:80],
                    })

        return signals

    # ------------------------------------------------------------------
    # Phase 3: Consolidation
    # ------------------------------------------------------------------

    def _consolidate(self, signals: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a consolidation plan from signals."""
        plan: dict[str, Any] = {
            "to_remove": [],
            "to_archive": [],
            "to_merge": [],
        }

        for signal in signals:
            if signal["type"] == "duplicate":
                # Archive the duplicate
                plan["to_archive"].append(signal["entry_id"])
            elif signal["type"] == "near_duplicate":
                # Keep the longer one, archive the shorter
                ids = signal["entry_ids"]
                plan["to_archive"].append(ids[0])

        return plan

    # ------------------------------------------------------------------
    # Phase 4: Output
    # ------------------------------------------------------------------

    def _output(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Apply the consolidation plan."""
        archived = 0
        for entry_id in plan.get("to_archive", []):
            try:
                self._store._move_entry(entry_id, MemoryTier.ARCHIVE)
                archived += 1
            except Exception:
                logger.warning("Failed to archive entry %d", entry_id)

        return {
            "archived": archived,
            "removed": 0,
            "merged": 0,
        }
