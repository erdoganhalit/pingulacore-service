"""
Varyant Rotasyon Modulu

Her pipeline calistirmasinda otomatik olarak bir sonraki varyanti secer.
Round-robin rotasyon; state veritabaninda tutulur (disk dosyasina bagimlilik yok).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from legacy_app.geometri.pomodoro.yaml_loader import ParsedTemplate

logger = logging.getLogger(__name__)


def get_variant_names(template: ParsedTemplate) -> list[str]:
    """ParsedTemplate'ten siralanmis varyant isimlerini cikarir.

    Desteklenen formatlar:
      - Dict-style: varyantlar: {varyant_1: {ad: "..."}, varyant_3: {ad: "..."}}
      - List-style: varyantlar: [{varyant_adi: "..."}, ...]
      - Per-question: context.questions[].varyant_adi
    """
    names: list[str] = []

    # 1) varyant_tanimlari["varyantlar"] — dict-style (Pattern A)
    #    Ic ice 'liste' varsa Pattern B'ye birak.
    top_varyantlar = template.varyant_tanimlari.get("varyantlar")
    if isinstance(top_varyantlar, dict) and "liste" not in top_varyantlar:
        for key, val in top_varyantlar.items():
            if isinstance(val, dict):
                names.append(val.get("ad", key))
            else:
                names.append(key)
        if names:
            return names

    # 2) raw YAML'daki varyantlar — list/dict-style (Pattern B)
    raw_varyantlar = (
        template.raw.get("varyantlar") or template.raw.get("Varyantlar")
        or template.raw.get("varyant") or template.raw.get("Varyant")
    )
    # Dict with nested 'liste' key containing actual variant list
    if isinstance(raw_varyantlar, dict) and "liste" in raw_varyantlar:
        raw_varyantlar = raw_varyantlar["liste"]
    if isinstance(raw_varyantlar, list):
        for item in raw_varyantlar:
            if isinstance(item, dict):
                name = item.get("varyant_adi") or item.get("ad") or item.get("baslik") or ""
                if name:
                    names.append(name)
            elif isinstance(item, str):
                names.append(item)
        if names:
            return names

    # 3) Per-question varyant_adi (Pattern C)
    questions = template.context.get("questions", [])
    seen: set[str] = set()
    for q in questions:
        v_name = q.get("varyant_adi") or ""
        if v_name and v_name not in seen:
            names.append(v_name)
            seen.add(v_name)

    return names


def get_variant_details(template: ParsedTemplate, variant_name: str) -> dict[str, Any]:
    """Belirtilen varyant adina ait detaylari ParsedTemplate'ten bulur.

    Senaryo cekirdegi, gorsel notlari, soru koku ornekleri gibi
    zengin verileri dondurur. Bulamazsa bos dict.
    """
    # 1) raw YAML'daki varyantlar — dict-style
    raw_varyantlar = (
        template.raw.get("varyantlar") or template.raw.get("Varyantlar")
        or template.raw.get("varyant") or template.raw.get("Varyant") or {}
    )

    # Dict with nested 'liste' key containing actual variant list
    if isinstance(raw_varyantlar, dict) and "liste" in raw_varyantlar:
        raw_varyantlar = raw_varyantlar["liste"]
    elif isinstance(raw_varyantlar, dict):
        for key, val in raw_varyantlar.items():
            if not isinstance(val, dict):
                continue
            if val.get("ad") == variant_name or val.get("baslik") == variant_name or key == variant_name:
                return dict(val)

    # 2) raw YAML'daki varyantlar — list-style
    if isinstance(raw_varyantlar, list):
        for item in raw_varyantlar:
            if isinstance(item, str):
                if item == variant_name:
                    return {"aciklama": item}
                continue
            if not isinstance(item, dict):
                continue
            item_name = item.get("varyant_adi") or item.get("ad") or item.get("baslik") or ""
            if item_name == variant_name:
                return dict(item)

    # 3) Per-question varyantlar
    for q in template.context.get("questions", []):
        if q.get("varyant_adi") == variant_name:
            return dict(q)
        for v in q.get("varyantlar", []):
            if isinstance(v, dict):
                v_name = v.get("varyant_adi") or v.get("ad") or v.get("baslik") or ""
                if v_name == variant_name:
                    return dict(v)

    return {}


def _yaml_key(yaml_path: str | Path) -> str:
    """YAML dosya yolundan stabil bir state key uretir."""
    return Path(yaml_path).stem


def select_next_variant(
    yaml_path: str | Path,
    available_variants: list[str],
    state_file: Path | None = None,  # geriye donuk uyumluluk icin tutuldu, kullanilmiyor
) -> str:
    """Siradaki varyanti secer ve DB'deki rotasyon durumunu gunceller.

    Round-robin rotasyon: her cagri bir sonraki varyanti dondurur.
    State veritabaninda tutulur; container yeniden baslatilsa da korunur.
    """
    if not available_variants:
        raise ValueError("available_variants bos olamaz")

    if len(available_variants) == 1:
        return available_variants[0]

    key = _yaml_key(yaml_path)

    try:
        from app.db.database import SessionLocal
        from app.db.models import VariantRotationState

        db = SessionLocal()
        try:
            row = db.query(VariantRotationState).filter_by(yaml_key=key).first()
            if row is None:
                row = VariantRotationState(yaml_key=key, last_index=-1, last_variant="")
                db.add(row)
                db.flush()

            next_index = (row.last_index + 1) % len(available_variants)
            selected = available_variants[next_index]
            row.last_index = next_index
            row.last_variant = selected
            db.commit()
            return selected
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    except Exception:
        logger.warning("Varyant rotasyon state'i DB'den alinamadi, ilk varyant seciliyor: %s", key)
        return available_variants[0]
