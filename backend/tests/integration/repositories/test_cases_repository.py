from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from app.domain.entities import Case, CaseSource, CaseStatus, Resolution, Route


@pytest_asyncio.fixture(autouse=True)
async def _cleanup(cases_repo):
    yield
    # ON DELETE CASCADE on case_events.case_id takes care of the audit log
    # rows for any case this test created.
    await cases_repo.delete_by_source(CaseSource.INTEGRATION_TEST.value)


def make_case_dto(**overrides) -> Case:
    defaults = dict(
        signal_id=f"sig_repo_it_{uuid4().hex}",
        account_id="acct_repo_it",
        signal_type="transaction",
        occurred_at=datetime.now(UTC),
        upstream_score=0.6,
        flag_reason="ml_score_0.60",
        payload={"amount": 10.0},
        pattern="merchant_fraud",
        triage_tier="elevated",
        confidence=0.6,
        entities={},
        matched_rules=[],
        similar_cases=[],
        evidence=[],
        risk_score=0.6,
        recommended_action="flag_for_review",
        draft_note="draft",
        route=Route.ELEVATED,
        status=CaseStatus.PENDING_REVIEW,
        resolution=Resolution.NONE,
        source=CaseSource.INTEGRATION_TEST,
    )
    defaults.update(overrides)
    return Case(**defaults)


@pytest.mark.asyncio
class TestCasesRepository:
    async def test_create_persists_and_returns_a_fully_populated_case(self, cases_repo):
        case = await cases_repo.create(make_case_dto())

        assert case.case_id is not None
        assert case.status == CaseStatus.PENDING_REVIEW
        assert case.route == Route.ELEVATED
        assert case.resolution == Resolution.NONE
        assert case.created_at is not None

    async def test_get_returns_none_for_unknown_id(self, cases_repo):
        assert await cases_repo.get(uuid4()) is None

    async def test_get_returns_the_created_case(self, cases_repo):
        created = await cases_repo.create(make_case_dto())

        fetched = await cases_repo.get(created.case_id)

        assert fetched is not None
        assert fetched.case_id == created.case_id
        assert fetched.payload == {"amount": 10.0}

    async def test_list_pending_excludes_eval_but_includes_integration_test(self, cases_repo):
        pending = await cases_repo.create(make_case_dto(status=CaseStatus.PENDING_REVIEW))
        eval_case = await cases_repo.create(
            make_case_dto(status=CaseStatus.PENDING_REVIEW, source=CaseSource.EVAL)
        )

        results = await cases_repo.list_pending()

        ids = [c.case_id for c in results]
        assert pending.case_id in ids
        assert eval_case.case_id not in ids

        await cases_repo.delete_by_source("eval")

    async def test_list_pending_includes_both_pending_review_and_auto_escalated(self, cases_repo):
        elevated = await cases_repo.create(make_case_dto(status=CaseStatus.PENDING_REVIEW))
        critical = await cases_repo.create(
            make_case_dto(route=Route.CRITICAL, status=CaseStatus.AUTO_ESCALATED)
        )

        ids = [c.case_id for c in await cases_repo.list_pending()]

        assert elevated.case_id in ids
        assert critical.case_id in ids

    async def test_list_pending_excludes_closed_cases(self, cases_repo):
        closed = await cases_repo.create(make_case_dto(status=CaseStatus.CLOSED))

        ids = [c.case_id for c in await cases_repo.list_pending()]

        assert closed.case_id not in ids

    async def test_update_resolution_persists_status_and_approver(self, cases_repo):
        case = await cases_repo.create(make_case_dto())

        updated = await cases_repo.update_resolution(
            case.case_id,
            resolution=Resolution.APPROVED,
            status=CaseStatus.CLOSED,
            approved_by="analyst_1",
        )

        assert updated.status == CaseStatus.CLOSED
        assert updated.resolution == Resolution.APPROVED
        assert updated.approved_by == "analyst_1"

        refetched = await cases_repo.get(case.case_id)
        assert refetched.status == CaseStatus.CLOSED

    async def test_find_similar_matches_by_account_id_or_pattern(self, cases_repo):
        same_account = await cases_repo.create(
            make_case_dto(account_id="acct_repo_it_shared", pattern="benign")
        )
        same_pattern = await cases_repo.create(
            make_case_dto(account_id="acct_repo_it_other", pattern="merchant_fraud")
        )
        unrelated = await cases_repo.create(
            make_case_dto(account_id="acct_repo_it_unrelated", pattern="benign")
        )

        results = await cases_repo.find_similar(account_id="acct_repo_it_shared", pattern="merchant_fraud")

        ids = [c.case_id for c in results]
        assert same_account.case_id in ids
        assert same_pattern.case_id in ids
        assert unrelated.case_id not in ids

    async def test_delete_by_source_removes_only_matching_rows(self, cases_repo):
        integration_case = await cases_repo.create(make_case_dto())
        eval_case = await cases_repo.create(make_case_dto(source=CaseSource.EVAL))

        await cases_repo.delete_by_source("eval")

        assert await cases_repo.get(eval_case.case_id) is None
        assert await cases_repo.get(integration_case.case_id) is not None
