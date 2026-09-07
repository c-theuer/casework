from datetime import UTC, datetime

import pytest

from app.domain.entities import Case


def make_case_dto(**overrides) -> Case:
    defaults = dict(
        signal_id=f"sig_it_{overrides.get('signal_id', 'default')}",
        account_id="acct_it",
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
        route="elevated",
        status="pending_review",
        resolution="none",
        source="integration_test",
    )
    defaults.update(overrides)
    return Case(**defaults)


@pytest.mark.asyncio
class TestCasesEndpoints:
    async def test_list_pending_returns_seeded_case(self, client, cases_repo):
        case = await cases_repo.create(make_case_dto(signal_id="sig_it_list_1"))

        response = await client.get("/cases?status=pending_review")

        assert response.status_code == 200
        ids = [c["case_id"] for c in response.json()]
        assert str(case.case_id) in ids

    async def test_list_pending_includes_auto_escalated_cases(self, client, cases_repo):
        case = await cases_repo.create(
            make_case_dto(
                signal_id="sig_it_critical_1",
                route="critical",
                status="auto_escalated",
                recommended_action="block",
            )
        )

        response = await client.get("/cases?status=pending_review")

        ids = [c["case_id"] for c in response.json()]
        assert str(case.case_id) in ids

    async def test_approve_closes_case_and_removes_it_from_queue(self, client, cases_repo):
        case = await cases_repo.create(make_case_dto(signal_id="sig_it_approve_1"))

        response = await client.post(f"/cases/{case.case_id}/approve", json={"approved_by": "analyst_1"})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "closed"
        assert body["resolution"] == "approved"
        assert body["approved_by"] == "analyst_1"

        queue = await client.get("/cases?status=pending_review")
        assert str(case.case_id) not in [c["case_id"] for c in queue.json()]

    async def test_deny_closes_case_without_approved_by(self, client, cases_repo):
        case = await cases_repo.create(make_case_dto(signal_id="sig_it_deny_1"))

        response = await client.post(f"/cases/{case.case_id}/deny", json={"denied_by": "analyst_1"})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "closed"
        assert body["resolution"] == "denied"
        assert body["approved_by"] is None

    async def test_approve_unknown_case_returns_404(self, client):
        response = await client.post(
            "/cases/00000000-0000-0000-0000-000000000000/approve",
            json={"approved_by": "analyst_1"},
        )
        assert response.status_code == 404

    async def test_approve_already_resolved_case_returns_409(self, client, cases_repo):
        case = await cases_repo.create(make_case_dto(signal_id="sig_it_conflict_1"))
        first = await client.post(f"/cases/{case.case_id}/approve", json={"approved_by": "analyst_1"})
        assert first.status_code == 200

        second = await client.post(f"/cases/{case.case_id}/approve", json={"approved_by": "analyst_2"})
        assert second.status_code == 409
