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
    CatalogAssetDeleteResponse,
    CatalogAssetItem,
    CatalogAssetListResponse,
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


@router.get("", response_model=CatalogAssetListResponse)
def list_catalog_assets(
    cursor: str | None = Query(default=None, description="Pagination cursor"),
    limit: int = Query(default=10, ge=1, le=50),
    query: str | None = Query(default=None, description="Fuzzy asset search"),
) -> CatalogAssetListResponse:
    settings = get_settings()
    storage = ObjectStorageService(settings)
    objects = storage.list_objects(bucket=settings.s3_catalog_bucket)

    q = (query or "").strip()
    if q:
        ranked: list[tuple[float, dict]] = []
        for obj in objects:
            score = _score_match(q, obj["key"])
            if score >= 0.28:
                ranked.append((score, obj))
        ranked.sort(key=lambda item: (-item[0], item[1]["key"]))
        filtered = [item[1] for item in ranked]
    else:
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
        next_cursor=next_cursor,
        total_count=len(filtered),
        query=q or None,
    )


@router.post("", response_model=CatalogAssetUploadResponse)
async def upload_catalog_asset(file: UploadFile = File(...)) -> CatalogAssetUploadResponse:
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Dosya adı boş olamaz")

    key = Path(filename).name
    settings = get_settings()
    storage = ObjectStorageService(settings)

    mime_type = (file.content_type or "").strip() or (mimetypes.guess_type(key)[0] or "application/octet-stream")
    if not mime_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Sadece görsel dosyaları yüklenebilir")

    base_key = key
    suffix = 1
    while storage.object_exists(bucket=settings.s3_catalog_bucket, key=key):
        stem = Path(base_key).stem
        ext = Path(base_key).suffix
        key = f"{stem}_{suffix}{ext}"
        suffix += 1

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
