# Casework

A multi-agent fraud-signal triage system: five coordinated agents that pick up where a bank's existing real-time fraud-scoring layer leaves off, research an already-flagged alert, draft a recommendation, and — only with a human in the loop — act on it against real payments infrastructure.

See `casework-spec.md` for the full design.

Stack: Claude Agent SDK + MCP · Stripe test mode · FastAPI (Python) · SQLAlchemy · Postgres · React + Vite + TypeScript.

> This README is a work in progress — the "why I built this," demo, and eval summary land in Phase 3 of the build plan once there's a recorded demo and a real eval report to point to.

## Backend architecture

The backend follows a domain-driven, dependency-inverted layout:

- `domain/entities/` — Pydantic domain objects (the base DTOs that flow router → service → repository)
- `domain/repositories/`, `domain/agents/` — `Protocol` ports; domain services depend on these abstractions, never on a concrete implementation
- `domain/services/` — orchestration and business logic (`CoordinatorService` owns the deterministic escalation rules)
- `infrastructure/db/`, `infrastructure/repositories/`, `infrastructure/agents/` — concrete SQLAlchemy and (Phase 1) stub-agent adapters implementing those ports
- `api/` — FastAPI routes and the composition root (`api/dependencies.py`) that wires concrete adapters to the ports routes and services depend on

## Database schema

`db/schema.sql` is hand-written DDL and is the source of truth for the database schema — it's applied directly via `docker-compose`'s init scripts, in CI, and by `scripts/init_db.sh`. The SQLAlchemy models under `backend/app/infrastructure/db/models/` are a query/persistence layer over that schema, not a migration tool, so the two are kept in sync by hand.

That's a deliberate simplification for a project this size (5 tables, changing rarely). **In production, use Alembic** to autogenerate migrations from the SQLAlchemy models instead, so the models become the single source of truth and versioned migration scripts take over `schema.sql`'s job.
