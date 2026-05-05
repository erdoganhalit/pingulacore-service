from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db import repository
from app.db.database import get_db
from app.schemas.api import (
    LegacyBatchDetailResponse,
    LegacyBatchRunRequest,
    LegacyBatchRunResponse,
    LegacyOutputNode,
    LegacyPipelineDescriptor,
    LegacyPipelineKind,
    LegacyPipelinesResponse,
    LegacyRunDetail,
    LegacyRunDetailResponse,
    LegacyYamlContentResponse,
    LegacyYamlDeleteResponse,
    LegacyYamlContentUpdateRequest,
    LegacyYamlFilesResponse,
    LegacyYamlInfoResponse,
    LegacyYamlUploadResponse,
    LegacyYamlsUploadResponse,
    FileExtractionResult,
    ExtractionError,
    PipelineLogEntryResponse,
)
from app.services import legacy_pipeline_service as legacy_svc
from app.services.legacy_session_output_store import get_legacy_output_store


router = APIRouter(
    prefix="/v1/legacy",
    tags=["legacy"],
    dependencies=[Depends(get_current_user)],
)


def _dt(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _ensure_kind(kind: LegacyPipelineKind) -> None:
    if kind not in legacy_svc.LEGACY_PIPELINES:
        raise HTTPException(status_code=400, detail="Bilinmeyen pipeline türü")


def _require_session_id(session_id: str | None) -> str:
    safe = (session_id or "").strip()
    if not safe:
        raise HTTPException(status_code=400, detail="X-Session-Id header zorunlu")
    return safe


@router.get("/pipelines", response_model=LegacyPipelinesResponse)
def list_legacy_pipelines() -> LegacyPipelinesResponse:
    items = legacy_svc.list_pipelines()
    return LegacyPipelinesResponse(
        pipelines=[LegacyPipelineDescriptor(**item) for item in items]
    )


@router.get("/pipelines/{kind}/yaml-files", response_model=LegacyYamlFilesResponse)
def list_legacy_yaml_files(kind: LegacyPipelineKind) -> LegacyYamlFilesResponse:
    _ensure_kind(kind)
    files = legacy_svc.list_yaml_files(kind)
    return LegacyYamlFilesResponse(kind=kind, files=files)


@router.get("/pipelines/{kind}/yaml-info", response_model=LegacyYamlInfoResponse)
def get_legacy_yaml_info(
    kind: LegacyPipelineKind,
    yaml_path: str = Query(..., description="Legacy YAML kimliği (DB)"),
) -> LegacyYamlInfoResponse:
    _ensure_kind(kind)
    try:
        info = legacy_svc.inspect_yaml(kind, yaml_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LegacyYamlInfoResponse(**info)


@router.get("/pipelines/{kind}/yaml-content", response_model=LegacyYamlContentResponse)
def get_legacy_yaml_content(
    kind: LegacyPipelineKind,
    yaml_path: str = Query(...),
) -> LegacyYamlContentResponse:
    _ensure_kind(kind)
    try:
        payload = legacy_svc.read_yaml_content(kind, yaml_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LegacyYamlContentResponse(**payload)


@router.put("/pipelines/{kind}/yaml-content", response_model=LegacyYamlContentResponse)
def put_legacy_yaml_content(
    kind: LegacyPipelineKind,
    req: LegacyYamlContentUpdateRequest,
) -> LegacyYamlContentResponse:
    _ensure_kind(kind)
    try:
        payload = legacy_svc.write_yaml_content(kind, req.yaml_path, req.content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LegacyYamlContentResponse(**payload)


@router.delete("/pipelines/{kind}/yaml-content", response_model=LegacyYamlDeleteResponse)
def delete_legacy_yaml_content(
    kind: LegacyPipelineKind,
    yaml_path: str = Query(...),
) -> LegacyYamlDeleteResponse:
    _ensure_kind(kind)
    try:
        deleted = legacy_svc.delete_yaml_content(kind, yaml_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"YAML bulunamadı: {yaml_path}")
    return LegacyYamlDeleteResponse(kind=kind, yaml_path=yaml_path, deleted=True)


@router.post("/pipelines/{kind}/yaml-upload", response_model=LegacyYamlUploadResponse)
async def upload_legacy_yaml(
    kind: LegacyPipelineKind,
    file: UploadFile = File(...),
) -> LegacyYamlUploadResponse:
    _ensure_kind(kind)
    content = await file.read()
    try:
        yaml_path = legacy_svc.save_uploaded_yaml(
            kind, filename=file.filename or "uploaded.yaml", content=content
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LegacyYamlUploadResponse(kind=kind, yaml_path=yaml_path)


@router.post("/pipelines/{kind}/yamls-upload", response_model=LegacyYamlsUploadResponse)
async def upload_legacy_yamls(
    kind: LegacyPipelineKind,
    files: list[UploadFile] = File(...),
) -> LegacyYamlsUploadResponse:
    _ensure_kind(kind)
    if not files:
        raise HTTPException(status_code=400, detail="En az bir YAML dosyası gerekli")

    payloads: list[tuple[str, bytes]] = []
    for upload in files:
        content = await upload.read()
        payloads.append((upload.filename or "uploaded.yaml", content))

    outcomes = legacy_svc.extract_uploaded_yamls(kind, files=payloads)
    results = [
        FileExtractionResult(
            filename=o.filename,
            yaml_path=o.yaml_path,
            errors=[ExtractionError(type=e.type, message=e.message, location=e.location) for e in o.errors],
            warnings=[ExtractionError(type=w.type, message=w.message, location=w.location) for w in o.warnings],
        )
        for o in outcomes
    ]
    ok = sum(1 for r in results if not r.errors)
    return LegacyYamlsUploadResponse(
        kind=kind,
        results=results,
        ok_count=ok,
        error_count=len(results) - ok,
    )


@router.post("/pipelines/{kind}/batch-run", response_model=LegacyBatchRunResponse)
async def run_legacy_batch(
    kind: LegacyPipelineKind,
    req: LegacyBatchRunRequest,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
    db: Session = Depends(get_db),
) -> LegacyBatchRunResponse:
    _ensure_kind(kind)
    session_id = _require_session_id(x_session_id)
    service = legacy_svc.LegacyPipelineService(db)
    items = [item.model_dump() for item in req.items]
    try:
        result = await service.run_batch(
            kind=kind,
            session_id=session_id,
            items=items,
            parallelism=req.parallelism,
            stream_key=req.stream_key,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return LegacyBatchRunResponse(**result)


@router.get("/runs/{run_id}", response_model=LegacyRunDetailResponse)
def get_legacy_run(
    run_id: str,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
    db: Session = Depends(get_db),
) -> LegacyRunDetailResponse:
    session_id = _require_session_id(x_session_id)
    service = legacy_svc.LegacyPipelineService(db)
    detail = service.get_run_detail(run_id, session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Legacy run bulunamadı")
    detail = dict(detail)
    detail["outputs"] = [LegacyOutputNode(**item) for item in detail.get("outputs", [])]
    return LegacyRunDetailResponse(**detail)


@router.get("/runs/{batch_id}/batch", response_model=LegacyBatchDetailResponse)
def get_legacy_batch(
    batch_id: str,
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
    db: Session = Depends(get_db),
) -> LegacyBatchDetailResponse:
    session_id = _require_session_id(x_session_id)
    service = legacy_svc.LegacyPipelineService(db)
    detail = service.get_batch_detail(batch_id, session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Legacy batch bulunamadı")
    runs = [
        LegacyRunDetail(
            **{**r, "outputs": [LegacyOutputNode(**n) for n in r.get("outputs", [])]}
        )
        for r in detail["runs"]
    ]
    return LegacyBatchDetailResponse(batch_id=detail["batch_id"], kind=detail["kind"], runs=runs)


@router.get("/runs/{run_id}/download")
def download_legacy_run(
    run_id: str,
    subdir: str | None = Query(None),
    sid: str | None = Query(default=None),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    session_id = _require_session_id(x_session_id or sid)
    service = legacy_svc.LegacyPipelineService(db)
    detail = service.get_run_detail(run_id, session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Legacy run bulunamadı")
    store = get_legacy_output_store()
    try:
        chunks, suggested = store.iter_zip_stream(session_id=session_id, run_id=run_id, subdir=subdir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(suggested)}",
    }
    return StreamingResponse(chunks, media_type="application/zip", headers=headers)


@router.get("/runs/{run_id}/outputs/{rel_path:path}")
def get_legacy_run_output_file(
    run_id: str,
    rel_path: str,
    sid: str | None = Query(default=None, description="Legacy session id (img/src gibi header olmayan istekler için)"),
    x_session_id: str | None = Header(default=None, alias="X-Session-Id"),
) -> Response:
    session_id = (x_session_id or sid or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="X-Session-Id veya sid gerekli")
    store = get_legacy_output_store()
    item = store.get_file(session_id=session_id, run_id=run_id, rel_path=rel_path)
    if item is None:
        raise HTTPException(status_code=404, detail="Output bulunamadı veya süresi doldu")
    return Response(content=item.content, media_type=item.mime_type)


@router.get("/runs/{run_id}/logs", response_model=list[PipelineLogEntryResponse])
def get_legacy_run_logs(run_id: str, db: Session = Depends(get_db)) -> list[PipelineLogEntryResponse]:
    rows = repository.list_pipeline_logs(db, run_id)
    return [
        PipelineLogEntryResponse(
            id=row.id,
            pipeline_id=row.pipeline_id,
            sub_pipeline_id=row.sub_pipeline_id,
            mode=row.mode,
            level=row.level,
            component=row.component,
            message=row.message,
            details=repository.parse_json(row.details_json),
            created_at=_dt(row.created_at) or "",
        )
        for row in rows
    ]
