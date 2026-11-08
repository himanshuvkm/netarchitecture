from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from io import BytesIO
import logging
import re
from pydantic import ValidationError
from ..schemas.network import NetworkRequest
from ..profiles.catalog import PROFILES
from ..engines.analyze_engine import analyze
from ..engines.media_engine import LinkRequest, recommend_media
from ..engines.vlsm_engine import allocate_vlsm
from ..engines.routing_engine import recommend_routing
from ..engines.config_engine import generate_configs, export_zip

log = logging.getLogger("netarchitect")
router = APIRouter(prefix="/api")

def run_analysis(payload: dict) -> dict:
    try:
        request = NetworkRequest.model_validate(payload)
        return analyze(request.model_dump())
    except (ValidationError, ValueError) as exc:
        detail = exc.errors(include_context=False) if isinstance(exc, ValidationError) else str(exc)
        log.info("Invalid analysis request: %s", detail)
        raise HTTPException(status_code=422, detail={"code":"validation_error","message":"Input validation failed","errors":detail})

@router.get("/health")
def health(): return {"status":"ok","service":"NetArchitect"}

@router.get("/profiles")
def profiles(): return list(PROFILES.values())

@router.get("/profiles/{profile_id}")
def profile(profile_id: str):
    if profile_id not in PROFILES: raise HTTPException(404, detail={"code":"not_found","message":"Unknown profile"})
    return PROFILES[profile_id]

@router.post("/analyze")
def api_analyze(payload: dict): return run_analysis(payload)

@router.post("/validate")
def validate(payload: dict):
    result = run_analysis(payload)
    return {"valid":True,"errors":[],"overlap_valid":result["vlsm"]["overlap_valid"],"warnings":result["warnings"]}

@router.post("/vlsm/allocate")
def vlsm(payload: dict):
    try: return allocate_vlsm(payload["root_cidr"],payload["vlans"],payload.get("reserved_subnets"))
    except (KeyError, ValueError) as exc: raise HTTPException(422,detail={"code":"allocation_error","message":str(exc)})

@router.post("/recommendations/media")
def media(payload: dict):
    try: return recommend_media(LinkRequest(**payload))
    except (TypeError, ValueError) as exc: raise HTTPException(422,detail={"code":"media_error","message":str(exc)})

@router.post("/recommendations/routing")
def routing(payload: dict):
    try: return recommend_routing(**payload)
    except TypeError as exc: raise HTTPException(422,detail={"code":"routing_error","message":str(exc)})

@router.post("/configurations/generate")
def configurations(payload: dict):
    result = run_analysis(payload)
    try: return {"files":generate_configs(result),"warnings":result["warnings"]}
    except ValueError as exc: raise HTTPException(422, detail={"code":"configuration_error","message":str(exc)})

@router.post("/configurations/export")
def export(payload: dict):
    result = run_analysis(payload)
    try: data = export_zip(generate_configs(result))
    except ValueError as exc: raise HTTPException(422, detail={"code":"configuration_error","message":str(exc)})
    filename = re.sub(r"[^a-z0-9_-]", "_", result["network_name"].lower()).strip("_") + "_configs.zip"
    return StreamingResponse(BytesIO(data), media_type="application/zip", headers={"Content-Disposition":f"attachment; filename={filename}"})

@router.get("/audit-log")
def audit_log():
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "ai_audit_log.md"
    return {"path":"ai_audit_log.md","content":path.read_text() if path.exists() else "Audit log not found"}
