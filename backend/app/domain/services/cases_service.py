from uuid import UUID

from app.domain.agents import ActionAgent
from app.domain.entities import Case, CaseEvent, CaseEventType, CaseStatus, Resolution
from app.domain.gateways import PaymentGateway
from app.domain.repositories import CaseEventsRepository, CasesRepository


class CaseNotFoundError(Exception):
    def __init__(self, case_id: UUID):
        super().__init__(f"No case with id {case_id}")


class CaseAlreadyResolvedError(Exception):
    def __init__(self, case_id: UUID, resolution: Resolution):
        super().__init__(f"Case {case_id} is already resolved ({resolution.value})")


def _should_cancel(case: Case, *, approved: bool) -> bool:
    """The capture-vs-cancel call is made deterministically here, never
    delegated to an LLM: approving a "block" recommendation means the
    analyst agrees this is fraud (cancel the hold); denying a "block"
    recommendation means the analyst disagrees (let it through, capture).
    The same logic mirrors for every other recommended_action, where
    approving means "yes, let it go through" and denying means "no, I
    think this is fraud after all"."""
    is_block_recommendation = case.recommended_action == "block"
    return is_block_recommendation if approved else not is_block_recommendation


class CasesService:
    """Translates between the routers (Request/Response DTOs, handled only
    there) and the CasesRepository/ActionAgent/PaymentGateway Protocols:
    this service only ever sees the base DTO (app.domain.entities.Case) and
    depends on abstractions, never on the concrete SQLAlchemy repository or
    Phase 1 stub agent directly."""

    def __init__(
        self,
        cases_repo: CasesRepository,
        case_events_repo: CaseEventsRepository,
        action_agent: ActionAgent,
        payment_gateway: PaymentGateway,
    ):
        self._cases_repo = cases_repo
        self._case_events_repo = case_events_repo
        self._action_agent = action_agent
        self._payment_gateway = payment_gateway

    async def list_pending(self) -> list[Case]:
        return await self._cases_repo.list_pending()

    async def _get_unresolved(self, case_id: UUID) -> Case:
        case = await self._cases_repo.get(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        if case.resolution != Resolution.NONE:
            raise CaseAlreadyResolvedError(case_id, case.resolution)
        return case

    async def _resolve_payment(self, case: Case, *, approved: bool) -> None:
        # Synthetic/eval/bulk cases never have a real PaymentIntent attached.
        if not case.stripe_payment_intent_id:
            return
        if _should_cancel(case, approved=approved):
            await self._payment_gateway.cancel(case.stripe_payment_intent_id)
            event_type = CaseEventType.PAYMENT_CANCELLED
        else:
            await self._payment_gateway.capture(case.stripe_payment_intent_id)
            event_type = CaseEventType.PAYMENT_CAPTURED
        await self._case_events_repo.log(
            CaseEvent(
                case_id=case.case_id,
                event_type=event_type.value,
                event_payload={"payment_intent_id": case.stripe_payment_intent_id},
            )
        )

    async def approve(self, case_id: UUID, approved_by: str) -> Case:
        case = await self._get_unresolved(case_id)

        await self._resolve_payment(case, approved=True)
        action_result = await self._action_agent.execute(case, approved_by)

        updated = await self._cases_repo.update_resolution(
            case_id,
            resolution=Resolution.APPROVED,
            status=CaseStatus.CLOSED,
            approved_by=approved_by,
        )
        await self._case_events_repo.log(
            CaseEvent(case_id=case_id, event_type=CaseEventType.APPROVED.value, event_payload={"approved_by": approved_by})
        )
        await self._case_events_repo.log(
            CaseEvent(
                case_id=case_id,
                event_type=CaseEventType.ACTION_EXECUTED.value,
                event_payload=action_result.model_dump(mode="json"),
            )
        )
        return updated

    async def deny(self, case_id: UUID, denied_by: str) -> Case:
        case = await self._get_unresolved(case_id)

        await self._resolve_payment(case, approved=False)

        updated = await self._cases_repo.update_resolution(
            case_id,
            resolution=Resolution.DENIED,
            status=CaseStatus.CLOSED,
            approved_by=None,
        )
        await self._case_events_repo.log(
            CaseEvent(case_id=case_id, event_type=CaseEventType.DENIED.value, event_payload={"denied_by": denied_by})
        )
        return updated
