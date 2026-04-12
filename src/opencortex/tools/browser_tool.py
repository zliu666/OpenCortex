"""Browser automation tool using Playwright."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from opencortex.tools.base import BaseTool, ToolExecutionContext, ToolResult


class BrowserNavigateInput(BaseModel):
    """Arguments for browser_navigate."""

    url: str = Field(description="URL to navigate to (http:// or https://)")


class BrowserScreenshotInput(BaseModel):
    """Arguments for browser_screenshot."""

    full_page: bool = Field(
        default=False,
        description="Whether to capture the full scrollable page",
    )


class BrowserClickInput(BaseModel):
    """Arguments for browser_click."""

    selector: str = Field(
        description="CSS selector or accessibility label to click",
    )


class BrowserTypeInput(BaseModel):
    """Arguments for browser_type."""

    selector: str = Field(
        description="CSS selector or accessibility label to target",
    )
    text: str = Field(description="Text to type into the element")
    delay_ms: int = Field(
        default=0,
        ge=0,
        le=10000,
        description="Delay between keystrokes in milliseconds",
    )


class BrowserSnapshotInput(BaseModel):
    """Arguments for browser_snapshot."""

    max_length: int = Field(
        default=8000,
        ge=100,
        le=50000,
        description="Maximum length of the accessibility tree output",
    )


class _BrowserState:
    """Shared browser state for the session."""

    def __init__(self) -> None:
        self._browser = None
        self._context = None
        self._page = None
        self._lock = asyncio.Lock()

    @property
    def page(self):
        return self._page

    @property
    def is_initialized(self) -> bool:
        return self._page is not None

    async def initialize(self):
        """Initialize or return existing browser/page."""
        async with self._lock:
            if self._page is not None:
                return self._page

            from playwright.async_api import async_playwright

            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720}
            )
            self._page = await self._context.new_page()
            return self._page

    async def close(self):
        """Close browser resources."""
        async with self._lock:
            if self._page:
                await self._page.close()
                self._page = None
            if self._context:
                await self._context.close()
                self._context = None
            if self._browser:
                await self._browser.close()
                self._browser = None


# Global state instance
_browser_state: _BrowserState | None = None


def _get_browser_state() -> _BrowserState:
    """Get or create the browser state."""
    global _browser_state
    if _browser_state is None:
        _browser_state = _BrowserState()
    return _browser_state


class BrowserNavigateTool(BaseTool):
    """Navigate to a URL in the browser."""

    name = "browser_navigate"
    description = "Navigate to a URL in the browser. Opens a page and waits for it to load."
    input_model = BrowserNavigateInput

    async def execute(self, arguments: BrowserNavigateInput, context: ToolExecutionContext) -> ToolResult:
        try:
            page = await _get_browser_state().initialize()
            response = await page.goto(arguments.url, wait_until="domcontentloaded", timeout=30000)
            title = await page.title()
            status = response.status if response else "unknown"
            return ToolResult(
                output=f"Navigated to {arguments.url}\nStatus: {status}\nTitle: {title}",
                metadata={"url": arguments.url, "status": status, "title": title},
            )
        except Exception as e:
            return ToolResult(output=f"Navigation failed: {e}", is_error=True)


class BrowserScreenshotTool(BaseTool):
    """Take a screenshot of the current page."""

    name = "browser_screenshot"
    description = "Take a screenshot of the current browser page. Returns base64-encoded PNG."
    input_model = BrowserScreenshotInput

    async def execute(self, arguments: BrowserScreenshotInput, context: ToolExecutionContext) -> ToolResult:
        try:
            page = await _get_browser_state().initialize()
            screenshot_bytes = await page.screenshot(full_page=arguments.full_page)
            b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            return ToolResult(
                output=f"Screenshot captured ({len(screenshot_bytes)} bytes, base64 length: {len(b64)})",
                metadata={"screenshot_b64": b64, "full_page": arguments.full_page},
            )
        except Exception as e:
            return ToolResult(output=f"Screenshot failed: {e}", is_error=True)


class BrowserClickTool(BaseTool):
    """Click an element on the page."""

    name = "browser_click"
    description = "Click an element identified by CSS selector or accessibility label."
    input_model = BrowserClickInput

    async def execute(self, arguments: BrowserClickInput, context: ToolExecutionContext) -> ToolResult:
        try:
            page = await _get_browser_state().initialize()
            await page.click(arguments.selector, timeout=10000)
            return ToolResult(
                output=f"Clicked element: {arguments.selector}",
                metadata={"selector": arguments.selector},
            )
        except Exception as e:
            return ToolResult(output=f"Click failed: {e}", is_error=True)


class BrowserTypeTool(BaseTool):
    """Type text into an element."""

    name = "browser_type"
    description = "Type text into an input field or contenteditable element identified by selector."
    input_model = BrowserTypeInput

    async def execute(self, arguments: BrowserTypeInput, context: ToolExecutionContext) -> ToolResult:
        try:
            page = await _get_browser_state().initialize()
            delay = arguments.delay_ms / 1000.0  # Convert to seconds
            await page.fill(arguments.selector, arguments.text)
            if delay > 0:
                await page.wait_for_timeout(delay * 1000)
            return ToolResult(
                output=f"Typed text into {arguments.selector}: {arguments.text!r}",
                metadata={"selector": arguments.selector, "length": len(arguments.text)},
            )
        except Exception as e:
            return ToolResult(output=f"Type failed: {e}", is_error=True)


class BrowserSnapshotTool(BaseTool):
    """Get the accessibility tree of the current page."""

    name = "browser_snapshot"
    description = "Get a structured accessibility tree snapshot of the current page. Useful for understanding page structure."
    input_model = BrowserSnapshotInput

    async def execute(self, arguments: BrowserSnapshotInput, context: ToolExecutionContext) -> ToolResult:
        try:
            page = await _get_browser_state().initialize()
            # Get accessibility snapshot with rich info
            snapshot = await page.accessibility.snapshot()
            if snapshot is None:
                return ToolResult(output="Page has no accessibility tree", metadata={})

            # Serialize to text
            tree_text = _format_accessibility_node(snapshot, indent=0)
            if len(tree_text) > arguments.max_length:
                tree_text = tree_text[: arguments.max_length] + "\n...[truncated]..."
            return ToolResult(
                output=tree_text,
                metadata={"node_count": _count_nodes(snapshot)},
            )
        except Exception as e:
            return ToolResult(output=f"Snapshot failed: {e}", is_error=True)


def _format_accessibility_node(node: dict[str, Any], indent: int) -> str:
    """Format an accessibility node into readable text."""
    parts = []
    role = node.get("role", "")
    name = node.get("name", "")
    if name:
        parts.append(f"{'  ' * indent}[{role}] {name}")
    else:
        parts.append(f"{'  ' * indent}[{role}]")
    for child in node.get("children", []):
        parts.append(_format_accessibility_node(child, indent + 1))
    return "\n".join(parts)


def _count_nodes(node: dict[str, Any]) -> int:
    """Count total nodes in accessibility tree."""
    count = 1
    for child in node.get("children", []):
        count += _count_nodes(child)
    return count
