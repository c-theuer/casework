from typing import NoReturn
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
        self.case_id = case_id
        self.resolution = resolution


class CaseNotActionableError(Exception):
    """Raised when a case's resolution is still NONE but its status isn't
    one a human is ever meant to approve/deny -- e.g. a low-route case
    CheckoutService already auto-closed and auto-captured on its own.
    Without this, the case's PaymentIntent (already captured) could be
    handed to _resolve_payment a second time."""

    def __init__(self, case_id: UUID, status: CaseStatus):
        super().__init__(f"Case {case_id} is not awaiting review (status={status.value})")
        self.case_id = case_id
        self.status = status


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

    async def _diagnose_resolution_failure(self, case_id: UUID) -> NoReturn:
        """Called only after CasesRepository.update_resolution() has already
        returned None for this case_id -- classifies why, for the right
        HTTP status, without ever gating the write on this read (that would
        reintroduce the check-then-act race the atomic update exists to
        avoid)."""
        case = await self._cases_repo.get(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        if case.resolution != Resolution.NONE:
            raise CaseAlreadyResolvedError(case_id, case.resolution)
        raise CaseNotActionableError(case_id, case.status)

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
        # Claim first: an atomic, conditional UPDATE (resolution=none AND a
        # reviewable status) is both the concurrency guard -- two concurrent
        # approve()/deny() calls for the same case can never both win -- and
        # what makes a retry safe: once claimed, a second call for the same
        # case_id fails fast here with CaseAlreadyResolvedError, before ever
        # reaching _resolve_payment again. Only the winner proceeds to
        # payment and action side effects.
        updated = await self._cases_repo.update_resolution(
            case_id, resolution=Resolution.APPROVED, status=CaseStatus.CLOSED, approved_by=approved_by
        )
        if updated is None:
            await self._diagnose_resolution_failure(case_id)

        await self._case_events_repo.log(
            CaseEvent(case_id=case_id, event_type=CaseEventType.APPROVED.value, event_payload={"approved_by": approved_by})
        )

        # Payment is the part that must succeed -- real money -- and the
        # case's own resolution is already durable at this point. Slack/
        # GitHub notification is best-effort audit trail on top of that.
        await self._resolve_payment(updated, approved=True)

        try:
            action_result = await self._action_agent.execute(updated, approved_by)
            await self._case_events_repo.log(
                CaseEvent(
                    case_id=case_id,
                    event_type=CaseEventType.ACTION_EXECUTED.value,
                    event_payload=action_result.model_dump(mode="json"),
                )
            )
        except Exception as exc:  # noqa: BLE001 -- ActionAgent is a Protocol; record whatever it raises
            await self._case_events_repo.log(
                CaseEvent(
                    case_id=case_id,
                    event_type=CaseEventType.ERROR.value,
                    event_payload={"stage": "execute", "error": str(exc)},
                )
            )

        return updated

    async def deny(self, case_id: UUID, denied_by: str) -> Case:
        updated = await self._cases_repo.update_resolution(
            case_id, resolution=Resolution.DENIED, status=CaseStatus.CLOSED, approved_by=None
        )
        if updated is None:
            await self._diagnose_resolution_failure(case_id)

        await self._case_events_repo.log(
            CaseEvent(case_id=case_id, event_type=CaseEventType.DENIED.value, event_payload={"denied_by": denied_by})
        )

        await self._resolve_payment(updated, approved=False)

        return updated
