from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
import mimetypes
from pathlib import Path
import unicodedata
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.schemas.api import (
    CatalogAssetBulkUploadItemResult,
    CatalogAssetBulkUploadResponse,
    CatalogAssetDeleteResponse,
    CatalogAssetItem,
    CatalogAssetListResponse,
    CatalogAssetMoveItemResult,
    CatalogAssetMoveRequest,
    CatalogAssetMoveResponse,
    CatalogAssetRenameRequest,
    CatalogAssetRenameResponse,
    CatalogAssetUploadResponse,
)
from app.services.object_storage_service import ObjectStorageService


router = APIRouter(
    prefix="/v1/catalog-assets",
    tags=["catalog-assets"],
    dependencies=[Depends(get_current_user)],
)


_TURKISH_MAP = str.maketrans({
    "ç": "c",
    "ğ": "g",
    "ı": "i",
    "ö": "o",
    "ş": "s",
    "ü": "u",
    "Ç": "c",
    "Ğ": "g",
    "İ": "i",
    "I": "i",
    "Ö": "o",
    "Ş": "s",
    "Ü": "u",
})


def _normalize_text(value: str) -> str:
    lowered = value.casefold().translate(_TURKISH_MAP)
    normalized = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _score_match(query: str, key: str) -> float:
    stem = Path(key).stem.replace("_", " ").replace("-", " ")
    nq = _normalize_text(query)
    nk = _normalize_text(stem)
    if not nq or not nk:
        return 0.0
    ratio = SequenceMatcher(None, nq, nk).ratio()
    bonus_contains = 0.35 if nq in nk else 0.0
    bonus_prefix = 0.2 if nk.startswith(nq) else 0.0
    tokens = [token for token in nq.split() if token]
    bonus_token = 0.1 if tokens and all(token in nk for token in tokens) else 0.0
    return ratio + bonus_contains + bonus_prefix + bonus_token


def _format_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _mime_for_key(key: str) -> str | None:
    return mimetypes.guess_type(key)[0]


def _resolve_image_mime(filename: str, content_type: str | None) -> str:
    mime_type = (content_type or "").strip() or (mimetypes.guess_type(filename)[0] or "application/octet-stream")
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Sadece görsel dosyaları yüklenebilir")
    return mime_type


def _resolve_unique_catalog_key(
    storage: ObjectStorageService,
    bucket: str,
    base_key: str,
    claimed: set[str],
) -> str:
    """Pick a key that doesn't collide with existing bucket objects or other keys claimed in this call.

    Uniqueness is computed over the FULL key (including folder prefix), so `klasor1/a.png`
    and `klasor2/a.png` do not collide.
    """
    base_path = Path(base_key)
    parent = str(base_path.parent)
    parent_prefix = "" if parent in (".", "") else f"{parent}/"
    stem = base_path.stem
    ext = base_path.suffix

    key = base_key
    suffix = 1
    while key in claimed or storage.object_exists(bucket=bucket, key=key):
        key = f"{parent_prefix}{stem}_{suffix}{ext}"
        suffix += 1
    claimed.add(key)
    return key


def _normalize_prefix(raw: str | None) -> str:
    """Normalize a folder prefix to the canonical form '' (root) or 'a/' or 'a/b/'.

    Strips leading/trailing slashes, rejects `..` segments and empty intermediate segments.
    Returns '' when prefix is empty/None (root view).
    """
    if not raw:
        return ""
    cleaned = raw.replace("\\", "/").strip("/").strip()
    if not cleaned:
        return ""
    segments = cleaned.split("/")
    for seg in segments:
        seg_stripped = seg.strip()
        if not seg_stripped or seg_stripped == "..":
            raise HTTPException(status_code=400, detail="Geçersiz klasör yolu")
    return "/".join(s.strip() for s in segments) + "/"


def _validate_folder_name(name: str) -> str:
    """Validate a single folder name segment (no slashes allowed)."""
    name = (name or "").strip().strip("/")
    if not name:
        raise HTTPException(status_code=400, detail="Klasör adı boş olamaz")
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Klasör adı / veya \\ içeremez")
    if name == "..":
        raise HTTPException(status_code=400, detail="Geçersiz klasör adı")
    if name.startswith("."):
        raise HTTPException(status_code=400, detail="Klasör adı . ile başlayamaz")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Klasör adı 100 karakteri aşamaz")
    return name


def _validate_filename(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Dosya adı boş olamaz")
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Dosya adı / veya \\ içeremez")
    if name == "..":
        raise HTTPException(status_code=400, detail="Geçersiz dosya adı")
    if name.startswith("."):
        raise HTTPException(status_code=400, detail="Dosya adı . ile başlayamaz")
    if len(name) > 200:
        raise HTTPException(status_code=400, detail="Dosya adı 200 karakteri aşamaz")
    return name


@router.get("", response_model=CatalogAssetListResponse)
def list_catalog_assets(
    cursor: str | None = Query(default=None, description="Pagination cursor"),
    limit: int = Query(default=10, ge=1, le=50),
    query: str | None = Query(default=None, description="Fuzzy asset search"),
    prefix: str | None = Query(default=None, description="Klasör prefix'i (boş ise root)"),
) -> CatalogAssetListResponse:
    settings = get_settings()
    storage = ObjectStorageService(settings)
    normalized_prefix = _normalize_prefix(prefix)
    bucket = settings.s3_catalog_bucket

    q = (query or "").strip()
    if q:
        # Search spans the current prefix subtree, not just immediate children.
        all_objects = storage.list_objects(bucket=bucket, prefix=normalized_prefix or None)
        ranked: list[tuple[float, dict]] = []
        for obj in all_objects:
            score = _score_match(q, obj["key"])
            if score >= 0.28:
                ranked.append((score, obj))
        ranked.sort(key=lambda item: (-item[0], item[1]["key"]))
        filtered = [item[1] for item in ranked]
        folder_names: list[str] = []
    else:
        objects, folder_names = storage.list_with_folders(bucket=bucket, prefix=normalized_prefix or None)
        filtered = sorted(objects, key=lambda obj: obj["key"])

    offset = 0
    if cursor:
        try:
            offset = max(0, int(cursor))
        except ValueError:
            raise HTTPException(status_code=400, detail="Geçersiz cursor")

    page = filtered[offset : offset + limit]
    next_cursor = str(offset + limit) if offset + limit < len(filtered) else None

    items = [
        CatalogAssetItem(
            key=obj["key"],
            name=Path(obj["key"]).name,
            size=int(obj["size"]),
            last_modified=_format_dt(obj.get("last_modified")),
            mime_type=_mime_for_key(obj["key"]),
            content_url=f"/v1/catalog-assets/{quote(obj['key'], safe='')}/content",
        )
        for obj in page
    ]

    return CatalogAssetListResponse(
        items=items,
        folders=folder_names,
        prefix=normalized_prefix or None,
        next_cursor=next_cursor,
        total_count=len(filtered),
        query=q or None,
    )


@router.post("", response_model=CatalogAssetUploadResponse)
async def upload_catalog_asset(
    file: UploadFile = File(...),
    prefix: str | None = Query(default=None, description="Hedef klasör prefix'i"),
) -> CatalogAssetUploadResponse:
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Dosya adı boş olamaz")

    normalized_prefix = _normalize_prefix(prefix)
    base_filename = Path(filename).name
    base_key = f"{normalized_prefix}{base_filename}"
    settings = get_settings()
    storage = ObjectStorageService(settings)

    mime_type = _resolve_image_mime(base_filename, file.content_type)
    key = _resolve_unique_catalog_key(storage, settings.s3_catalog_bucket, base_key, claimed=set())

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Boş dosya yüklenemez")

    storage.upload_bytes(
        bucket=settings.s3_catalog_bucket,
        key=key,
        data=content,
        content_type=mime_type,
    )
    return CatalogAssetUploadResponse(key=key, size=len(content), mime_type=mime_type)


@router.post("/bulk", response_model=CatalogAssetBulkUploadResponse)
async def upload_catalog_assets_bulk(
    files: list[UploadFile] = File(...),
    prefix: str | None = Query(default=None, description="Hedef klasör prefix'i"),
) -> CatalogAssetBulkUploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="En az bir dosya gönderilmeli")

    normalized_prefix = _normalize_prefix(prefix)
    settings = get_settings()
    storage = ObjectStorageService(settings)
    bucket = settings.s3_catalog_bucket

    results: list[CatalogAssetBulkUploadItemResult] = []
    claimed_keys: set[str] = set()

    for upload in files:
        filename = (upload.filename or "").strip()
        try:
            if not filename:
                raise HTTPException(status_code=400, detail="Dosya adı boş olamaz")

            base_filename = Path(filename).name
            base_key = f"{normalized_prefix}{base_filename}"
            mime_type = _resolve_image_mime(base_filename, upload.content_type)
            key = _resolve_unique_catalog_key(storage, bucket, base_key, claimed=claimed_keys)

            content = await upload.read()
            if not content:
                raise HTTPException(status_code=400, detail="Boş dosya yüklenemez")

            storage.upload_bytes(
                bucket=bucket,
                key=key,
                data=content,
                content_type=mime_type,
            )
            results.append(
                CatalogAssetBulkUploadItemResult(
                    filename=filename or "(unnamed)",
                    success=True,
                    key=key,
                    size=len(content),
                    mime_type=mime_type,
                )
            )
        except HTTPException as exc:
            results.append(
                CatalogAssetBulkUploadItemResult(
                    filename=filename or "(unnamed)",
                    success=False,
                    error=str(exc.detail),
                )
            )
        except Exception as exc:
            results.append(
                CatalogAssetBulkUploadItemResult(
                    filename=filename or "(unnamed)",
                    success=False,
                    error=f"Beklenmeyen hata: {exc}",
                )
            )

    success_count = sum(1 for r in results if r.success)
    return CatalogAssetBulkUploadResponse(
        results=results,
        success_count=success_count,
        failure_count=len(results) - success_count,
    )


@router.post("/move-into-folder", response_model=CatalogAssetMoveResponse)
def move_into_folder(payload: CatalogAssetMoveRequest) -> CatalogAssetMoveResponse:
    folder_name = _validate_folder_name(payload.folder)
    if not payload.keys:
        raise HTTPException(status_code=400, detail="En az bir görsel seçilmeli")

    settings = get_settings()
    storage = ObjectStorageService(settings)
    bucket = settings.s3_catalog_bucket

    # Reject the target folder name if it collides with an existing file at root.
    if storage.object_exists(bucket=bucket, key=folder_name):
        raise HTTPException(
            status_code=409,
            detail=f"'{folder_name}' adında bir dosya zaten var; klasör oluşturulamaz",
        )

    results: list[CatalogAssetMoveItemResult] = []
    claimed_keys: set[str] = set()
    target_prefix = f"{folder_name}/"

    for source_key in payload.keys:
        normalized_source = (source_key or "").strip().lstrip("/")
        try:
            if not normalized_source:
                raise HTTPException(status_code=400, detail="Geçersiz key")
            filename = Path(normalized_source).name
            if not filename:
                raise HTTPException(status_code=400, detail=f"Geçersiz key: {source_key}")

            if not storage.object_exists(bucket=bucket, key=normalized_source):
                raise HTTPException(status_code=404, detail="Görsel bulunamadı")

            target_base = f"{target_prefix}{filename}"
            if target_base == normalized_source:
                # Already at destination; treat as no-op success.
                results.append(
                    CatalogAssetMoveItemResult(
                        key=normalized_source,
                        success=True,
                        new_key=normalized_source,
                    )
                )
                continue

            target_key = _resolve_unique_catalog_key(storage, bucket, target_base, claimed=claimed_keys)
            storage.copy_object(bucket=bucket, source_key=normalized_source, dest_key=target_key)
            storage.delete_object(bucket=bucket, key=normalized_source)
            results.append(
                CatalogAssetMoveItemResult(
                    key=normalized_source,
                    success=True,
                    new_key=target_key,
                )
            )
        except HTTPException as exc:
            results.append(
                CatalogAssetMoveItemResult(
                    key=normalized_source or source_key,
                    success=False,
                    error=str(exc.detail),
                )
            )
        except Exception as exc:
            results.append(
                CatalogAssetMoveItemResult(
                    key=normalized_source or source_key,
                    success=False,
                    error=f"Beklenmeyen hata: {exc}",
                )
            )

    success_count = sum(1 for r in results if r.success)
    return CatalogAssetMoveResponse(
        folder=folder_name,
        results=results,
        success_count=success_count,
        failure_count=len(results) - success_count,
    )


@router.post("/rename", response_model=CatalogAssetRenameResponse)
def rename_catalog_asset(payload: CatalogAssetRenameRequest) -> CatalogAssetRenameResponse:
    source_key = (payload.key or "").strip().lstrip("/")
    if not source_key:
        raise HTTPException(status_code=400, detail="Mevcut key gerekli")

    new_filename = _validate_filename(payload.new_name)

    # Preserve image extension type: new filename must resolve to an image mime.
    new_mime = mimetypes.guess_type(new_filename)[0] or ""
    if not new_mime.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Yeni dosya adı bir görsel uzantısına (.png, .jpg, vb.) sahip olmalı",
        )

    settings = get_settings()
    storage = ObjectStorageService(settings)
    bucket = settings.s3_catalog_bucket

    if not storage.object_exists(bucket=bucket, key=source_key):
        raise HTTPException(status_code=404, detail="Görsel bulunamadı")

    source_path = Path(source_key)
    parent = str(source_path.parent)
    parent_prefix = "" if parent in (".", "") else f"{parent}/"
    new_key = f"{parent_prefix}{new_filename}"

    if new_key == source_key:
        return CatalogAssetRenameResponse(old_key=source_key, new_key=source_key)

    if storage.object_exists(bucket=bucket, key=new_key):
        raise HTTPException(
            status_code=409,
            detail=f"Aynı isimde bir görsel zaten var: {new_key}",
        )

    storage.copy_object(bucket=bucket, source_key=source_key, dest_key=new_key)
    storage.delete_object(bucket=bucket, key=source_key)

    return CatalogAssetRenameResponse(old_key=source_key, new_key=new_key)


@router.delete("/{key:path}", response_model=CatalogAssetDeleteResponse)
def delete_catalog_asset(key: str) -> CatalogAssetDeleteResponse:
    normalized_key = key.strip().lstrip("/")
    if not normalized_key:
        raise HTTPException(status_code=400, detail="Asset key gerekli")
    settings = get_settings()
    storage = ObjectStorageService(settings)
    deleted = storage.delete_object(bucket=settings.s3_catalog_bucket, key=normalized_key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Asset bulunamadı")
    return CatalogAssetDeleteResponse(key=normalized_key, deleted=True)


@router.get("/{key:path}/content")
def get_catalog_asset_content(key: str) -> Response:
    normalized_key = key.strip().lstrip("/")
    if not normalized_key:
        raise HTTPException(status_code=400, detail="Asset key gerekli")

    settings = get_settings()
    storage = ObjectStorageService(settings)
    try:
        content, mime_type = storage.get_object(bucket=settings.s3_catalog_bucket, key=normalized_key)
    except Exception:
        raise HTTPException(status_code=404, detail="Asset bulunamadı")

    return Response(content=content, media_type=mime_type or _mime_for_key(normalized_key) or "application/octet-stream")
