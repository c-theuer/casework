import json
from unittest.mock import patch

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage
from pydantic import BaseModel

from app.infrastructure.agents.base import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    AgentActionError,
    AgentOutputError,
    _extract_json,
    run_agent,
    run_agent_freeform,
)


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


def _assistant_tool_use(*, name: str = "mcp__slack__slack_post_message", text_after: str = "") -> list:
    """One AssistantMessage carrying a ToolUseBlock, optionally followed by
    a second AssistantMessage with trailing text (e.g. the final summary +
    status line the model writes after seeing the tool result)."""
    messages = [AssistantMessage(content=[ToolUseBlock(id="tu_1", name=name, input={})], model="claude-test")]
    if text_after:
        messages.append(_assistant_text(text_after))
    return messages


def _user_tool_result(*, is_error: bool, content: str = "ok") -> UserMessage:
    return UserMessage(
        content=[ToolResultBlock(tool_use_id="tu_1", content=content, is_error=is_error)],
        uuid="u_1",
        parent_tool_use_id=None,
        tool_use_result=None,
    )


@pytest.mark.asyncio
class TestRunAgentFreeform:
    async def test_returns_text_with_status_line_stripped_on_success(self):
        async def _fake_query(*, prompt, options):
            for msg in _assistant_tool_use(text_after=f"Posted the message.\n{STATUS_SUCCESS}"):
                yield msg
            yield _user_tool_result(is_error=False)

        with patch("app.infrastructure.agents.base.query", side_effect=_fake_query):
            result = await run_agent_freeform(
                agent_name="TestAgent", system_prompt="be helpful", prompt="do it"
            )
        assert result == "Posted the message."

    async def test_raises_when_no_tool_was_ever_called(self):
        async def _fake_query(*, prompt, options):
            yield _assistant_text(f"I posted it.\n{STATUS_SUCCESS}")

        with (
            patch("app.infrastructure.agents.base.query", side_effect=_fake_query),
            pytest.raises(AgentActionError) as exc_info,
        ):
            await run_agent_freeform(agent_name="TestAgent", system_prompt="be helpful", prompt="do it")
        assert "never called any tool" in str(exc_info.value)

    async def test_raises_when_a_tool_call_comes_back_as_an_mcp_error(self):
        async def _fake_query(*, prompt, options):
            for msg in _assistant_tool_use(text_after=f"Done.\n{STATUS_SUCCESS}"):
                yield msg
            yield _user_tool_result(is_error=True, content="permission denied")

        with (
            patch("app.infrastructure.agents.base.query", side_effect=_fake_query),
            pytest.raises(AgentActionError) as exc_info,
        ):
            await run_agent_freeform(agent_name="TestAgent", system_prompt="be helpful", prompt="do it")
        assert "tool call(s) failed" in str(exc_info.value)

    async def test_raises_when_model_reports_status_failed(self):
        """Regression test: a Slack tool call can return a normal (non-error)
        MCP result whose *content* is itself an application-level failure
        (Slack's own {"ok": false, "error": "missing_scope"}) -- the model
        correctly reads this and says so, but without an explicit checkable
        marker there was nothing stopping that from being logged as a
        success anyway."""

        async def _fake_query(*, prompt, options):
            for msg in _assistant_tool_use(
                text_after=f"Could not post: missing_scope.\n{STATUS_FAILED}"
            ):
                yield msg
            yield _user_tool_result(is_error=False, content='{"ok": true}')

        with (
            patch("app.infrastructure.agents.base.query", side_effect=_fake_query),
            pytest.raises(AgentActionError) as exc_info,
        ):
            await run_agent_freeform(agent_name="TestAgent", system_prompt="be helpful", prompt="do it")
        assert "did not confirm success" in str(exc_info.value)

    async def test_raises_when_tool_payload_reports_application_level_failure(self):
        async def _fake_query(*, prompt, options):
            for msg in _assistant_tool_use(
                text_after=f"Posted to Slack.\n{STATUS_SUCCESS}"
            ):
                yield msg
            yield _user_tool_result(is_error=False, content='{"ok": false, "error": "missing_scope"}')

        with (
            patch("app.infrastructure.agents.base.query", side_effect=_fake_query),
            pytest.raises(AgentActionError) as exc_info,
        ):
            await run_agent_freeform(agent_name="TestAgent", system_prompt="be helpful", prompt="do it")
        assert "tool call(s) failed" in str(exc_info.value)

    async def test_raises_when_status_line_is_missing_entirely(self):
        async def _fake_query(*, prompt, options):
            for msg in _assistant_tool_use(text_after="I think that worked."):
                yield msg
            yield _user_tool_result(is_error=False)

        with (
            patch("app.infrastructure.agents.base.query", side_effect=_fake_query),
            pytest.raises(AgentActionError),
        ):
            await run_agent_freeform(agent_name="TestAgent", system_prompt="be helpful", prompt="do it")

    async def test_raises_when_a_required_tool_never_fired_even_though_another_did(self):
        """Regression test: an agent whose job is two actions (e.g. post to
        Slack AND file a GitHub issue) could previously satisfy "at least
        one tool call happened" by doing only the first, then simply
        asserting STATUS: SUCCESS. required_tools is checked against the
        actual trace, independent of what the model claims."""

        async def _fake_query(*, prompt, options):
            for msg in _assistant_tool_use(
                name="mcp__slack__slack_post_message", text_after=f"Posted to Slack.\n{STATUS_SUCCESS}"
            ):
                yield msg
            yield _user_tool_result(is_error=False)

        with (
            patch("app.infrastructure.agents.base.query", side_effect=_fake_query),
            pytest.raises(AgentActionError) as exc_info,
        ):
            await run_agent_freeform(
                agent_name="TestAgent",
                system_prompt="be helpful",
                prompt="do it",
                required_tools=["mcp__slack__slack_post_message", "mcp__github__create_issue"],
            )
        assert "mcp__github__create_issue" in str(exc_info.value)
        assert exc_info.value.missing_tools == ["mcp__github__create_issue"]

    async def test_succeeds_when_all_required_tools_fired(self):
        async def _fake_query(*, prompt, options):
            yield AssistantMessage(
                content=[
                    ToolUseBlock(id="tu_1", name="mcp__slack__slack_post_message", input={}),
                    ToolUseBlock(id="tu_2", name="mcp__github__create_issue", input={}),
                ],
                model="claude-test",
            )
            yield _user_tool_result(is_error=False)
            yield _assistant_text(f"Done.\n{STATUS_SUCCESS}")

        with patch("app.infrastructure.agents.base.query", side_effect=_fake_query):
            result = await run_agent_freeform(
                agent_name="TestAgent",
                system_prompt="be helpful",
                prompt="do it",
                required_tools=["mcp__slack__slack_post_message", "mcp__github__create_issue"],
            )
        assert result == "Done."
