"""GET /result/{scan_id}: one finished check, for the page linked from the follow-up text."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api import result_store
from api.schema import ScanResult

router = APIRouter()


@router.get("/result/{scan_id}", response_model=ScanResult)
def get_result(scan_id: str) -> ScanResult:
    result = result_store.get(scan_id)
    if result is None:
        raise HTTPException(status_code=404, detail="We couldn't find this check. It may have expired.")
    return result
