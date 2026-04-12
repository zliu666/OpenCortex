"""Tests for PersistenceStore."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import pytest_asyncio

from opencortex.persistence.store import PersistenceStore


@pytest_asyncio.fixture
async def store(tmp_path: Path) -> PersistenceStore:
    s = PersistenceStore(tmp_path / "test.db")
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_init_schema_and_tables_exist(store: PersistenceStore):
    """Schema initializes without error and tables exist."""
    db = await store._get_db()
    tables = await db.execute_fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    names = [r[0] for r in tables]
    assert "sessions" in names
    assert "messages" in names
    assert "schema_version" in names


@pytest.mark.asyncio
async def test_create_and_list_sessions(store: PersistenceStore):
    await store.create_session("s1", source="cli", model="gpt-4", title="Test")
    sessions = await store.list_sessions()
    assert len(sessions) == 1
    assert sessions[0]["id"] == "s1"
    assert sessions[0]["model"] == "gpt-4"


@pytest.mark.asyncio
async def test_end_session(store: PersistenceStore):
    await store.create_session("s2")
    await store.end_session("s2")
    sessions = await store.list_sessions()
    assert sessions[0]["ended_at"] is not None


@pytest.mark.asyncio
async def test_append_and_get_messages(store: PersistenceStore):
    await store.create_session("s3")
    await store.append_message("s3", "user", "Hello")
    msg_id = await store.append_message("s3", "assistant", "Hi there", token_count=10)
    assert isinstance(msg_id, int)

    msgs = await store.get_session_messages("s3")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["content"] == "Hi there"
    assert msgs[1]["token_count"] == 10


@pytest.mark.asyncio
async def test_get_messages_with_limit(store: PersistenceStore):
    await store.create_session("s4")
    for i in range(5):
        await store.append_message("s4", "user", f"msg {i}")
    msgs = await store.get_session_messages("s4", limit=2)
    assert len(msgs) == 2


@pytest.mark.asyncio
async def test_append_message_with_tool_calls(store: PersistenceStore):
    await store.create_session("s5")
    await store.append_message(
        "s5", "assistant", None,
        tool_calls=[{"name": "read", "args": {"path": "/tmp"}}],
    )
    msgs = await store.get_session_messages("s5")
    assert msgs[0]["tool_calls"] is not None


@pytest.mark.asyncio
async def test_fts5_search(store: PersistenceStore):
    await store.create_session("s6")
    await store.append_message("s6", "user", "Python is a great programming language")
    await store.append_message("s6", "user", "Rust is fast and safe")
    await store.append_message("s6", "user", "I love programming in Python")

    results = await store.search_messages("Python")
    assert len(results) == 2


@pytest.mark.asyncio
async def test_list_sessions_pagination(store: PersistenceStore):
    for i in range(5):
        await store.create_session(f"page_{i}")
    page1 = await store.list_sessions(limit=2, offset=0)
    page2 = await store.list_sessions(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["id"] != page2[0]["id"]


@pytest.mark.asyncio
async def test_concurrent_writes(tmp_path: Path):
    """Multiple tasks writing to the same store concurrently."""
    store = PersistenceStore(tmp_path / "concurrent.db")
    await store.create_session("concurrent")

    async def write(idx: int):
        for j in range(10):
            await store.append_message("concurrent", "user", f"msg-{idx}-{j}")

    await asyncio.gather(*[write(i) for i in range(5)])
    msgs = await store.get_session_messages("concurrent")
    assert len(msgs) == 50
    await store.close()


@pytest.mark.asyncio
async def test_system_prompt_stored_as_message(store: PersistenceStore):
    await store.create_session("s7", system_prompt="You are helpful.")
    msgs = await store.get_session_messages("s7")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "system"
    assert msgs[0]["content"] == "You are helpful."
