from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.domain.entities import (
    ActionResult,
    Case,
    CaseEventType,
    CaseRecommendation,
    CaseSource,
    CaseStatus,
    ResearchBrief,
    Resolution,
    Route,
    Signal,
    TriageResult,
)
from app.domain.services import CoordinatorError, CoordinatorService, decide_route


def make_triage(pattern="benign", tier="low", confidence=0.1) -> TriageResult:
    return TriageResult(signal_id="sig_1", pattern=pattern, tier=tier, confidence=confidence, entities={})


class TestDecideRoute:
    def test_confidence_exactly_at_low_boundary_is_not_low(self):
        # spec: low requires confidence < 0.4 (strict), so 0.4 itself falls through
        assert decide_route(make_triage(pattern="card_testing", confidence=0.4)) == Route.ELEVATED

    def test_confidence_just_below_low_boundary_is_low(self):
        assert decide_route(make_triage(pattern="card_testing", confidence=0.39999)) == Route.LOW

    def test_benign_pattern_is_always_low_regardless_of_confidence(self):
        assert decide_route(make_triage(pattern="benign", confidence=0.99)) == Route.LOW

    def test_confidence_exactly_at_critical_boundary_is_not_critical(self):
        # spec: critical requires confidence > 0.85 (strict), so 0.85 itself falls through
        assert decide_route(make_triage(pattern="card_testing", confidence=0.85)) == Route.ELEVATED

    def test_confidence_just_above_critical_boundary_with_matching_pattern_is_critical(self):
        assert decide_route(make_triage(pattern="card_testing", confidence=0.8501)) == Route.CRITICAL
        assert decide_route(make_triage(pattern="account_takeover", confidence=0.9)) == Route.CRITICAL

    def test_high_confidence_with_non_critical_pattern_is_elevated_not_critical(self):
        assert decide_route(make_triage(pattern="merchant_fraud", confidence=0.99)) == Route.ELEVATED


def make_signal(**overrides) -> Signal:
    defaults = dict(
        signal_id="sig_1",
        signal_type="transaction",
        occurred_at=datetime.now(UTC),
        account_id="acct_1",
        upstream_score=0.6,
        flag_reason="ml_score_0.60",
        payload={"amount": 50.0, "device_context": "known_device"},
    )
    defaults.update(overrides)
    return Signal(**defaults)


def make_returned_case(**overrides) -> Case:
    """Stand-in for what the CasesRepository Protocol's create() hands back
    in production: a fully-populated base DTO (as if just converted from a
    freshly committed row). Mocked repos in these tests return this
    directly, since CoordinatorService does no ORM<->DTO conversion itself
    -- that lives inside the concrete SqlAlchemyCasesRepository adapter."""
    now = datetime.now(UTC)
    defaults = dict(
        case_id=uuid4(),
        signal_id="sig_1",
        account_id="acct_1",
        signal_type="transaction",
        occurred_at=now,
        upstream_score=0.6,
        flag_reason="ml_score_0.60",
        payload={},
        status=CaseStatus.PENDING_REVIEW,
        resolution=Resolution.NONE,
        source=CaseSource.EVAL,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Case(**defaults)


def make_coordinator(**overrides) -> tuple[CoordinatorService, dict]:
    """Mocks stand in for the CasesRepository/CaseEventsRepository/
    SignalsLogRepository/TriageAgent/ResearchAgent/SynthesisAgent/
    ActionAgent Protocols -- AsyncMock duck-types against any Protocol
    without needing to subclass it, since Protocols are structural."""
    mocks = dict(
        cases_repo=AsyncMock(),
        case_events_repo=AsyncMock(),
        signals_log_repo=AsyncMock(),
        triage_agent=AsyncMock(),
        research_agent=AsyncMock(),
        synthesis_agent=AsyncMock(),
        action_agent=AsyncMock(),
    )
    mocks.update(overrides)
    mocks["signals_log_repo"].count_recent.return_value = 0
    coordinator = CoordinatorService(**mocks)
    return coordinator, mocks


def logged_events(case_events_repo_mock) -> list:
    """CaseEventsRepository.log() takes one CaseEvent DTO argument instead
    of three loose (case_id, event_type, payload) args."""
    return [call.args[0] for call in case_events_repo_mock.log.call_args_list]


@pytest.mark.asyncio
class TestCoordinatorServiceHandleSignal:
    async def test_low_route_skips_research_and_synthesis_entirely(self):
        coordinator, mocks = make_coordinator()
        mocks["triage_agent"].run.return_value = make_triage(pattern="benign", confidence=0.1)
        returned_case = make_returned_case(status=CaseStatus.CLOSED)
        mocks["cases_repo"].create.return_value = returned_case

        await coordinator.handle_signal(make_signal(), source=CaseSource.EVAL)

        mocks["research_agent"].run.assert_not_called()
        mocks["synthesis_agent"].run.assert_not_called()
        mocks["action_agent"].notify.assert_not_called()
        created_case = mocks["cases_repo"].create.call_args.args[0]
        assert created_case.status == CaseStatus.CLOSED
        assert created_case.route == Route.LOW
        events = logged_events(mocks["case_events_repo"])
        assert any(
            e.case_id == returned_case.case_id and e.event_type == CaseEventType.LOGGED_ONLY.value
            for e in events
        )

    async def test_elevated_route_runs_full_pipeline_without_notifying(self):
        coordinator, mocks = make_coordinator()
        mocks["triage_agent"].run.return_value = make_triage(
            pattern="merchant_fraud", confidence=0.6
        )
        mocks["research_agent"].run.return_value = ResearchBrief(
            signal_id="sig_1", matched_rules=["r1"], similar_cases=[], evidence=["e1"]
        )
        mocks["synthesis_agent"].run.return_value = CaseRecommendation(
            signal_id="sig_1",
            risk_score=0.6,
            recommended_action="flag_for_review",
            draft_note="note",
            requires_human_approval=True,
        )
        mocks["cases_repo"].create.return_value = make_returned_case(status=CaseStatus.PENDING_REVIEW)

        await coordinator.handle_signal(make_signal(), source=CaseSource.EVAL)

        mocks["research_agent"].run.assert_awaited_once()
        mocks["synthesis_agent"].run.assert_awaited_once()
        mocks["action_agent"].notify.assert_not_called()
        created_case = mocks["cases_repo"].create.call_args.args[0]
        assert created_case.status == CaseStatus.PENDING_REVIEW
        assert created_case.recommended_action == "flag_for_review"

    async def test_critical_route_overrides_recommendation_to_block_and_notifies(self):
        coordinator, mocks = make_coordinator()
        mocks["triage_agent"].run.return_value = make_triage(
            pattern="card_testing", confidence=0.9
        )
        mocks["research_agent"].run.return_value = ResearchBrief(
            signal_id="sig_1", matched_rules=[], similar_cases=[], evidence=[]
        )
        # Synthesis disagrees with the deterministic override -- Coordinator
        # must still force "block" and log the mismatch.
        mocks["synthesis_agent"].run.return_value = CaseRecommendation(
            signal_id="sig_1",
            risk_score=0.9,
            recommended_action="monitor",
            draft_note="note",
            requires_human_approval=True,
        )
        mocks["cases_repo"].create.return_value = make_returned_case(
            status=CaseStatus.AUTO_ESCALATED, recommended_action="block"
        )
        mocks["action_agent"].notify.return_value = ActionResult(
            signal_id="sig_1",
            action_taken="notify_fraud_ops",
            executed_by="casework-action-agent",
            approved_by="",
            timestamp=datetime.now(UTC),
        )

        await coordinator.handle_signal(make_signal(), source=CaseSource.LIVE_STRIPE)

        created_case = mocks["cases_repo"].create.call_args.args[0]
        assert created_case.status == CaseStatus.AUTO_ESCALATED
        assert created_case.recommended_action == "block"
        mocks["action_agent"].notify.assert_awaited_once()

        events = logged_events(mocks["case_events_repo"])
        assert any(e.event_type == CaseEventType.ROUTE_RECOMMENDATION_MISMATCH.value for e in events)

    async def test_notify_failure_logs_an_error_event_before_raising(self):
        """The case is already fully persisted by the time notify() runs --
        a failed notification must still leave a record on the case's own
        audit trail, not just surface via the re-raised CoordinatorError to
        whatever called handle_signal()."""
        coordinator, mocks = make_coordinator()
        mocks["triage_agent"].run.return_value = make_triage(pattern="card_testing", confidence=0.9)
        mocks["research_agent"].run.return_value = ResearchBrief(
            signal_id="sig_1", matched_rules=[], similar_cases=[], evidence=[]
        )
        mocks["synthesis_agent"].run.return_value = CaseRecommendation(
            signal_id="sig_1", risk_score=0.9, recommended_action="block",
            draft_note="note", requires_human_approval=True,
        )
        returned_case = make_returned_case(status=CaseStatus.AUTO_ESCALATED, recommended_action="block")
        mocks["cases_repo"].create.return_value = returned_case
        mocks["action_agent"].notify.side_effect = RuntimeError("missing_scope")

        with pytest.raises(CoordinatorError) as exc_info:
            await coordinator.handle_signal(make_signal(), source=CaseSource.LIVE_STRIPE)

        assert exc_info.value.stage == "notify"
        assert exc_info.value.case_id == returned_case.case_id
        events = logged_events(mocks["case_events_repo"])
        error_events = [e for e in events if e.event_type == CaseEventType.ERROR.value]
        assert len(error_events) == 1
        assert error_events[0].case_id == returned_case.case_id
        assert error_events[0].event_payload["stage"] == "notify"
        assert "missing_scope" in error_events[0].event_payload["error"]
        # NOTIFIED must never be logged for a notify() call that raised.
        assert not any(e.event_type == CaseEventType.NOTIFIED.value for e in events)

    async def test_triage_failure_raises_coordinator_error_after_logging_signal(self):
        coordinator, mocks = make_coordinator()
        mocks["triage_agent"].run.side_effect = RuntimeError("boom")

        with pytest.raises(CoordinatorError) as exc_info:
            await coordinator.handle_signal(make_signal(), source=CaseSource.EVAL)

        assert exc_info.value.stage == "triage"
        assert exc_info.value.case_id is None
        mocks["signals_log_repo"].log.assert_awaited_once()
        mocks["cases_repo"].create.assert_not_called()

    async def test_signal_log_failure_raises_coordinator_error_not_a_raw_exception(self):
        """Previously fully unguarded -- a failure here would propagate as
        whatever raw exception type the repository raised, which
        CheckoutService's `except CoordinatorError` can't catch, leaking a
        500 after Stripe has already authorized the card."""
        coordinator, mocks = make_coordinator()
        mocks["signals_log_repo"].log.side_effect = RuntimeError("db unreachable")

        with pytest.raises(CoordinatorError) as exc_info:
            await coordinator.handle_signal(make_signal(), source=CaseSource.EVAL)

        assert exc_info.value.stage == "signal_log"
        assert exc_info.value.case_id is None
        mocks["triage_agent"].run.assert_not_called()

    async def test_persist_failure_raises_coordinator_error_with_no_case_id(self):
        """cases_repo.create() failing means no case exists at all -- the
        caller (CheckoutService) needs case_id=None here specifically to
        know it's safe to cancel the dangling authorization."""
        coordinator, mocks = make_coordinator()
        mocks["triage_agent"].run.return_value = make_triage(pattern="benign", confidence=0.1)
        mocks["cases_repo"].create.side_effect = RuntimeError("db unreachable")

        with pytest.raises(CoordinatorError) as exc_info:
            await coordinator.handle_signal(make_signal(), source=CaseSource.EVAL)

        assert exc_info.value.stage == "persist"
        assert exc_info.value.case_id is None

    async def test_low_route_event_log_failure_raises_coordinator_error_with_case_id(self):
        coordinator, mocks = make_coordinator()
        mocks["triage_agent"].run.return_value = make_triage(pattern="benign", confidence=0.1)
        returned_case = make_returned_case(status=CaseStatus.CLOSED)
        mocks["cases_repo"].create.return_value = returned_case
        mocks["case_events_repo"].log.side_effect = RuntimeError("audit down")

        with pytest.raises(CoordinatorError) as exc_info:
            await coordinator.handle_signal(make_signal(), source=CaseSource.EVAL)

        assert exc_info.value.stage == "logged_only"
        assert exc_info.value.case_id == returned_case.case_id

    async def test_post_persist_event_failure_raises_coordinator_error_with_case_id(self):
        coordinator, mocks = make_coordinator()
        mocks["triage_agent"].run.return_value = make_triage(pattern="merchant_fraud", confidence=0.6)
        mocks["research_agent"].run.return_value = ResearchBrief(
            signal_id="sig_1", matched_rules=["r1"], similar_cases=[], evidence=["e1"]
        )
        mocks["synthesis_agent"].run.return_value = CaseRecommendation(
            signal_id="sig_1",
            risk_score=0.6,
            recommended_action="flag_for_review",
            draft_note="note",
            requires_human_approval=True,
        )
        returned_case = make_returned_case(status=CaseStatus.PENDING_REVIEW)
        mocks["cases_repo"].create.return_value = returned_case
        mocks["case_events_repo"].log.side_effect = [None, None, None, RuntimeError("audit down")]

        with pytest.raises(CoordinatorError) as exc_info:
            await coordinator.handle_signal(make_signal(), source=CaseSource.EVAL)

        assert exc_info.value.stage == "queued_for_review"
        assert exc_info.value.case_id == returned_case.case_id

    async def test_handoff_signal_id_mismatch_logs_a_warning_but_still_persists_the_case(self):
        """A confused/hallucinating model response is a real signal worth
        keeping, but hard-failing the whole pipeline over it would throw
        away otherwise-good triage/research/synthesis work for what is, at
        worst, an audit-trail data-integrity problem -- the persisted Case
        always uses the original signal_id for its own identity regardless."""
        coordinator, mocks = make_coordinator()
        mocks["triage_agent"].run.return_value = make_triage(pattern="merchant_fraud", confidence=0.6)
        mocks["research_agent"].run.return_value = ResearchBrief(
            signal_id="sig_WRONG", matched_rules=[], similar_cases=[], evidence=[]
        )
        mocks["synthesis_agent"].run.return_value = CaseRecommendation(
            signal_id="sig_1", risk_score=0.6, recommended_action="flag_for_review",
            draft_note="note", requires_human_approval=False,
        )
        returned_case = make_returned_case(status=CaseStatus.PENDING_REVIEW)
        mocks["cases_repo"].create.return_value = returned_case

        case = await coordinator.handle_signal(make_signal(), source=CaseSource.EVAL)

        assert case == returned_case
        events = logged_events(mocks["case_events_repo"])
        warning_events = [e for e in events if e.event_type == CaseEventType.HANDOFF_VALIDATION_WARNING.value]
        assert len(warning_events) == 1
        warnings = warning_events[0].event_payload["warnings"]
        assert any("ResearchBrief.signal_id" in w for w in warnings)
        assert any("requires_human_approval" in w for w in warnings)

    async def test_notify_failure_preserves_coordinator_error_when_error_logging_also_fails(self, caplog):
        """Before logging was added, a notify() failure whose own
        case_events audit-trail write ALSO failed left no trace anywhere:
        the CoordinatorError is still raised and caught upstream, but
        nothing durable records why. logger.exception() in
        _log_case_event_best_effort is what closes that gap."""
        caplog.set_level("ERROR")
        coordinator, mocks = make_coordinator()
        mocks["triage_agent"].run.return_value = make_triage(pattern="card_testing", confidence=0.9)
        mocks["research_agent"].run.return_value = ResearchBrief(
            signal_id="sig_1", matched_rules=[], similar_cases=[], evidence=[]
        )
        mocks["synthesis_agent"].run.return_value = CaseRecommendation(
            signal_id="sig_1",
            risk_score=0.9,
            recommended_action="block",
            draft_note="note",
            requires_human_approval=True,
        )
        returned_case = make_returned_case(status=CaseStatus.AUTO_ESCALATED, recommended_action="block")
        mocks["cases_repo"].create.return_value = returned_case
        mocks["action_agent"].notify.side_effect = RuntimeError("missing_scope")
        mocks["case_events_repo"].log.side_effect = [None, None, None, None, RuntimeError("audit down")]

        with pytest.raises(CoordinatorError) as exc_info:
            await coordinator.handle_signal(make_signal(), source=CaseSource.LIVE_STRIPE)

        assert exc_info.value.stage == "notify"
        assert exc_info.value.case_id == returned_case.case_id
        assert "pipeline stage failed" in caplog.text
        assert "missing_scope" in caplog.text
        assert "best-effort case_events write failed" in caplog.text
        assert "audit down" in caplog.text
