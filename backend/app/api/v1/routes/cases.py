from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_cases_service
from app.api.schemas import ApproveRequest, DenyRequest
from app.domain.entities import Case
from app.domain.services import CaseAlreadyResolvedError, CaseNotFoundError, CasesService

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[Case])
async def list_cases(
    status: Literal["pending_review"] = "pending_review",
    cases_service: CasesService = Depends(get_cases_service),
) -> list[Case]:
    # Only pending_review is supported for now -- the fraud-ops queue view is
    # the only consumer, per spec §7.
    return await cases_service.list_pending()


@router.post("/{case_id}/approve", response_model=Case)
async def approve_case(
    case_id: UUID,
    request: ApproveRequest,
    cases_service: CasesService = Depends(get_cases_service),
) -> Case:
    try:
        return await cases_service.approve(case_id, request.approved_by)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CaseAlreadyResolvedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{case_id}/deny", response_model=Case)
async def deny_case(
    case_id: UUID,
    request: DenyRequest,
    cases_service: CasesService = Depends(get_cases_service),
) -> Case:
    try:
        return await cases_service.deny(case_id, request.denied_by)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CaseAlreadyResolvedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
