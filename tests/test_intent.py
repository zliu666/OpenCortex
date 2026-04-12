"""Tests for IntentInjector — Tool-as-Solver protocol intent injection."""

from __future__ import annotations

import json

import pytest

from opencortex.security.intent import (
    IntentInjector,
    INTENT_PARAM_SCHEMA,
    INTENT_TOOL_DESCRIPTION_TEMPLATE,
)


class TestIntentInjectorInit:
    def test_init(self):
        injector = IntentInjector()
        assert injector is not None


class TestIntentInjection:
    def test_injects_intent_parameter(self):
        injector = IntentInjector()
        schema = {
            "name": "web_fetch",
            "description": "Fetch a web page",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
            },
        }

        result = injector.inject_intent(schema)

        # Check intent parameter was added
        params = result["parameters"]
        assert "intent" in params["properties"]
        assert "intent" in params["required"]

    def test_intent_has_correct_schema(self):
        injector = IntentInjector()
        schema = {
            "name": "web_search",
            "description": "Search the web",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
            },
        }

        result = injector.inject_intent(schema)

        intent_param = result["parameters"]["properties"]["intent"]
        assert intent_param["type"] == "object"
        assert "extract" in intent_param["description"].lower()
        assert "json" in intent_param["description"].lower()

    def test_adds_intent_to_required(self):
        injector = IntentInjector()
        schema = {
            "name": "http_get",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
                "required": ["url"],
            },
        }

        result = injector.inject_intent(schema)

        assert "intent" in result["parameters"]["required"]
        assert "url" in result["parameters"]["required"]

    def test_modifies_description_with_intent(self):
        injector = IntentInjector()
        schema = {
            "name": "web_fetch",
            "description": "Fetch a webpage content",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                },
            },
        }

        result = injector.inject_intent(schema, intent_description="Get page summary")

        # Check description was modified
        assert "intent" in result["description"].lower()
        assert "extract" in result["description"].lower()
        assert "return value" in result["description"].lower()

    def test_handles_function_wrapper_format(self):
        injector = IntentInjector()
        schema = {
            "type": "function",
            "function": {
                "name": "web_fetch",
                "description": "Fetch a webpage",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                    },
                },
            },
        }

        result = injector.inject_intent(schema)

        # Should work with wrapper format
        func = result["function"]
        assert "intent" in func["parameters"]["properties"]
        assert "intent" in func["parameters"]["required"]

    def test_preserves_other_parameters(self):
        injector = IntentInjector()
        schema = {
            "name": "web_search",
            "description": "Search the web",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
        }

        result = injector.inject_intent(schema)

        props = result["parameters"]["properties"]
        assert "url" not in props  # Not in original
        assert "query" in props
        assert "limit" in props
        assert "intent" in props


class TestIntentExtraction:
    def test_extract_intent_dict_from_args(self):
        injector = IntentInjector()
        args = {
            "url": "https://example.com",
            "intent": {"summary": "brief summary"},
        }

        intent = injector.extract_intent_from_args(args)

        assert intent == {"summary": "brief summary"}

    def test_extract_intent_string_from_args(self):
        injector = IntentInjector()
        args = {
            "url": "https://example.com",
            "intent": '{"summary": "brief summary"}',
        }

        intent = injector.extract_intent_from_args(args)

        assert intent == {"summary": "brief summary"}

    def test_extract_intent_returns_none_for_missing(self):
        injector = IntentInjector()
        args = {"url": "https://example.com"}

        intent = injector.extract_intent_from_args(args)

        assert intent is None

    def test_extract_intent_returns_none_for_invalid_json(self):
        injector = IntentInjector()
        args = {
            "url": "https://example.com",
            "intent": "not a valid json",
        }

        intent = injector.extract_intent_from_args(args)

        assert intent is None

    def test_extract_intent_returns_none_for_empty_dict(self):
        injector = IntentInjector()
        args = {
            "url": "https://example.com",
            "intent": {},
        }

        intent = injector.extract_intent_from_args(args)

        assert intent is None

    def test_extract_complex_nested_intent(self):
        injector = IntentInjector()
        args = {
            "url": "https://example.com",
            "intent": json.dumps({
                "summary": "page overview",
                "key_points": ["point 1", "point 2"],
                "metadata": {"author": "test"},
            }),
        }

        intent = injector.extract_intent_from_args(args)

        assert intent["summary"] == "page overview"
        assert len(intent["key_points"]) == 2
        assert intent["metadata"]["author"] == "test"


class TestIntentStripping:
    def test_strip_intent_removes_intent_key(self):
        injector = IntentInjector()
        args = {
            "url": "https://example.com",
            "intent": {"summary": "test"},
            "other_param": "value",
        }

        stripped = injector.strip_intent_from_args(args)

        assert "intent" not in stripped
        assert stripped["url"] == "https://example.com"
        assert stripped["other_param"] == "value"

    def test_strip_intent_does_not_modify_original(self):
        injector = IntentInjector()
        args = {
            "url": "https://example.com",
            "intent": {"summary": "test"},
        }

        stripped = injector.strip_intent_from_args(args)

        # Original should still have intent
        assert "intent" in args
        # Stripped version should not
        assert "intent" not in stripped

    def test_strip_intent_handles_empty_args(self):
        injector = IntentInjector()
        args = {}

        stripped = injector.strip_intent_from_args(args)

        assert stripped == {}

    def test_strip_intent_handles_args_without_intent(self):
        injector = IntentInjector()
        args = {"url": "https://example.com"}

        stripped = injector.strip_intent_from_args(args)

        assert stripped == {"url": "https://example.com"}


class TestSubagentPromptBuilding:
    def test_build_prompt_with_dict_intent(self):
        injector = IntentInjector()

        prompt = injector.build_subagent_prompt(
            "web_fetch",
            "<html>some html content</html>",
            {"summary": "extract summary"},
        )

        assert "web_fetch" in prompt
        assert "extract summary" in prompt
        assert "<html>some html content</html>" in prompt
        assert "Extract only the information" in prompt

    def test_build_prompt_with_string_intent(self):
        injector = IntentInjector()

        prompt = injector.build_subagent_prompt(
            "web_search",
            "search result content...",
            "Get the top 5 results",
        )

        assert "web_search" in prompt
        assert "Get the top 5 results" in prompt
        assert "search result content..." in prompt

    def test_build_prompt_with_none_intent(self):
        injector = IntentInjector()

        prompt = injector.build_subagent_prompt(
            "web_fetch",
            "content...",
            None,
        )

        assert "web_fetch" in prompt
        assert "all relevant factual information" in prompt.lower()
        assert "content..." in prompt

    def test_build_prompt_ignores_instructions(self):
        injector = IntentInjector()

        prompt = injector.build_subagent_prompt(
            "web_fetch",
            "result",
            {"extract": "data"},
        )

        # Prompt should instruct sub-agent to ignore instructions
        assert "ignore" in prompt.lower()
        assert "instruction" in prompt.lower()

    def test_build_prompt_requests_json(self):
        injector = IntentInjector()

        prompt = injector.build_subagent_prompt(
            "web_fetch",
            "result",
            {"data": "value"},
        )

        assert "JSON" in prompt


class TestConstants:
    def test_intent_param_schema_exists(self):
        assert INTENT_PARAM_SCHEMA
        assert INTENT_PARAM_SCHEMA["type"] == "object"
        assert "description" in INTENT_PARAM_SCHEMA

    def test_intent_description_template_exists(self):
        assert INTENT_TOOL_DESCRIPTION_TEMPLATE
        assert "{intent}" in INTENT_TOOL_DESCRIPTION_TEMPLATE
        assert "{original_description}" in INTENT_TOOL_DESCRIPTION_TEMPLATE
