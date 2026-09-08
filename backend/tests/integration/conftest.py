import os
from collections.abc import AsyncIterator

import pytest_asyncio
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dependencies import (
    get_action_agent,
    get_checkout_service,
    get_coordinator_service,
    get_db_session,
    get_payment_gateway,
    get_research_agent,
    get_synthesis_agent,
    get_triage_agent,
)
from app.domain.entities import CaseSource
from app.domain.gateways import PaymentGateway
from app.domain.services import CheckoutService, CoordinatorService
from app.infrastructure.agents import (
    StubActionAgent,
    StubResearchAgent,
    StubSynthesisAgent,
    StubTriageAgent,
)
from app.infrastructure.db import session as db_session
from app.infrastructure.payments.stub_gateway import StubPaymentGateway
from app.infrastructure.repositories import (
    SqlAlchemyCaseEventsRepository,
    SqlAlchemyCasesRepository,
)
from app.main import app

# docker-compose (and CI) run a second, disposable Postgres on 5433 for this.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://casework:casework@localhost:5433/casework_test"
)
_TEST_DATABASE_ASYNC_URL = TEST_DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest_asyncio.fixture
async def test_sessionmaker():
    # Function-scoped (not session-scoped) deliberately: pytest-asyncio gives
    # each test function its own event loop by default, and an async engine
    # opened on one loop deadlocks if reused from another.
    engine = create_async_engine(_TEST_DATABASE_ASYNC_URL)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    db_session.set_sessionmaker(sessionmaker)
    yield sessionmaker
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_sessionmaker) -> AsyncIterator[AsyncSession]:
    async with test_sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def cases_repo(test_session):
    return SqlAlchemyCasesRepository(test_session)


@pytest_asyncio.fixture
async def case_events_repo(test_session):
    return SqlAlchemyCaseEventsRepository(test_session)


def _checkout_service_tagged_for_tests(
    coordinator: CoordinatorService = Depends(get_coordinator_service),
    payment_gateway: PaymentGateway = Depends(get_payment_gateway),
) -> CheckoutService:
    # Tagging cases as `integration_test` (instead of the real `live_stripe`
    # a production checkout would use) is what lets the teardown below clean
    # up safely without ever touching rows a manual local dev session made.
    return CheckoutService(coordinator, payment_gateway, source=CaseSource.INTEGRATION_TEST)


@pytest_asyncio.fixture
async def client(test_sessionmaker, test_session):
    async def override_get_db_session():
        async with test_sessionmaker() as session:
            yield session

    # Phase 1: these are already stubs, but overriding them here exercises
    # the same dependency-override seam Phase 2's real SDK-backed agents
    # will use, so this fixture won't need to change later.
    app.dependency_overrides[get_db_session] = override_get_db_session
    app.dependency_overrides[get_triage_agent] = lambda: StubTriageAgent()
    app.dependency_overrides[get_research_agent] = lambda: StubResearchAgent()
    app.dependency_overrides[get_synthesis_agent] = lambda: StubSynthesisAgent()
    app.dependency_overrides[get_action_agent] = lambda: StubActionAgent()
    app.dependency_overrides[get_payment_gateway] = lambda: StubPaymentGateway()
    app.dependency_overrides[get_checkout_service] = _checkout_service_tagged_for_tests

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()

    # Cleanup keys off the `source` column, not a signal_id naming
    # convention: `list_pending()` deliberately does NOT exclude
    # `integration_test` (tests need their own fixtures to show up
    # in the real queue endpoint), so `source` alone can't double as
    # a "hide this from queries" flag the way `eval` does.
    await test_session.execute(
        text(
            "DELETE FROM case_events WHERE case_id IN "
            "(SELECT case_id FROM cases WHERE source = 'integration_test')"
        )
    )
    await test_session.execute(text("DELETE FROM cases WHERE source = 'integration_test'"))
    await test_session.execute(text("DELETE FROM signals_log WHERE source = 'integration_test'"))
    await test_session.commit()
