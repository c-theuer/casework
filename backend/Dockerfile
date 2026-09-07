FROM python:3.12-slim

# Node/npm is required at runtime: the Claude Agent SDK spawns the Stripe/Slack/
# GitHub/Postgres MCP servers as `npx` stdio subprocesses.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --no-install-project

COPY . .
RUN uv sync

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
