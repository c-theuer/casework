"""Composition root: this is the one place concrete infrastructure classes
get named. Every factory function below is annotated to return a domain
Protocol -- callers (services, routes) never see the concrete type, only
the abstraction, so swapping an implementation (a real Stripe/Slack/GitHub-
backed agent in Phase 2, a different DB adapter, a fake for tests) means
changing a single `return` line here and nowhere else.
"""

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.agents import ActionAgent, ResearchAgent, SynthesisAgent, TriageAgent
from app.domain.repositories import (
    CaseEventsRepository,
    CasesRepository,
    PersonasRepository,
    RulesRepository,
    SignalsLogRepository,
)
from app.domain.services import CasesService, CheckoutService, CoordinatorService
from app.infrastructure.agents import (
    StubActionAgent,
    StubResearchAgent,
    StubSynthesisAgent,
    StubTriageAgent,
)
from app.infrastructure.db.session import get_sessionmaker
from app.infrastructure.repositories import (
    SqlAlchemyCaseEventsRepository,
    SqlAlchemyCasesRepository,
    SqlAlchemyPersonasRepository,
    SqlAlchemyRulesRepository,
    SqlAlchemySignalsLogRepository,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    # FastAPI caches Depends() results per request, so every repository
    # below that depends on this shares the same session/transaction for the
    # lifetime of one request -- a standard unit-of-work pattern.
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session


def get_cases_repository(session: AsyncSession = Depends(get_db_session)) -> CasesRepository:
    return SqlAlchemyCasesRepository(session)


def get_case_events_repository(session: AsyncSession = Depends(get_db_session)) -> CaseEventsRepository:
    return SqlAlchemyCaseEventsRepository(session)


def get_signals_log_repository(session: AsyncSession = Depends(get_db_session)) -> SignalsLogRepository:
    return SqlAlchemySignalsLogRepository(session)


def get_personas_repository(session: AsyncSession = Depends(get_db_session)) -> PersonasRepository:
    return SqlAlchemyPersonasRepository(session)


def get_rules_repository(session: AsyncSession = Depends(get_db_session)) -> RulesRepository:
    return SqlAlchemyRulesRepository(session)


# Agent adapters have no dependencies of their own in Phase 1. Phase 2 swaps
# each `return` below for a Claude Agent SDK-backed adapter (with MCP
# config, model name, etc.) -- CoordinatorService's constructor, and every
# test that mocks these Protocols, stays untouched.
def get_triage_agent() -> TriageAgent:
    return StubTriageAgent()


def get_research_agent() -> ResearchAgent:
    return StubResearchAgent()


def get_synthesis_agent() -> SynthesisAgent:
    return StubSynthesisAgent()


def get_action_agent() -> ActionAgent:
    return StubActionAgent()


def get_coordinator_service(
    cases_repo: CasesRepository = Depends(get_cases_repository),
    case_events_repo: CaseEventsRepository = Depends(get_case_events_repository),
    signals_log_repo: SignalsLogRepository = Depends(get_signals_log_repository),
    triage_agent: TriageAgent = Depends(get_triage_agent),
    research_agent: ResearchAgent = Depends(get_research_agent),
    synthesis_agent: SynthesisAgent = Depends(get_synthesis_agent),
    action_agent: ActionAgent = Depends(get_action_agent),
) -> CoordinatorService:
    return CoordinatorService(
        cases_repo,
        case_events_repo,
        signals_log_repo,
        triage_agent,
        research_agent,
        synthesis_agent,
        action_agent,
    )


def get_checkout_service(
    coordinator: CoordinatorService = Depends(get_coordinator_service),
) -> CheckoutService:
    return CheckoutService(coordinator)


def get_cases_service(
    cases_repo: CasesRepository = Depends(get_cases_repository),
    case_events_repo: CaseEventsRepository = Depends(get_case_events_repository),
    action_agent: ActionAgent = Depends(get_action_agent),
) -> CasesService:
    return CasesService(cases_repo, case_events_repo, action_agent)
