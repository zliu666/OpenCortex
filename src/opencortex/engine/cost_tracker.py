"""Simple usage aggregation with optional per-model tracking."""

from __future__ import annotations

from opencortex.api.usage import UsageSnapshot


class CostTracker:
    """Accumulate usage over the lifetime of a session.

    When dual-model routing is active, tracks usage separately for
    each provider key (``primary`` and ``execution``).
    """

    def __init__(self) -> None:
        self._usage = UsageSnapshot()
        self._per_model: dict[str, UsageSnapshot] = {}

    def add(self, usage: UsageSnapshot, *, provider_key: str = "primary") -> None:
        """Add a usage snapshot to the running total.

        Args:
            usage: The usage snapshot to add.
            provider_key: "primary" or "execution" for per-model tracking.
        """
        self._usage = UsageSnapshot(
            input_tokens=self._usage.input_tokens + usage.input_tokens,
            output_tokens=self._usage.output_tokens + usage.output_tokens,
        )
        existing = self._per_model.get(provider_key, UsageSnapshot())
        self._per_model[provider_key] = UsageSnapshot(
            input_tokens=existing.input_tokens + usage.input_tokens,
            output_tokens=existing.output_tokens + usage.output_tokens,
        )

    @property
    def total(self) -> UsageSnapshot:
        """Return the aggregated usage."""
        return self._usage

    @property
    def per_model(self) -> dict[str, UsageSnapshot]:
        """Return per-model usage breakdown."""
        return dict(self._per_model)

    def summary(self) -> str:
        """Return a human-readable usage summary."""
        lines = [
            f"Total: {self._usage.input_tokens}in / {self._usage.output_tokens}out "
            f"({self._usage.total_tokens} tokens)"
        ]
        for key, usage in self._per_model.items():
            lines.append(
                f"  {key}: {usage.input_tokens}in / {usage.output_tokens}out "
                f"({usage.total_tokens} tokens)"
            )
        return "\n".join(lines)
