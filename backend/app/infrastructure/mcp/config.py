"""Builders for the external MCP servers the agent adapters use. Each
returns a stdio server config the Claude Agent SDK spawns as a subprocess
for the lifetime of one agent call -- nothing here is shared or long-lived.
Which of these an agent actually gets wired into its
ClaudeAgentOptions.mcp_servers is the real security boundary (see each
adapter in app/infrastructure/agents/); this module only builds the configs.

No Stripe MCP server here: Casework only ever authorizes/captures/cancels
PaymentIntents through the deterministic PaymentGateway port (see
app.domain.gateways.payment_gateway), never through an agent tool call --
there's no scenario where an LLM should be deciding whether money moves.
"""

from claude_agent_sdk.types import McpStdioServerConfig

from app.config import Settings


def postgres_mcp_server(settings: Settings) -> McpStdioServerConfig:
    """Read-only Postgres access for the Research Agent, via postgres-mcp
    (crystaldba/postgres-mcp) run through uvx.

    `--access-mode=restricted` wraps every query in a READ ONLY transaction
    and rejects commit/rollback statements -- the original
    @modelcontextprotocol/server-postgres reference server was archived
    over exactly this kind of SQL-injection gap in its read-only wrapper,
    so this is deliberate defense in depth alongside the allowed_tools
    scoping applied in the ResearchAgent adapter itself.

    `mcp<2` is pinned because the published postgres-mcp release still
    targets the pre-2.0 `mcp` Python SDK (FastMCP); mcp 2.x renamed/
    reworked that API and postgres-mcp fails to import against it --
    verified by actually running it against mcp 2.1.1 vs. mcp<2.
    """
    return McpStdioServerConfig(
        type="stdio",
        command="uvx",
        args=["--with", "mcp<2", "postgres-mcp", "--access-mode=restricted"],
        env={"DATABASE_URI": settings.db_dsn},
    )


def slack_mcp_server(settings: Settings) -> McpStdioServerConfig:
    """Slack posting for the Action Agent's notify() (critical-path
    pre-approval prompt) and execute() (post-approval summary) calls.

    Uses the real @modelcontextprotocol/server-slack package -- an earlier
    version of this pointed at @slack/mcp-server, which doesn't exist on
    the npm registry at all (confirmed via `npm view`, 404); that typo
    made the server fail to start silently, and the agent went on to
    hallucinate a successful post anyway. SLACK_TEAM_ID is not optional:
    the server's own README lists it as required alongside
    SLACK_BOT_TOKEN.
    """
    return McpStdioServerConfig(
        type="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-slack"],
        env={
            "SLACK_BOT_TOKEN": settings.slack_bot_token,
            "SLACK_TEAM_ID": settings.slack_team_id,
        },
    )


def github_mcp_server(settings: Settings) -> McpStdioServerConfig:
    """GitHub Issues for the Action Agent's execute() call -- the spec's
    stand-in case-management system, one issue per approved case."""
    return McpStdioServerConfig(
        type="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": settings.github_pat},
    )


