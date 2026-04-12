"""ToolClassifier — rule-based tool categorization (no LLM needed).

Categories:
  EXTERNAL — returns content from external sources (web_fetch, search, etc.)
  INTERNAL — local read-only operations (file_read, file_list, etc.)
  COMMAND  — side-effect / write operations (bash, file_write, file_delete, etc.)
"""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from enum import Enum
from typing import Callable

log = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    EXTERNAL = "external"
    INTERNAL = "internal"
    COMMAND = "command"


# Type alias for custom rules
RuleFn = Callable[[str, str], ToolCategory | None]


class ToolClassifier:
    """Rule + keyword based tool classifier with LRU cache."""

    def __init__(self, cache_size: int = 256) -> None:
        # Exact name → category mapping
        self._exact: dict[str, ToolCategory] = {}
        # Prefix patterns (e.g. "web_" → EXTERNAL)
        self._prefixes: list[tuple[str, ToolCategory]] = []
        # Keyword patterns checked against description
        self._desc_keywords: list[tuple[re.Pattern, ToolCategory]] = []
        # User-registered custom rules (checked first)
        self._custom_rules: list[RuleFn] = []
        # LRU cache
        self._cache: OrderedDict[str, ToolCategory] = OrderedDict()
        self._cache_size = cache_size

        self._register_defaults()

    # ── default rule set ─────────────────────────────────────────────────

    def _register_defaults(self) -> None:
        # EXTERNAL tools (fetch / search external content)
        for name in (
            "web_fetch", "web_search", "http_get", "http_post", "http_request",
            "curl", "wget", "fetch_url", "search_web", "search_internet",
            "browse", "scrape", "download",
        ):
            self._exact[name] = ToolCategory.EXTERNAL

        self._prefixes.append(("web_", ToolCategory.EXTERNAL))
        self._prefixes.append(("http_", ToolCategory.EXTERNAL))
        self._prefixes.append(("fetch_", ToolCategory.EXTERNAL))
        self._prefixes.append(("search_", ToolCategory.EXTERNAL))
        self._prefixes.append(("browse_", ToolCategory.EXTERNAL))

        # INTERNAL tools (local read-only)
        for name in (
            "file_read", "file_list", "file_info", "file_stat",
            "read_file", "list_files", "cat", "head", "tail", "less",
            "grep", "find", "which", "whereis", "env", "echo", "pwd",
            "ls", "stat", "file", "wc", "diff",
            "memory_search", "memory_get",
        ):
            self._exact[name] = ToolCategory.INTERNAL

        self._prefixes.append(("read_", ToolCategory.INTERNAL))
        self._prefixes.append(("list_", ToolCategory.INTERNAL))
        self._prefixes.append(("get_", ToolCategory.INTERNAL))
        self._prefixes.append(("show_", ToolCategory.INTERNAL))
        self._prefixes.append(("view_", ToolCategory.INTERNAL))
        self._prefixes.append(("query_", ToolCategory.INTERNAL))
        self._prefixes.append(("check_", ToolCategory.INTERNAL))

        # COMMAND tools (side-effects / writes)
        for name in (
            "bash", "shell", "exec", "execute", "run_command",
            "file_write", "file_edit", "file_delete", "file_move", "file_copy",
            "write_file", "edit_file", "delete_file", "move_file", "copy_file",
            "mkdir", "rm", "cp", "mv", "chmod", "chown",
            "git_push", "git_commit", "deploy", "install", "pip_install",
            "npm_install", "apt_install",
        ):
            self._exact[name] = ToolCategory.COMMAND

        self._prefixes.append(("write_", ToolCategory.COMMAND))
        self._prefixes.append(("edit_", ToolCategory.COMMAND))
        self._prefixes.append(("delete_", ToolCategory.COMMAND))
        self._prefixes.append(("create_", ToolCategory.COMMAND))
        self._prefixes.append(("update_", ToolCategory.COMMAND))
        self._prefixes.append(("remove_", ToolCategory.COMMAND))
        self._prefixes.append(("install_", ToolCategory.COMMAND))
        self._prefixes.append(("deploy_", ToolCategory.COMMAND))

        # Description keyword fallbacks
        self._desc_keywords.append(
            (re.compile(r"\b(fetch|download|scrape|crawl|browse|search|url|http|request|api)\b", re.I),
             ToolCategory.EXTERNAL)
        )
        self._desc_keywords.append(
            (re.compile(r"\b(delete|remove|write|modify|create|update|execute|run|install|deploy|push|commit)\b", re.I),
             ToolCategory.COMMAND)
        )
        self._desc_keywords.append(
            (re.compile(r"\b(read|list|get|show|view|check|query|find|grep)\b", re.I),
             ToolCategory.INTERNAL)
        )

    # ── public API ───────────────────────────────────────────────────────

    def classify(self, tool_name: str, tool_description: str = "") -> ToolCategory:
        """Classify a tool into EXTERNAL / INTERNAL / COMMAND.

        Uses LRU cache; custom rules first, then exact match, prefix,
        description keywords, and finally defaults to INTERNAL.
        """
        cache_key = tool_name
        if cache_key in self._cache:
            # Move to end (most recently used)
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        category = self._do_classify(tool_name, tool_description)
        self._put_cache(cache_key, category)
        return category

    def register_rule(self, rule: RuleFn) -> None:
        """Register a custom classification rule.

        ``rule(name, description) -> ToolCategory | None``
        Custom rules are checked before built-in rules.
        """
        self._custom_rules.append(rule)
        self._cache.clear()

    def register_exact(self, name: str, category: ToolCategory) -> None:
        """Register an exact name → category mapping."""
        self._exact[name] = category
        self._cache.clear()

    def register_prefix(self, prefix: str, category: ToolCategory) -> None:
        """Register a prefix rule (e.g. "my_ext_" → EXTERNAL)."""
        self._prefixes.append((prefix, category))
        self._cache.clear()

    # ── internals ────────────────────────────────────────────────────────

    def _do_classify(self, tool_name: str, tool_description: str) -> ToolCategory:
        # 1. custom rules
        for rule in self._custom_rules:
            result = rule(tool_name, tool_description)
            if result is not None:
                return result

        # 2. exact match
        if tool_name in self._exact:
            return self._exact[tool_name]

        # 3. prefix match
        for prefix, category in self._prefixes:
            if tool_name.startswith(prefix):
                return category

        # 4. description keywords
        for pattern, category in self._desc_keywords:
            if pattern.search(tool_description):
                return category

        # default: INTERNAL (safe read-only)
        log.debug("ToolClassifier: defaulting %s to INTERNAL", tool_name)
        return ToolCategory.INTERNAL

    def _put_cache(self, key: str, value: ToolCategory) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
