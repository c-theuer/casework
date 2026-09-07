from uuid import UUID

from app.domain.agents import ActionAgent
from app.domain.entities import Case, CaseEvent, CaseEventType, CaseStatus, Resolution
from app.domain.repositories import CaseEventsRepository, CasesRepository


class CaseNotFoundError(Exception):
    def __init__(self, case_id: UUID):
        super().__init__(f"No case with id {case_id}")


class CaseAlreadyResolvedError(Exception):
    def __init__(self, case_id: UUID, resolution: Resolution):
        super().__init__(f"Case {case_id} is already resolved ({resolution.value})")


class CasesService:
    """Translates between the routers (Request/Response DTOs, handled only
    there) and the CasesRepository/ActionAgent Protocols: this service only
    ever sees the base DTO (app.domain.entities.Case) and depends on
    abstractions, never on the concrete SQLAlchemy repository or Phase 1
    stub agent directly."""

    def __init__(
        self,
        cases_repo: CasesRepository,
        case_events_repo: CaseEventsRepository,
        action_agent: ActionAgent,
    ):
        self._cases_repo = cases_repo
        self._case_events_repo = case_events_repo
        self._action_agent = action_agent

    async def list_pending(self) -> list[Case]:
        return await self._cases_repo.list_pending()

    async def _get_unresolved(self, case_id: UUID) -> Case:
        case = await self._cases_repo.get(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        if case.resolution != Resolution.NONE:
            raise CaseAlreadyResolvedError(case_id, case.resolution)
        return case

    async def approve(self, case_id: UUID, approved_by: str) -> Case:
        case = await self._get_unresolved(case_id)

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
        await self._get_unresolved(case_id)

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
