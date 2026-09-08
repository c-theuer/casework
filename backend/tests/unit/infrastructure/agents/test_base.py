import json
from unittest.mock import patch

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from pydantic import BaseModel

from app.infrastructure.agents.base import AgentOutputError, _extract_json, run_agent


class _Widget(BaseModel):
    name: str
    count: int


def _assistant_text(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextBlock(text=text)], model="claude-test")


def _fake_query_yielding(*texts: str):
    """Builds a fake query() replacement: one AssistantMessage per call in
    `texts`, consumed in order across successive invocations."""
    responses = iter(texts)

    async def _fake_query(*, prompt, options):
        text = next(responses)
        yield _assistant_text(text)

    return _fake_query


class TestExtractJson:
    def test_extracts_bare_json_object(self):
        assert _extract_json('{"a": 1}') == {"a": 1}

    def test_extracts_json_from_markdown_fence(self):
        text = 'Here you go:\n```json\n{"a": 1}\n```\nDone.'
        assert _extract_json(text) == {"a": 1}

    def test_extracts_json_object_with_trailing_prose(self):
        text = 'I looked into it and found: {"a": 1} -- that should do it.'
        assert _extract_json(text) == {"a": 1}

    def test_extracts_json_object_ignoring_a_second_trailing_json_blob(self):
        """Regression test: a real Claude Agent SDK response once included
        a second, unrelated JSON-ish fragment after the real answer, which
        the old rfind("{")/rfind("}") slice-based extraction turned into a
        malformed span and a spurious "Extra data" JSONDecodeError.
        raw_decode-from-the-first-brace stops at the end of the first
        complete value and ignores everything after it."""
        text = '{"a": 1}\n\nNote: {"unrelated": true}'
        assert _extract_json(text) == {"a": 1}

    def test_raises_json_decode_error_when_no_object_present(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json("no json here at all")


@pytest.mark.asyncio
class TestRunAgent:
    async def test_returns_validated_model_on_first_success(self):
        with patch(
            "app.infrastructure.agents.base.query",
            side_effect=_fake_query_yielding('{"name": "widget", "count": 3}'),
        ):
            result = await run_agent(
                agent_name="TestAgent",
                system_prompt="be a widget describer",
                input_payload={"x": 1},
                output_model=_Widget,
            )
        assert result == _Widget(name="widget", count=3)

    async def test_retries_once_and_succeeds_with_corrected_output(self):
        with patch(
            "app.infrastructure.agents.base.query",
            side_effect=_fake_query_yielding(
                '{"name": "widget"}',  # missing required "count" -> ValidationError
                '{"name": "widget", "count": 3}',
            ),
        ):
            result = await run_agent(
                agent_name="TestAgent",
                system_prompt="be a widget describer",
                input_payload={"x": 1},
                output_model=_Widget,
            )
        assert result == _Widget(name="widget", count=3)

    async def test_raises_agent_output_error_after_exhausting_retries(self):
        with patch(
            "app.infrastructure.agents.base.query",
            side_effect=_fake_query_yielding("not json at all", "still not json"),
        ), pytest.raises(AgentOutputError) as exc_info:
            await run_agent(
                agent_name="TestAgent",
                system_prompt="be a widget describer",
                input_payload={"x": 1},
                output_model=_Widget,
                max_retries=1,
            )
        assert exc_info.value.agent_name == "TestAgent"

    async def test_passes_mcp_servers_and_allowed_tools_through_to_options(self):
        captured_options = {}

        async def _fake_query(*, prompt, options):
            captured_options["mcp_servers"] = options.mcp_servers
            captured_options["allowed_tools"] = options.allowed_tools
            captured_options["tools"] = options.tools
            captured_options["permission_mode"] = options.permission_mode
            yield _assistant_text('{"name": "widget", "count": 1}')

        with patch("app.infrastructure.agents.base.query", side_effect=_fake_query):
            await run_agent(
                agent_name="TestAgent",
                system_prompt="be a widget describer",
                input_payload={},
                output_model=_Widget,
                mcp_servers={"postgres": {"type": "stdio", "command": "uvx", "args": []}},
                allowed_tools=["mcp__postgres__execute_sql"],
            )

        assert captured_options["mcp_servers"] == {
            "postgres": {"type": "stdio", "command": "uvx", "args": []}
        }
        assert captured_options["allowed_tools"] == ["mcp__postgres__execute_sql"]
        # No built-in tools for any agent -- only the explicit MCP tools above.
        assert captured_options["tools"] == []
        # Headless: never hang on an unanswered permission prompt.
        assert captured_options["permission_mode"] == "dontAsk"
