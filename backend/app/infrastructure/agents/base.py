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


STATUS_SUCCESS = "STATUS: SUCCESS"
STATUS_FAILED = "STATUS: FAILED"


class AgentActionError(Exception):
    """Raised when a freeform (tool-side-effect) agent call didn't actually
    complete: it never invoked any tool at all, a tool call itself came back
    as an MCP-level error, a required tool was never called even though
    some *other* tool was, or the agent's own final status line says
    STATUS: FAILED (or omits the marker entirely).

    The status-line case is doing real work here, not just belt-and-
    suspenders: a tool can be called and return a completely well-formed
    MCP result that is nonetheless a failure at the *application* level --
    e.g. Slack's API answering a `slack_list_channels` call with a normal
    (non-error) response body of `{"ok": false, "error": "missing_scope"}`.
    Verified this the hard way too: the model correctly read that response,
    correctly declined to guess a channel ID, and correctly explained the
    blocker in its text -- but because a tool call *had* happened with no
    MCP-level error, nothing here would previously have caught that this
    was still a failure, and the caller (CoordinatorService) went on to log
    a NOTIFIED case event for a message that was never sent. Requiring an
    explicit, checkable STATUS: SUCCESS line -- never inferred from prose --
    closes that gap without having to parse Slack- or GitHub-specific error
    shapes in generic agent infrastructure.

    The missing-required-tool case closes a related but distinct gap: an
    agent whose job is two actions (e.g. post to Slack AND file a GitHub
    issue) could previously satisfy "at least one tool call happened" by
    doing only the first and then simply asserting STATUS: SUCCESS -- the
    model's self-report was the only thing standing between "did some of
    the job" and "recorded as fully executed". `required_tools` is checked
    against the actual tool-call trace, independent of anything the model
    says about itself."""

    def __init__(
        self,
        agent_name: str,
        text: str,
        tool_calls: list[str],
        tool_errors: list[str],
        missing_tools: list[str] | None = None,
    ):
        if not tool_calls:
            message = f"{agent_name} claimed to act but never called any tool"
        elif tool_errors:
            message = f"{agent_name}'s tool call(s) failed: {tool_errors}"
        elif missing_tools:
            message = f"{agent_name} never called required tool(s) {missing_tools} (called: {tool_calls})"
        else:
            message = f"{agent_name} did not confirm success: {text[:500]}"
        super().__init__(message)
        self.agent_name = agent_name
        self.text = text
        self.tool_calls = tool_calls
        self.tool_errors = tool_errors
        self.missing_tools = missing_tools or []


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


def _tool_result_indicates_failure(content: object) -> bool:
    if isinstance(content, str):
        stripped = content.strip()
        if not stripped:
            return False
        try:
            content = json.loads(stripped)
        except json.JSONDecodeError:
            return False
    if isinstance(content, list):
        return any(_tool_result_indicates_failure(item) for item in content)
    if isinstance(content, dict):
        if content.get("ok") is False or content.get("success") is False:
            return True
        status = content.get("status")
        if isinstance(status, str) and status.lower() in {"error", "failed", "failure"}:
            return True
    return False


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
                if isinstance(block, ToolResultBlock) and (
                    block.is_error or _tool_result_indicates_failure(block.content)
                ):
                    tool_errors.append(str(block.content))
    return _SessionResult(text="".join(text_parts), tool_calls=tool_calls, tool_errors=tool_errors)


async def run_agent_freeform(
    *,
    agent_name: str,
    system_prompt: str,
    prompt: str,
    mcp_servers: dict[str, McpServerConfig] | None = None,
    allowed_tools: list[str] | None = None,
    required_tools: list[str] | None = None,
    model: str | None = None,
) -> str:
    """For agents whose real job is a tool side-effect (posting to Slack,
    filing a GitHub issue) rather than producing structured data. The
    caller's system_prompt MUST require the response to end with exactly
    one line reading "STATUS: SUCCESS" if -- and only if -- the required
    tool action(s) actually completed, or "STATUS: FAILED" otherwise.
    `required_tools` names every tool that must appear in the actual
    tool-call trace for the job to count as done (e.g. execute() requires
    both the Slack-post and the GitHub-issue tools) -- checked independently
    of anything the model claims about itself.

    Raises AgentActionError if no tool was actually called, a tool call
    came back as an MCP-level error, a name in `required_tools` never
    appears in the trace, or the response's own status line is STATUS:
    FAILED or missing -- the model's prose is never trusted as proof an
    action happened; only the actual tool-call trace *and* an explicit
    checkable success marker are. On success, returns the response text
    with that status line stripped off."""
    result = await _run_once(
        system_prompt=system_prompt,
        prompt=prompt,
        mcp_servers=mcp_servers or {},
        allowed_tools=allowed_tools or [],
        model=model,
    )
    if not result.tool_calls or result.tool_errors:
        raise AgentActionError(agent_name, result.text, result.tool_calls, result.tool_errors)

    missing_tools = [t for t in (required_tools or []) if t not in result.tool_calls]
    if missing_tools:
        raise AgentActionError(
            agent_name, result.text, result.tool_calls, result.tool_errors, missing_tools=missing_tools
        )

    text = result.text.strip()
    lines = text.splitlines()
    last_line = lines[-1].strip() if lines else ""
    if last_line != STATUS_SUCCESS:
        raise AgentActionError(agent_name, text, result.tool_calls, result.tool_errors)
    return "\n".join(lines[:-1]).strip()


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
