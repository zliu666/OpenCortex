"""Tests for Feishu channel implementation."""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Stub lark_oapi before importing the module under test ────────────

import sys
from types import ModuleType
from unittest.mock import MagicMock

# Fix Python logging to support {}-style format strings (used by loguru-like patterns)
import logging
_orig_getMessage = logging.LogRecord.getMessage
def _getMessage(self):
    msg = str(self.msg)
    if self.args and '{' in msg:
        try:
            return msg.format(*self.args) if isinstance(self.args, tuple) else msg.format(self.args)
        except (IndexError, KeyError, ValueError):
            pass
    if self.args:
        return msg % self.args
    return msg
logging.LogRecord.getMessage = _getMessage

_fake_lark = ModuleType("lark_oapi")
_fake_lark.Client = type("C", (), {
    "__init__": lambda s, *a, **kw: None,
    "builder": staticmethod(lambda: MagicMock(
        app_id=MagicMock(return_value=MagicMock(
            app_secret=MagicMock(return_value=MagicMock(
                log_level=MagicMock(return_value=MagicMock(build=MagicMock(return_value=MagicMock())))
            ))
        ))
    )),
})
_fake_lark.LogLevel = type("LL", (), {"INFO": 1})()
_fake_lark.ws = ModuleType("lark_oapi.ws")
_fake_lark.ws.Client = type("WSC", (), {"__init__": lambda s, *a, **kw: None, "start": lambda s: None})
_fake_ws_client_mod = ModuleType("lark_oapi.ws.client")
_fake_ws_client_mod.loop = None
_fake_lark.EventDispatcherHandler = type("EDH", (), {
    "builder": staticmethod(lambda *a, **kw: MagicMock(
        register_p2_im_message_receive_v1=MagicMock(return_value=MagicMock(build=MagicMock(return_value=MagicMock())))
    ))
})

# Set __spec__ to avoid ValueError
_fake_lark.__spec__ = MagicMock()
_fake_lark.__path__ = []
sys.modules["lark_oapi"] = _fake_lark
sys.modules["lark_oapi.ws"] = _fake_lark.ws
sys.modules["lark_oapi.ws.client"] = _fake_ws_client_mod

# Now also stub the lazy imports inside feishu.py
for _mod_name in [
    "lark_oapi.api.im.v1",
]:
    _m = ModuleType(_mod_name)
    _m.__spec__ = MagicMock()
    # Populate names that feishu.py lazy-imports
    _m.CreateMessageReactionRequest = MagicMock()
    _m.CreateMessageReactionRequestBody = MagicMock()
    _m.Emoji = MagicMock()
    _m.ReplyMessageRequest = MagicMock()
    _m.ReplyMessageRequestBody = MagicMock()
    _m.CreateMessageRequest = MagicMock()
    _m.CreateMessageRequestBody = MagicMock()
    _m.CreateImageRequest = MagicMock()
    _m.CreateImageRequestBody = MagicMock()
    _m.CreateFileRequest = MagicMock()
    _m.CreateFileRequestBody = MagicMock()
    _m.GetMessageResourceRequest = MagicMock()
    sys.modules[_mod_name] = _m

from opencortex.channels.impl.feishu import (
    FeishuChannel,
    _extract_post_content,
    _extract_post_text,
    _extract_share_card_content,
    _extract_interactive_content,
    _extract_element_content,
    MSG_TYPE_MAP,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@dataclass
class FakeConfig:
    app_id = "test-app-id"
    app_secret = "test-secret"
    encrypt_key = ""
    verification_token = ""
    react_emoji = "THUMBSUP"
    allow_from = ["*"]


def _make_bus():
    bus = MagicMock()
    bus.publish_inbound = AsyncMock()
    return bus


def _make_channel(config=None, bus=None):
    return FeishuChannel(config or FakeConfig(), bus or _make_bus())


def _make_event(
    message_id="msg_001",
    message_type="text",
    content='{"text": "hello"}',
    chat_id="oc_group1",
    chat_type="group",
    sender_type="user",
    open_id="ou_test",
    mentions=None,
):
    """Build a fake P2ImMessageReceiveV1 event data object."""
    mention_list = []
    if mentions:
        for m in mentions:
            obj = MagicMock()
            obj.sender_id = MagicMock()
            obj.sender_id.open_id = m.get("open_id", "")
            obj.key = m.get("key", "")
            mention_list.append(obj)

    sender = MagicMock()
    sender.sender_type = sender_type
    sender.sender_id = MagicMock()
    sender.sender_id.open_id = open_id

    message = MagicMock()
    message.message_id = message_id
    message.message_type = message_type
    message.content = content
    message.chat_id = chat_id
    message.chat_type = chat_type
    message.mentions = mention_list

    event = MagicMock()
    event.message = message
    event.sender = sender

    data = MagicMock()
    data.event = event
    return data


# ── Helper functions tests ────────────────────────────────────────────

class TestExtractPostContent:
    def test_simple_text(self):
        result = _extract_post_text({"title": "Hi", "content": [[{"tag": "text", "text": "hello"}]]})
        assert "hello" in result

    def test_with_title(self):
        text, imgs = _extract_post_content({"title": "Title", "content": [[{"tag": "text", "text": "body"}]]})
        assert "Title" in text
        assert "body" in text

    def test_with_images(self):
        content = {"content": [[{"tag": "img", "image_key": "img_key_123"}]]}
        text, imgs = _extract_post_content(content)
        assert imgs == ["img_key_123"]

    def test_localized_format(self):
        data = {"zh_cn": {"title": "标题", "content": [[{"tag": "text", "text": "内容"}]]}}
        text, _ = _extract_post_content(data)
        assert "标题" in text
        assert "内容" in text

    def test_empty_content(self):
        text, imgs = _extract_post_content({})
        assert text == ""
        assert imgs == []

    def test_wrapped_post_format(self):
        data = {"post": {"zh_cn": {"content": [[{"tag": "text", "text": "wrapped"}]]}}}
        text, _ = _extract_post_content(data)
        assert "wrapped" in text


class TestExtractShareCardContent:
    def test_share_chat(self):
        result = _extract_share_card_content({"chat_id": "oc_123"}, "share_chat")
        assert "shared chat" in result
        assert "oc_123" in result

    def test_interactive(self):
        content = {"header": {"title": {"content": "Card Title"}}, "elements": [[]]}
        result = _extract_share_card_content(content, "interactive")
        assert "Card Title" in result

    def test_unknown_type(self):
        result = _extract_share_card_content({}, "unknown_type")
        assert "[unknown_type]" in result

    def test_system(self):
        result = _extract_share_card_content({}, "system")
        assert "system message" in result


class TestExtractElementContent:
    def test_markdown_element(self):
        result = _extract_element_content({"tag": "markdown", "content": "**bold**"})
        assert "**bold**" in result

    def test_div_element(self):
        result = _extract_element_content({"tag": "div", "text": {"content": "hello"}})
        assert "hello" in result

    def test_button_element(self):
        result = _extract_element_content({"tag": "button", "text": {"content": "Click"}, "url": "https://example.com"})
        assert "Click" in result
        assert "link: https://example.com" in result

    def test_non_dict(self):
        result = _extract_element_content("not a dict")
        assert result == []


class TestMsgFormatDetection:
    def test_short_plain_text(self):
        assert FeishuChannel._detect_msg_format("hello") == "text"

    def test_code_block_triggers_card(self):
        assert FeishuChannel._detect_msg_format("```python\nprint('hi')\n```") == "interactive"

    def test_table_triggers_card(self):
        assert FeishuChannel._detect_msg_format("| a | b |\n|---|---|\n| 1 | 2 |") == "interactive"

    def test_heading_triggers_card(self):
        assert FeishuChannel._detect_msg_format("# Title\nbody") == "interactive"

    def test_bold_triggers_card(self):
        assert FeishuChannel._detect_msg_format("**bold text**") == "interactive"

    def test_link_triggers_post(self):
        assert FeishuChannel._detect_msg_format("Check [docs](https://example.com)") == "post"

    def test_long_text_triggers_card(self):
        assert FeishuChannel._detect_msg_format("x" * 3000) == "interactive"


class TestMarkdownToPost:
    def test_plain_text(self):
        result = FeishuChannel._markdown_to_post("hello world")
        data = json.loads(result)
        assert "zh_cn" in data

    def test_link_conversion(self):
        result = FeishuChannel._markdown_to_post("See [docs](https://example.com)")
        data = json.loads(result)
        content = data["zh_cn"]["content"]
        assert any(el.get("tag") == "a" for row in content for el in row)


class TestBuildCardElements:
    def test_plain_text(self):
        ch = _make_channel()
        elements = ch._build_card_elements("hello")
        assert len(elements) == 1
        assert elements[0]["tag"] == "markdown"

    def test_table_parsed(self):
        ch = _make_channel()
        elements = ch._build_card_elements("| a | b |\n|---|---|\n| 1 | 2 |")
        assert any(el.get("tag") == "table" for el in elements)

    def test_headings_split(self):
        ch = _make_channel()
        elements = ch._build_card_elements("## Title\ncontent")
        assert any(el.get("tag") == "div" for el in elements)


class TestSplitElementsByTableLimit:
    def test_single_table(self):
        from opencortex.channels.impl.feishu import FeishuChannel
        elements = [{"tag": "table"}, {"tag": "markdown", "content": "text"}]
        groups = FeishuChannel._split_elements_by_table_limit(elements, max_tables=1)
        assert len(groups) == 1

    def test_multiple_tables_split(self):
        from opencortex.channels.impl.feishu import FeishuChannel
        elements = [
            {"tag": "table", "columns": []},
            {"tag": "markdown", "content": "between"},
            {"tag": "table", "columns": []},
        ]
        groups = FeishuChannel._split_elements_by_table_limit(elements, max_tables=1)
        assert len(groups) == 2


# ── Channel instance tests ────────────────────────────────────────────

class TestFeishuChannel:
    @pytest.mark.asyncio
    async def test_on_message_text(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        data = _make_event(content='{"text": "hello bot"}')
        await ch._on_message(data)
        ch.bus.publish_inbound.assert_called_once()
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.content == "hello bot"
        assert msg.channel == "feishu"

    @pytest.mark.asyncio
    async def test_on_message_skip_bot(self):
        ch = _make_channel()
        data = _make_event(sender_type="bot")
        await ch._on_message(data)
        ch.bus.publish_inbound.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_message_dedup(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        data = _make_event(message_id="dup_1")
        await ch._on_message(data)
        await ch._on_message(data)
        assert ch.bus.publish_inbound.call_count == 1

    @pytest.mark.asyncio
    async def test_on_message_post(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        content = json.dumps({"title": "T", "content": [[{"tag": "text", "text": "body"}]]})
        data = _make_event(message_type="post", content=content)
        await ch._on_message(data)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert "body" in msg.content

    @pytest.mark.asyncio
    async def test_on_message_image(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        ch._download_and_save_media = AsyncMock(return_value=("/tmp/img.png", "[image: img.png]"))
        data = _make_event(message_type="image", content='{"image_key": "key_123"}')
        await ch._on_message(data)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert "image" in msg.content

    @pytest.mark.asyncio
    async def test_on_message_audio(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        ch._download_and_save_media = AsyncMock(return_value=(None, "[audio: download failed]"))
        data = _make_event(message_type="audio", content='{"file_key": "fk_1"}')
        await ch._on_message(data)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert "audio" in msg.content

    @pytest.mark.asyncio
    async def test_on_message_interactive_card(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        content = json.dumps({"header": {"title": {"content": "Card"}}})
        data = _make_event(message_type="interactive", content=content)
        await ch._on_message(data)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert "Card" in msg.content

    @pytest.mark.asyncio
    async def test_on_message_sticker(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        data = _make_event(message_type="sticker", content='{}')
        await ch._on_message(data)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert "[sticker]" in msg.content

    @pytest.mark.asyncio
    async def test_on_message_empty_skipped(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        data = _make_event(content='{"text": ""}', message_type="text")
        await ch._on_message(data)
        ch.bus.publish_inbound.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_message_share_chat(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        data = _make_event(message_type="share_chat", content='{"chat_id": "oc_abc"}')
        await ch._on_message(data)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert "shared chat" in msg.content

    @pytest.mark.asyncio
    async def test_on_message_private_chat_reply_to_sender(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        data = _make_event(chat_type="p2p", open_id="ou_me")
        await ch._on_message(data)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.chat_id == "ou_me"

    @pytest.mark.asyncio
    async def test_on_message_group_chat_reply_to_chat(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        data = _make_event(chat_type="group", chat_id="oc_grp")
        await ch._on_message(data)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert msg.chat_id == "oc_grp"

    @pytest.mark.asyncio
    async def test_on_message_group_mention_stripped(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._running = True
        data = _make_event(
            chat_type="group",
            content='{"text": "@_user_1 hello", "mention": "bot"}',
        )
        await ch._on_message(data)
        msg = ch.bus.publish_inbound.call_args[0][0]
        assert "@_user" not in msg.content

    def test_is_allowed_wildcard(self):
        ch = _make_channel()
        assert ch.is_allowed("anyone") is True

    def test_is_allowed_denied_when_empty(self):
        ch = _make_channel(FakeConfig())
        ch.config.allow_from = []
        assert ch.is_allowed("anyone") is False

    def test_is_allowed_specific_user(self):
        ch = _make_channel()
        ch.config.allow_from = ["ou_allowed"]
        assert ch.is_allowed("ou_allowed") is True
        assert ch.is_allowed("ou_other") is False


class TestFeishuSend:
    @pytest.mark.asyncio
    async def test_send_text(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._send_message_sync = MagicMock(return_value=True)
        from opencortex.channels.bus.events import OutboundMessage
        msg = OutboundMessage(channel="feishu", chat_id="oc_1", content="hello")
        await ch.send(msg)
        ch._send_message_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_reply(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._send_reply_sync = MagicMock(return_value=True)
        from opencortex.channels.bus.events import OutboundMessage
        msg = OutboundMessage(channel="feishu", chat_id="oc_1", content="reply text", reply_to="msg_123")
        await ch.send(msg)
        ch._send_reply_sync.assert_called()

    @pytest.mark.asyncio
    async def test_send_reply_via_metadata(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._send_reply_sync = MagicMock(return_value=True)
        from opencortex.channels.bus.events import OutboundMessage
        msg = OutboundMessage(
            channel="feishu", chat_id="oc_1", content="reply",
            metadata={"message_id": "msg_456"},
        )
        await ch.send(msg)
        ch._send_reply_sync.assert_called()

    @pytest.mark.asyncio
    async def test_send_not_initialized(self):
        ch = _make_channel()
        ch._client = None
        from opencortex.channels.bus.events import OutboundMessage
        msg = OutboundMessage(channel="feishu", chat_id="oc_1", content="hello")
        await ch.send(msg)  # Should not raise

    @pytest.mark.asyncio
    async def test_send_interactive_card(self):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._send_message_sync = MagicMock(return_value=True)
        from opencortex.channels.bus.events import OutboundMessage
        msg = OutboundMessage(channel="feishu", chat_id="oc_1", content="# Title\n```code```")
        await ch.send(msg)
        assert ch._send_message_sync.call_count >= 1

    @pytest.mark.asyncio
    async def test_send_with_media_image(self, tmp_path):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._upload_image_sync = MagicMock(return_value="img_key")
        ch._send_message_sync = MagicMock(return_value=True)
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n")
        from opencortex.channels.bus.events import OutboundMessage
        msg = OutboundMessage(channel="feishu", chat_id="oc_1", content="see image", media=[str(img)])
        await ch.send(msg)
        ch._upload_image_sync.assert_called_once_with(str(img))
        ch._send_message_sync.assert_called()

    @pytest.mark.asyncio
    async def test_send_with_media_file(self, tmp_path):
        ch = _make_channel()
        ch._client = MagicMock()
        ch._upload_file_sync = MagicMock(return_value="file_key")
        ch._send_message_sync = MagicMock(return_value=True)
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"%PDF-1.4")
        from opencortex.channels.bus.events import OutboundMessage
        msg = OutboundMessage(channel="feishu", chat_id="oc_1", content="", media=[str(f)])
        await ch.send(msg)
        ch._upload_file_sync.assert_called_once_with(str(f))


class TestParseMdTable:
    def test_simple_table(self):
        ch = _make_channel()
        result = FeishuChannel._parse_md_table("| a | b |\n|---|---|\n| 1 | 2 |")
        assert result is not None
        assert result["tag"] == "table"
        assert len(result["rows"]) == 1

    def test_too_short(self):
        assert FeishuChannel._parse_md_table("| a |") is None
