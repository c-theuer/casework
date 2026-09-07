from app.domain.agents import ActionAgent, ResearchAgent, SynthesisAgent, TriageAgent
from app.domain.entities import (
    Case,
    CaseEvent,
    CaseEventType,
    CaseSource,
    CaseStatus,
    ResearchBrief,
    Route,
    Signal,
    SignalLogEntry,
    TriageResult,
)
from app.domain.repositories import CaseEventsRepository, CasesRepository, SignalsLogRepository


class CoordinatorError(Exception):
    """Raised when the pipeline fails after the signal has already been
    logged. Callers (e.g. CheckoutService) should catch this and still return
    whatever upstream result they already have -- the auth path is
    independent of the investigation queue."""

    def __init__(self, signal_id: str, stage: str, original: Exception):
        super().__init__(f"Coordinator pipeline failed for {signal_id} at stage '{stage}': {original}")
        self.signal_id = signal_id
        self.stage = stage
        self.original = original


def decide_route(triage: TriageResult) -> Route:
    """Pure, deterministic escalation logic -- never an LLM call. Reads the
    model's pattern/confidence directly rather than trusting its own `tier`
    self-label, per spec §9."""
    if triage.confidence < 0.4 or triage.pattern == "benign":
        return Route.LOW
    if triage.confidence > 0.85 and triage.pattern in {"card_testing", "account_takeover"}:
        return Route.CRITICAL
    return Route.ELEVATED


class CoordinatorService:
    """Orchestrates the 5-agent pipeline. Depends only on domain Protocols
    (CasesRepository, CaseEventsRepository, SignalsLogRepository,
    TriageAgent, ResearchAgent, SynthesisAgent, ActionAgent) -- never on a
    concrete infrastructure class. Deals exclusively in base DTOs
    (app.domain.entities); SQLAlchemy is the concrete repository adapters'
    business alone."""

    def __init__(
        self,
        cases_repo: CasesRepository,
        case_events_repo: CaseEventsRepository,
        signals_log_repo: SignalsLogRepository,
        triage_agent: TriageAgent,
        research_agent: ResearchAgent,
        synthesis_agent: SynthesisAgent,
        action_agent: ActionAgent,
    ):
        self._cases_repo = cases_repo
        self._case_events_repo = case_events_repo
        self._signals_log_repo = signals_log_repo
        self._triage_agent = triage_agent
        self._research_agent = research_agent
        self._synthesis_agent = synthesis_agent
        self._action_agent = action_agent

    async def _velocity_context(self, signal: Signal) -> dict:
        device_context = signal.payload.get("device_context")
        recent_txn_count = await self._signals_log_repo.count_recent(
            account_id=signal.account_id, within_minutes=10
        )
        result = {"recent_txn_count_10min": recent_txn_count}
        if device_context:
            result["recent_device_count_10min"] = await self._signals_log_repo.count_recent(
                device_context=device_context, within_minutes=10
            )
        return result

    async def handle_signal(self, signal: Signal, source: CaseSource) -> Case:
        await self._signals_log_repo.log(_signal_to_log_entry(signal, source))

        try:
            velocity_context = await self._velocity_context(signal)
            triage = await self._triage_agent.run(signal, velocity_context)
        except Exception as exc:
            raise CoordinatorError(signal.signal_id, "triage", exc) from exc

        route = decide_route(triage)

        if route == Route.LOW:
            case = await self._cases_repo.create(
                _build_case_dto(signal, triage, route, CaseStatus.CLOSED, source)
            )
            await self._case_events_repo.log(
                CaseEvent(case_id=case.case_id, event_type=CaseEventType.LOGGED_ONLY.value)
            )
            return case

        try:
            research = await self._research_agent.run(triage)
            recommendation = await self._synthesis_agent.run(triage, research)
        except Exception as exc:
            raise CoordinatorError(signal.signal_id, "research_or_synthesis", exc) from exc

        recommended_action = recommendation.recommended_action
        mismatch = route == Route.CRITICAL and recommended_action != "block"
        if route == Route.CRITICAL:
            recommended_action = "block"

        status = CaseStatus.AUTO_ESCALATED if route == Route.CRITICAL else CaseStatus.PENDING_REVIEW

        case = await self._cases_repo.create(
            _build_case_dto(
                signal,
                triage,
                route,
                status,
                source,
                research=research,
                risk_score=recommendation.risk_score,
                recommended_action=recommended_action,
                draft_note=recommendation.draft_note,
            )
        )

        await self._case_events_repo.log(
            CaseEvent(
                case_id=case.case_id, event_type=CaseEventType.TRIAGED.value, event_payload=triage.model_dump()
            )
        )
        await self._case_events_repo.log(
            CaseEvent(
                case_id=case.case_id,
                event_type=CaseEventType.RESEARCHED.value,
                event_payload=research.model_dump(),
            )
        )
        await self._case_events_repo.log(
            CaseEvent(
                case_id=case.case_id,
                event_type=CaseEventType.SYNTHESIZED.value,
                event_payload=recommendation.model_dump(),
            )
        )
        if mismatch:
            await self._case_events_repo.log(
                CaseEvent(
                    case_id=case.case_id,
                    event_type=CaseEventType.ROUTE_RECOMMENDATION_MISMATCH.value,
                    event_payload={
                        "synthesis_recommended": recommendation.recommended_action,
                        "overridden_to": "block",
                    },
                )
            )

        if route == Route.CRITICAL:
            await self._case_events_repo.log(
                CaseEvent(case_id=case.case_id, event_type=CaseEventType.AUTO_ESCALATED.value)
            )
            try:
                action_result = await self._action_agent.notify(case)
                await self._case_events_repo.log(
                    CaseEvent(
                        case_id=case.case_id,
                        event_type=CaseEventType.NOTIFIED.value,
                        event_payload=action_result.model_dump(mode="json"),
                    )
                )
            except Exception as exc:
                raise CoordinatorError(signal.signal_id, "notify", exc) from exc
        else:
            await self._case_events_repo.log(
                CaseEvent(case_id=case.case_id, event_type=CaseEventType.QUEUED_FOR_REVIEW.value)
            )

        return case


def _signal_to_log_entry(signal: Signal, source: CaseSource) -> SignalLogEntry:
    return SignalLogEntry(
        signal_id=signal.signal_id,
        account_id=signal.account_id,
        device_context=signal.payload.get("device_context"),
        geo_context=signal.payload.get("geo_context"),
        signal_type=signal.signal_type,
        occurred_at=signal.occurred_at,
        source=source,
        raw_signal=signal.model_dump(mode="json"),
    )


def _build_case_dto(
    signal: Signal,
    triage: TriageResult,
    route: Route,
    status: CaseStatus,
    source: CaseSource,
    *,
    research: ResearchBrief | None = None,
    risk_score: float | None = None,
    recommended_action: str | None = None,
    draft_note: str | None = None,
) -> Case:
    return Case(
        signal_id=signal.signal_id,
        account_id=signal.account_id,
        signal_type=signal.signal_type,
        occurred_at=signal.occurred_at,
        upstream_score=signal.upstream_score,
        flag_reason=signal.flag_reason,
        payload=signal.payload,
        pattern=triage.pattern,
        triage_tier=triage.tier,
        confidence=triage.confidence,
        entities=triage.entities,
        matched_rules=research.matched_rules if research else None,
        similar_cases=research.similar_cases if research else None,
        evidence=research.evidence if research else None,
        risk_score=risk_score,
        recommended_action=recommended_action,
        draft_note=draft_note,
        route=route,
        status=status,
        source=source,
    )
