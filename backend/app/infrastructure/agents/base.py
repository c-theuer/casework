"""Shared machinery every real (Claude Agent SDK-backed) agent adapter uses:
build a prompt embedding the input payload and the output schema, run one
query() session, extract the final JSON object from the response text, and
validate it against the caller's Pydantic model -- retrying once with the
validation error fed back into the prompt if it fails.

query() is a fresh, one-shot session per call (no cross-call memory), so a
"retry" here is a brand new call whose prompt includes the previous attempt
and why it failed, not a continued conversation.
"""

import json
from dataclasses import dataclass, field

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from claude_agent_sdk.types import McpServerConfig
from pydantic import BaseModel, ValidationError


class AgentOutputError(Exception):
    """Raised when an agent's response never validated against its output
    schema, even after a retry with the validation error fed back."""

    def __init__(self, agent_name: str, raw_text: str, original: Exception):
        super().__init__(f"{agent_name} produced invalid output: {original}")
        self.agent_name = agent_name
        self.raw_text = raw_text
        self.original = original


class AgentActionError(Exception):
    """Raised when a freeform (tool-side-effect) agent call either never
    invoked any tool at all, or a tool call it made came back as an error.

    This exists because a model will confidently narrate a successful
    action in its final text even when the underlying tool call never
    happened or failed outright (verified this the hard way: the Slack MCP
    server failed to start, no tool was ever called, and the model still
    replied "Message posted to #fraud-ops" as if it had). Text output alone
    is not evidence an action occurred -- only a non-error ToolResultBlock
    is."""

    def __init__(self, agent_name: str, text: str, tool_calls: list[str], tool_errors: list[str]):
        if not tool_calls:
            message = f"{agent_name} claimed to act but never called any tool"
        else:
            message = f"{agent_name}'s tool call(s) failed: {tool_errors}"
        super().__init__(message)
        self.agent_name = agent_name
        self.text = text
        self.tool_calls = tool_calls
        self.tool_errors = tool_errors


def _extract_json(text: str) -> dict:
    """Parse the first complete JSON object out of a model's response,
    tolerating a markdown fence or reasoning prose around it. Uses
    raw_decode (not a brace-to-brace slice) so trailing content after the
    object -- which real model output sometimes includes despite explicit
    "no commentary" instructions -- doesn't cause a spurious "Extra data"
    failure: raw_decode stops at the end of the first valid value and
    simply ignores whatever comes after it."""
    start = text.find("{")
    if start == -1:
        raise json.JSONDecodeError("no JSON object found in response", text, 0)
    obj, _ = json.JSONDecoder().raw_decode(text, start)
    return dict(obj)


@dataclass
class _SessionResult:
    text: str
    tool_calls: list[str] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)


async def _run_once(
    *,
    system_prompt: str,
    prompt: str,
    mcp_servers: dict[str, McpServerConfig],
    allowed_tools: list[str],
    model: str | None,
) -> _SessionResult:
    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers=mcp_servers,
        allowed_tools=allowed_tools,
        # No built-in tools (Bash, Read, Write, WebSearch, ...) for any
        # agent -- the only tools reachable are the MCP ones explicitly
        # wired in above, and only the ones named in allowed_tools at that.
        tools=[],
        # Headless: deny anything not pre-approved instead of blocking on a
        # permission prompt nobody is present to answer.
        permission_mode="dontAsk",
        # Isolate this call from whatever this machine's own Claude Code
        # user config happens to have -- without this, a locally-installed
        # plugin's MCP servers leak into the agent's tool list unannounced.
        # Verified this was a real gap, not a theoretical one: a personal
        # Stripe plugin showed up as an available MCP server before this
        # flag was added.
        strict_mcp_config=True,
        model=model,
    )
    text_parts: list[str] = []
    tool_calls: list[str] = []
    tool_errors: list[str] = []
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    tool_calls.append(block.name)
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock) and block.is_error:
                    tool_errors.append(str(block.content))
    return _SessionResult(text="".join(text_parts), tool_calls=tool_calls, tool_errors=tool_errors)


async def run_agent_freeform(
    *,
    agent_name: str,
    system_prompt: str,
    prompt: str,
    mcp_servers: dict[str, McpServerConfig] | None = None,
    allowed_tools: list[str] | None = None,
    model: str | None = None,
) -> str:
    """For agents whose real job is a tool side-effect (posting to Slack,
    filing a GitHub issue, refunding a charge) rather than producing
    structured data. Raises AgentActionError if no tool was actually called
    or a tool call errored -- the model's final text is never trusted as
    proof an action happened, only a successful ToolResultBlock is."""
    result = await _run_once(
        system_prompt=system_prompt,
        prompt=prompt,
        mcp_servers=mcp_servers or {},
        allowed_tools=allowed_tools or [],
        model=model,
    )
    if not result.tool_calls or result.tool_errors:
        raise AgentActionError(agent_name, result.text, result.tool_calls, result.tool_errors)
    return result.text


async def run_agent[ModelT: BaseModel](
    *,
    agent_name: str,
    system_prompt: str,
    input_payload: dict,
    output_model: type[ModelT],
    mcp_servers: dict[str, McpServerConfig] | None = None,
    allowed_tools: list[str] | None = None,
    model: str | None = None,
    max_retries: int = 1,
) -> ModelT:
    schema = output_model.model_json_schema()
    prompt = (
        f"Input:\n{json.dumps(input_payload, default=str)}\n\n"
        "Respond with ONLY a single JSON object matching this schema -- no "
        f"markdown, no commentary, no code fence:\n{json.dumps(schema)}"
    )

    raw_text = ""
    last_error: Exception = AgentOutputError(agent_name, "", RuntimeError("unreachable"))
    for _ in range(max_retries + 1):
        result = await _run_once(
            system_prompt=system_prompt,
            prompt=prompt,
            mcp_servers=mcp_servers or {},
            allowed_tools=allowed_tools or [],
            model=model,
        )
        raw_text = result.text
        try:
            return output_model.model_validate(_extract_json(raw_text))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            prompt = (
                f"{prompt}\n\nYour previous response was:\n{raw_text}\n\n"
                f"That failed validation with this error:\n{exc}\n\n"
                "Try again. Respond with ONLY a single JSON object matching the schema above."
            )

    raise AgentOutputError(agent_name, raw_text, last_error)
