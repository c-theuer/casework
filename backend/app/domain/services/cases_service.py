import logging
from typing import NoReturn
from uuid import UUID

from app.domain.agents import ActionAgent
from app.domain.entities import Case, CaseEvent, CaseEventType, CaseStatus, Resolution
from app.domain.gateways import PaymentGateway
from app.domain.repositories import CaseEventsRepository, CasesRepository

logger = logging.getLogger(__name__)


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

    async def _log_case_event_best_effort(self, event: CaseEvent) -> None:
        try:
            await self._case_events_repo.log(event)
        except Exception:
            logger.exception(
                "best-effort case_events write failed",
                extra={"case_id": str(event.case_id), "event_type": event.event_type},
            )

    async def _claim_resolution(
        self, case_id: UUID, *, resolution: Resolution, approved_by: str | None
    ) -> Case:
        claimed = await self._cases_repo.update_resolution(
            case_id,
            resolution=resolution,
            status=CaseStatus.ERROR,
            approved_by=approved_by,
        )
        if claimed is not None:
            return claimed

        logger.info(
            "resolution claim rejected by atomic update; diagnosing why",
            extra={"case_id": str(case_id), "resolution": resolution.value},
        )
        case = await self._cases_repo.get(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        if case.status == CaseStatus.ERROR and case.resolution == resolution:
            if resolution == Resolution.APPROVED and case.approved_by != approved_by:
                raise CaseAlreadyResolvedError(case_id, case.resolution)
            return case
        if case.resolution != Resolution.NONE:
            raise CaseAlreadyResolvedError(case_id, case.resolution)
        raise CaseNotActionableError(case_id, case.status)

    async def _close_resolved_case(self, case_id: UUID, *, resolution: Resolution) -> Case:
        closed = await self._cases_repo.update_status(
            case_id,
            current_statuses=(CaseStatus.ERROR,),
            new_status=CaseStatus.CLOSED,
            current_resolution=resolution,
        )
        if closed is not None:
            return closed
        await self._diagnose_resolution_failure(case_id)

    async def _resolve_payment(self, case: Case, *, approved: bool) -> CaseEvent | None:
        # Synthetic/eval/bulk cases never have a real PaymentIntent attached.
        if not case.stripe_payment_intent_id:
            return None
        expected_status = "canceled" if _should_cancel(case, approved=approved) else "succeeded"
        current_status = await self._payment_gateway.get_status(case.stripe_payment_intent_id)
        if current_status == expected_status:
            event_type = (
                CaseEventType.PAYMENT_CANCELLED if expected_status == "canceled" else CaseEventType.PAYMENT_CAPTURED
            )
            logger.info(
                "payment already in expected terminal status; skipping capture/cancel call",
                extra={
                    "case_id": str(case.case_id),
                    "payment_intent_id": case.stripe_payment_intent_id,
                    "status": current_status,
                },
            )
            return CaseEvent(
                case_id=case.case_id,
                event_type=event_type.value,
                event_payload={"payment_intent_id": case.stripe_payment_intent_id},
            )
        if current_status != "requires_capture":
            raise RuntimeError(
                f"PaymentIntent {case.stripe_payment_intent_id} is in unexpected status {current_status!r}"
            )
        if _should_cancel(case, approved=approved):
            await self._payment_gateway.cancel(case.stripe_payment_intent_id)
            event_type = CaseEventType.PAYMENT_CANCELLED
        else:
            await self._payment_gateway.capture(case.stripe_payment_intent_id)
            event_type = CaseEventType.PAYMENT_CAPTURED
        logger.info(
            "payment resolved",
            extra={
                "case_id": str(case.case_id),
                "payment_intent_id": case.stripe_payment_intent_id,
                "event_type": event_type.value,
            },
        )
        return CaseEvent(
            case_id=case.case_id,
            event_type=event_type.value,
            event_payload={"payment_intent_id": case.stripe_payment_intent_id},
        )

    async def approve(self, case_id: UUID, approved_by: str) -> Case:
        claimed = await self._claim_resolution(
            case_id, resolution=Resolution.APPROVED, approved_by=approved_by
        )
        payment_event = await self._resolve_payment(claimed, approved=True)
        updated = await self._close_resolved_case(case_id, resolution=Resolution.APPROVED)
        await self._log_case_event_best_effort(
            CaseEvent(
                case_id=case_id,
                event_type=CaseEventType.APPROVED.value,
                event_payload={"approved_by": approved_by},
            )
        )
        if payment_event is not None:
            await self._log_case_event_best_effort(payment_event)

        try:
            action_result = await self._action_agent.execute(updated, approved_by)
            await self._log_case_event_best_effort(
                CaseEvent(
                    case_id=case_id,
                    event_type=CaseEventType.ACTION_EXECUTED.value,
                    event_payload=action_result.model_dump(mode="json"),
                )
            )
        except Exception as exc:
            logger.exception(
                "case action execution failed",
                extra={"case_id": str(case_id), "approved_by": approved_by},
            )
            await self._log_case_event_best_effort(
                CaseEvent(
                    case_id=case_id,
                    event_type=CaseEventType.ERROR.value,
                    event_payload={"stage": "execute", "error": str(exc)},
                )
            )

        return updated

    async def deny(self, case_id: UUID, denied_by: str) -> Case:
        claimed = await self._claim_resolution(
            case_id, resolution=Resolution.DENIED, approved_by=None
        )
        payment_event = await self._resolve_payment(claimed, approved=False)
        updated = await self._close_resolved_case(case_id, resolution=Resolution.DENIED)
        await self._log_case_event_best_effort(
            CaseEvent(
                case_id=case_id,
                event_type=CaseEventType.DENIED.value,
                event_payload={"denied_by": denied_by},
            )
        )
        if payment_event is not None:
            await self._log_case_event_best_effort(payment_event)

        return updated
