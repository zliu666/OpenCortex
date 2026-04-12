"""Memory nudge: periodic background review for auto-learning."""

from __future__ import annotations

import re

MEMORY_REVIEW_PROMPT = """Review the conversation above and consider saving to memory if appropriate.

Focus on:
1. Has the user revealed things about themselves — preferences, work habits, personal details?
2. Has the user expressed expectations about how you should behave?
3. Are there important decisions, patterns, or corrections worth remembering?

If something stands out, save it using the memory tool.
If nothing is worth saving, just say 'Nothing to save.' and stop.
"""

# Simple rule-based patterns for extracting memory-worthy content
_RULE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"I (?:always|never|usually|prefer|like|hate|love)\s+(.+)", re.I), "preference"),
    (re.compile(r"(?:please|make sure|always|never)\s+(?:make|do|use|set)\s+(.+)", re.I), "instruction"),
    (re.compile(r"(?:my name is|I'm called|call me)\s+(.+)", re.I), "identity"),
    (re.compile(r"I work (?:at|on|with|as)\s+(.+)", re.I), "work"),
]


class MemoryNudge:
    """定期触发后台审查，让 Agent 回顾对话并决定是否保存记忆。"""

    def __init__(self, memory_files, interval: int = 10) -> None:
        self.memory_files = memory_files  # MemoryFiles 实例
        self.interval = interval  # 每 N 轮触发一次
        self._turns = 0

    def tick(self) -> bool:
        """每轮调用，返回是否需要审查。"""
        self._turns += 1
        if self._turns >= self.interval:
            self._turns = 0
            return True
        return False

    async def review(self, messages: list[dict], api_client=None) -> list[str]:
        """后台审查对话，返回要保存的记忆条目。

        如果有 api_client，用 LLM 判断；否则用简单规则提取。
        messages 格式: [{"role": "user"|"assistant", "content": "..."}]
        """
        if api_client is not None:
            return await self._review_with_llm(messages, api_client)
        return self._review_with_rules(messages)

    async def _review_with_llm(self, messages: list[dict], api_client) -> list[str]:
        """Use LLM to review conversation and extract memory-worthy items."""
        recent = messages[-self.interval * 2 :]  # 最近对话
        prompt_messages = (
            [
                {"role": "system", "content": MEMORY_REVIEW_PROMPT},
            ]
            + recent
            + [
                {
                    "role": "user",
                    "content": "Based on the above conversation, list each memory-worthy item on its own line. If nothing, reply: Nothing to save.",
                },
            ]
        )
        response = await api_client.chat(prompt_messages)
        if not response or "Nothing to save" in response:
            return []
        # Each non-empty line is a suggestion
        return [line.strip().lstrip("- •") for line in response.splitlines() if line.strip()]

    def _review_with_rules(self, messages: list[dict]) -> list[str]:
        """Rule-based extraction of memory-worthy content from recent messages."""
        recent = messages[-self.interval * 2 :]
        suggestions: list[str] = []
        for msg in recent:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            for pattern, category in _RULE_PATTERNS:
                for match in pattern.finditer(content):
                    suggestion = f"[{category}] {match.group(0)}"
                    if suggestion not in suggestions:
                        suggestions.append(suggestion)
        return suggestions

    def apply_suggestions(self, suggestions: list[str]) -> None:
        """将建议保存的记忆写入 MEMORY.md。"""
        for entry in suggestions:
            self.memory_files.add_memory(entry)
