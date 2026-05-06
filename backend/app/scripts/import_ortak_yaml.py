from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import models, repository
from app.db.database import SessionLocal


REPO_ROOT = Path(__file__).resolve().parents[2]
ORTAK_DIR = REPO_ROOT / "ortak"
IMPORT_CREATED_BY = "ortak-import"
GRADE_SLUG = "grade-2"
SUBJECT_SLUG = "2-matematik"
SUBJECT_PATH = f"root/{GRADE_SLUG}/{SUBJECT_SLUG}"


@dataclass(frozen=True)
class TemplateSpec:
    code: str
    title: str
    description: str
    theme_slug: str
    filenames: tuple[str, ...]

    @property
    def folder_slug(self) -> str:
        suffix = self.code.removesuffix("_v1")
        return f"import-{suffix}"

    @property
    def folder_name(self) -> str:
        return f"Import / {self.code}"

    @property
    def folder_path(self) -> str:
        return f"{SUBJECT_PATH}/{self.theme_slug}/{self.folder_slug}"


@dataclass(frozen=True)
class PropertySpec:
    canonical_path: str
    property_key: str
    label: str
    description: str
    data_type: str
    constraints: Any | None = None
    parent_lookup: tuple[str, str] | None = None


TEMPLATE_SPECS: tuple[TemplateSpec, ...] = (
    TemplateSpec(
        code="g2m_geometry_common_v1",
        title="2. Sınıf Matematik Geometri Ortak Template",
        description="Geometri ve günlük nesne eşleştirme odaklı ortak YAML iskeleti.",
        theme_slug="nesnelerin-geometrisi-1",
        filenames=("g1_geometrik_cisim_orneklerini_dogru_sirayla_veren_kisiyi_secme.yaml",),
    ),
    TemplateSpec(
        code="g2m_operations_common_v1",
        title="2. Sınıf Matematik İşlem Ortak Template",
        description="İşlem, toplama, çıkarma, karşılaştırma ve benzeri ortak soru iskeleti.",
        theme_slug="islemlerden-cebirsel-dusunmeye",
        filenames=(
            "k10_ardisik_cikarma_sonuc.yaml",
            "k16_tek_adimli_cikarma.yaml",
            "k17_eldeli_toplama.yaml",
            "k18_onluk_bozarak_cikarma.yaml",
            "k21_eksilen_cikan_gorselden.yaml",
            "k4_carpma_okunus.yaml",
            "o08_iki_adimli_toplama.yaml",
            "o09_toplama_cikarma.yaml",
            "o14_onluk_bozarak_senaryo.yaml",
            "o22_islem_sonuclari_karsilastir.yaml",
        ),
    ),
    TemplateSpec(
        code="g2m_numeracy_common_v1",
        title="2. Sınıf Matematik Sayı ve Nicelik Ortak Template",
        description="Sayı-nicelik, deste-düzine ve temel sayısal ilişki odaklı ortak template.",
        theme_slug="sayilar-ve-nicelikler-1",
        filenames=("k19_deste_duzine_cevir.yaml",),
    ),
    TemplateSpec(
        code="g2m_operations_visual_option_persona_v1",
        title="2. Sınıf Matematik Görselli Persona Şıklı İşlem Template",
        description="Konuşma balonlu çocuk/persona şıkları içeren işlem template'i.",
        theme_slug="islemlerden-cebirsel-dusunmeye",
        filenames=("k1001_ardisik_cikarma_sonuc_gorsel_sik.yaml",),
    ),
    TemplateSpec(
        code="g2m_operations_context_visual_mirror_v1",
        title="2. Sınıf Matematik Görsel Aynalama İşlem Template",
        description="Context.generation altında ek görsel açıklamalar taşıyan işlem template'i.",
        theme_slug="islemlerden-cebirsel-dusunmeye",
        filenames=(
            "k11_ardisik_eksilen_nesne.yaml",
            "k5_carpim_tablo_eksik_sonuc.yaml",
            "o05_ardisik_cikarma_bolme_eslestir.yaml",
            "o23_sifreli_islem_seti.yaml",
        ),
    ),
    TemplateSpec(
        code="g2m_fraction_tray_variants_v1",
        title="2. Sınıf Matematik Adil Paylaşım Varyant Template",
        description="Tepsi ve eş parça paylaşımı varyantlarını taşıyan fraction template'i.",
        theme_slug="sayilar-ve-nicelikler-2",
        filenames=("o16_tepsi_4_cocuk_yaml_varyantli.yaml",),
    ),
    TemplateSpec(
        code="g2m_fraction_half_area_variants_v1",
        title="2. Sınıf Matematik Yarım Alanı Tamamlama Template",
        description="Açık yarım alan ve varyantlı görsel tamamlama iskeleti.",
        theme_slug="sayilar-ve-nicelikler-2",
        filenames=("o17_karma_soru_kalibi_varyantli.yaml",),
    ),
    TemplateSpec(
        code="g2m_fraction_token_completion_v1",
        title="2. Sınıf Matematik Jetonla Tamamlama Template",
        description="Jeton maliyeti ile bütün-yarım-çeyrek tamamlama template'i.",
        theme_slug="sayilar-ve-nicelikler-2",
        filenames=("o18_vitrin_etiket_yaml_varyantli.yaml",),
    ),
    TemplateSpec(
        code="g2m_fraction_relation_variants_v1",
        title="2. Sınıf Matematik Bütün-Yarım-Çeyrek İlişki Template",
        description="Bütün-yarım-çeyrek ilişkisini varyantlarla kuran fraction template'i.",
        theme_slug="sayilar-ve-nicelikler-2",
        filenames=("o19_butun_yarim_ceyrek_sayisal_iliski_varyantli.yaml",),
    ),
    TemplateSpec(
        code="g2m_fraction_closed_box_variants_v1",
        title="2. Sınıf Matematik Kapalı Kutu İpuçları Template",
        description="İpucu ve varyant yapılarıyla kapalı kutu isimlendirme template'i.",
        theme_slug="sayilar-ve-nicelikler-2",
        filenames=("o20_kapali_kutu_ipuclarina_gore_adlandirma_varyantli.yaml",),
    ),
    TemplateSpec(
        code="g2m_numeracy_money_sort_variants_v1",
        title="2. Sınıf Matematik Para Sıralama Varyant Template",
        description="Para değeri ve sıralama varyantlarını taşıyan numeracy template'i.",
        theme_slug="sayilar-ve-nicelikler-1",
        filenames=("o21_kalan_paralari_sirala_duzende_varyantli.yaml",),
    ),
)

SUBJECT_PROPERTY_SPECS: tuple[PropertySpec, ...] = (
    PropertySpec("content.pattern_id", "pattern_id", "Pattern ID", "YAML kalıbının benzersiz desen kimliği.", "text"),
    PropertySpec("content.source_filename", "source_filename", "Kaynak dosya adı", "İmport edilen YAML dosyasının adı.", "text"),
    PropertySpec("content.frequency_level", "frequency_level", "Frekans seviyesi", "Kalıbın kullanım sıklığı düzeyi.", "text"),
    PropertySpec("content.difficulty_level", "difficulty_level", "Zorluk seviyesi", "Kalıbın özet zorluk seviyesi.", "text"),
    PropertySpec("generation.image_type", "image_type", "Görsel üretim tipi", "Soru bağlamında beklenen görsel üretim tipi.", "text"),
    PropertySpec("generation.structure_rules", "structure_rules", "Yapı kuralları", "Senaryo ve üretim iskeletini oluşturan yapı kuralları.", "array"),
    PropertySpec("generation.prompt_rules", "prompt_rules", "Prompt kuralları", "LLM veya görsel üretim prompt'una taşınacak kurallar.", "array"),
    PropertySpec("question.question_count", "question_count", "Soru sayısı", "Bir YAML instance içinde üretilecek soru sayısı.", "number"),
    PropertySpec("question.slot_types", "slot_types", "Soru slot tipleri", "Question slot'larında tanımlanan type değerleri.", "array"),
    PropertySpec("paragraph.required", "required", "Paragraf zorunlu mu", "Soruda paragraf alanının zorunlu olup olmadığını belirtir.", "bool"),
    PropertySpec("paragraph.word_count_min", "word_count_min", "Paragraf minimum kelime", "Paragraf için minimum kelime sınırı.", "number"),
    PropertySpec("paragraph.word_count_max", "word_count_max", "Paragraf maksimum kelime", "Paragraf için maksimum kelime sınırı.", "number"),
    PropertySpec("paragraph.sentence_count_min", "sentence_count_min", "Paragraf minimum cümle", "Paragraf için minimum cümle sayısı.", "number"),
    PropertySpec("paragraph.sentence_count_max", "sentence_count_max", "Paragraf maksimum cümle", "Paragraf için maksimum cümle sayısı.", "number"),
    PropertySpec("option.labels", "labels", "Şık etiketleri", "Seçeneklerde kullanılacak etiket listesi.", "array"),
    PropertySpec("option.correct_count", "correct_count", "Doğru şık sayısı", "Soruda beklenen doğru seçenek sayısı.", "number"),
    PropertySpec("option.style", "style", "Şık stili", "Seçeneklerin görsel veya sözel sunum stili.", "text"),
    PropertySpec("option.word_count_min", "word_count_min", "Şık minimum kelime", "Bir şık için minimum kelime sınırı.", "number"),
    PropertySpec("option.word_count_max", "word_count_max", "Şık maksimum kelime", "Bir şık için maksimum kelime sınırı.", "number"),
    PropertySpec(
        "visual.main_style",
        "main_style",
        "Ana görsel stili",
        "Ana soru görselinin stil tanımı.",
        "text",
        parent_lookup=("root", "visual"),
    ),
    PropertySpec(
        "visual.main_size",
        "main_size",
        "Ana görsel boyutu",
        "Ana soru görselinin boyut etiketi.",
        "text",
        parent_lookup=("root", "visual"),
    ),
    PropertySpec(
        "visual.option_required",
        "option_required",
        "Şık görseli gerekli mi",
        "Şıkların ayrıca görsel ile desteklenip desteklenmeyeceğini belirtir.",
        "bool",
        parent_lookup=("root", "visual"),
    ),
    PropertySpec(
        "visual.option_rules",
        "option_rules",
        "Şık görsel kuralları",
        "Şık görselleri için uyulacak kurallar.",
        "array",
        parent_lookup=("root", "visual"),
    ),
    PropertySpec("answer.rules", "rules", "Doğru cevap kuralları", "Doğru cevabı tanımlayan kural listesi.", "array"),
    PropertySpec("distractor.rules", "rules", "Çeldirici kuralları", "Yanlış seçenekler için üretim kuralları.", "array"),
    PropertySpec("distractor.forbidden_rules", "forbidden_rules", "Çeldirici yasakları", "Yanlış seçeneklerde kaçınılacak durumlar.", "array"),
    PropertySpec("curriculum.learning_outcome", "learning_outcome", "Öğrenme çıktısı", "TYMM öğrenme çıktısı özeti.", "text"),
    PropertySpec("curriculum.theme_boundary", "theme_boundary", "Tema sınırı", "Kalıbın bağlı kaldığı müfredat tema sınırı.", "text"),
    PropertySpec("curriculum.allowed_concepts", "allowed_concepts", "İzinli kavramlar", "Kalıpta kullanılmasına izin verilen kavramlar.", "array"),
    PropertySpec("curriculum.allowed_skills", "allowed_skills", "İzinli beceriler", "Kalıpta kullanılmasına izin verilen beceriler.", "array"),
    PropertySpec("curriculum.allowed_operations", "allowed_operations", "İzinli soru işlemleri", "Kalıpta kullanılmasına izin verilen soru işlemleri.", "array"),
)

OPTION_SPECIAL_SPECS: tuple[PropertySpec, ...] = (
    PropertySpec("option.content_type", "content_type", "Şık içerik tipi", "Şıkların içerik tipi.", "text"),
    PropertySpec("option.render_mode", "render_mode", "Şık render modu", "Şıkların nasıl render edileceği.", "text"),
    PropertySpec("option.presentation_mode", "presentation_mode", "Şık sunum modu", "Şık sunum biçimi.", "text"),
    PropertySpec("option.personas", "personas", "Şık persona listesi", "Şıklarda kullanılacak persona tanımları.", "json"),
)

VARIANT_SPECS: tuple[PropertySpec, ...] = (
    PropertySpec("variant.enabled", "enabled", "Varyant etkin mi", "Bu template'te varyant mantığı bulunup bulunmadığı.", "bool"),
    PropertySpec("variant.codes", "codes", "Varyant kodları", "Tanımlı varyant kodlarının listesi.", "array"),
    PropertySpec("variant.active_codes", "active_codes", "Aktif varyant kodları", "Question slot'larında aktif olarak kullanılan varyant kodları.", "array"),
    PropertySpec("variant.definitions", "definitions", "Varyant tanımları", "YAML içindeki varyant açıklamalarının ham yapısı.", "json"),
)

DIFFICULTY_EXPLANATION_SPEC = PropertySpec(
    "difficulty.explanation",
    "explanation",
    "Zorluk açıklaması",
    "Zorluk seviyesine ait açıklama metni.",
    "text",
)

TEMPLATE_LOCAL_PROPERTY_SPECS: dict[str, tuple[PropertySpec, ...]] = {
    "g2m_operations_visual_option_persona_v1": OPTION_SPECIAL_SPECS,
    "g2m_fraction_tray_variants_v1": VARIANT_SPECS,
    "g2m_fraction_half_area_variants_v1": VARIANT_SPECS,
    "g2m_fraction_token_completion_v1": VARIANT_SPECS + (DIFFICULTY_EXPLANATION_SPEC,),
    "g2m_fraction_relation_variants_v1": VARIANT_SPECS,
    "g2m_fraction_closed_box_variants_v1": VARIANT_SPECS,
    "g2m_numeracy_money_sort_variants_v1": VARIANT_SPECS,
}


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def normalize_enum_text(value: str | None) -> str | None:
    token = normalize_text(value)
    return token.lower() or None


def normalize_bool_like(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = normalize_text(value).lower()
        if token in {"true", "yes", "evet"}:
            return True
        if token in {"false", "no", "hayir"}:
            return False
    return None


def unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        if raw is None:
            continue
        if isinstance(raw, str):
            token = raw.strip()
        else:
            token = str(raw).strip()
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def get_path(data: Any, *keys: str, default: Any = None) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def infer_leaf_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "text"


def build_field_schema(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {key: build_field_schema(child) for key, child in value.items()},
        }
    if isinstance(value, list):
        item_schema = build_field_schema(value[0]) if value else {"type": "text"}
        return {"type": "array", "items": item_schema}
    return {"type": infer_leaf_type(value)}


def shape_signature(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: shape_signature(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        if not value:
            return []
        return [shape_signature(value[0])]
    return type(value).__name__


def load_yaml_files() -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for path in sorted(ORTAK_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"YAML üst seviyesi dict olmalı: {path.name}")
        payloads[path.name] = data
    return payloads


def validate_bucket_count(payloads: dict[str, dict[str, Any]]) -> None:
    buckets = Counter(json.dumps(shape_signature(payload), sort_keys=True, ensure_ascii=False) for payload in payloads.values())
    if len(buckets) != 9:
        raise ValueError(f"Beklenen 9 structure bucket yerine {len(buckets)} bulundu")


def validate_template_mapping(payloads: dict[str, dict[str, Any]]) -> dict[str, TemplateSpec]:
    by_file: dict[str, TemplateSpec] = {}
    for spec in TEMPLATE_SPECS:
        for filename in spec.filenames:
            if filename in by_file:
                raise ValueError(f"Dosya iki template'e atanmış: {filename}")
            by_file[filename] = spec
    missing = sorted(set(payloads) - set(by_file))
    extra = sorted(set(by_file) - set(payloads))
    if missing:
        raise ValueError(f"Template eşlemesinde eksik dosyalar var: {missing}")
    if extra:
        raise ValueError(f"Template eşlemesinde bulunmayan dosyalar tanımlanmış: {extra}")
    return by_file


def get_constant_node_by_path(db: Session, path: str) -> models.CurriculumConstantNode:
    row = db.scalar(select(models.CurriculumConstantNode).where(models.CurriculumConstantNode.path == path))
    if row is None:
        raise ValueError(f"Constant curriculum node bulunamadı: {path}")
    return row


def get_folder_by_path(db: Session, path: str) -> models.CurriculumFolderNode | None:
    return db.scalar(select(models.CurriculumFolderNode).where(models.CurriculumFolderNode.path == path))


def ensure_folder_node(db: Session, spec: TemplateSpec) -> models.CurriculumFolderNode:
    existing = get_folder_by_path(db, spec.folder_path)
    if existing is not None:
        changed = False
        if existing.name != spec.folder_name:
            existing.name = spec.folder_name
            changed = True
        if existing.code != spec.code:
            existing.code = spec.code
            changed = True
        if existing.grade != GRADE_SLUG:
            existing.grade = GRADE_SLUG
            changed = True
        if existing.subject != SUBJECT_SLUG:
            existing.subject = SUBJECT_SLUG
            changed = True
        if existing.theme != spec.theme_slug:
            existing.theme = spec.theme_slug
            changed = True
        if changed:
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return existing

    return repository.create_curriculum_node(
        db,
        parent_id=None,
        node_type="folder",
        name=spec.folder_name,
        slug=spec.folder_slug,
        grade=GRADE_SLUG,
        subject=SUBJECT_SLUG,
        theme=spec.theme_slug,
        code=spec.code,
    )


def get_template_by_code(db: Session, code: str) -> models.YamlTemplate | None:
    return db.scalar(select(models.YamlTemplate).where(models.YamlTemplate.template_code == code))


def ensure_yaml_template(
    db: Session,
    *,
    spec: TemplateSpec,
    folder: models.CurriculumFolderNode,
    sample_payload: dict[str, Any],
) -> models.YamlTemplate:
    field_schema = build_field_schema(sample_payload)
    existing = get_template_by_code(db, spec.code)
    if existing is not None:
        existing.curriculum_folder_node_id = folder.id
        existing.title = spec.title
        existing.description = spec.description
        existing.field_schema_json = json.dumps(field_schema, ensure_ascii=False)
        existing.schema_version = "v1"
        existing.status = "active"
        existing.created_by = IMPORT_CREATED_BY
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    return repository.create_yaml_template(
        db,
        curriculum_folder_node_id=folder.id,
        template_code=spec.code,
        title=spec.title,
        description=spec.description,
        field_schema=field_schema,
        schema_version="v1",
        created_by=IMPORT_CREATED_BY,
    )


def get_yaml_instance_by_template_and_name(db: Session, template_id: str, instance_name: str) -> models.YamlInstance | None:
    stmt = select(models.YamlInstance).where(
        models.YamlInstance.template_id == template_id,
        models.YamlInstance.instance_name == instance_name,
    )
    return db.scalar(stmt)


def ensure_yaml_instance(
    db: Session,
    *,
    template: models.YamlTemplate,
    instance_name: str,
    payload: dict[str, Any],
) -> models.YamlInstance:
    rendered_yaml_text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    existing = get_yaml_instance_by_template_and_name(db, template.id, instance_name)
    if existing is not None:
        existing.status = "final"
        existing.values_json = json.dumps(payload, ensure_ascii=False)
        existing.rendered_yaml_text = rendered_yaml_text
        existing.created_by = IMPORT_CREATED_BY
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    return repository.create_yaml_instance(
        db,
        template_id=template.id,
        instance_name=instance_name,
        values=payload,
        rendered_yaml_text=rendered_yaml_text,
        status="final",
        created_by=IMPORT_CREATED_BY,
    )


def get_property_definition_by_node_and_path(
    db: Session,
    *,
    node_id: str,
    canonical_path: str,
) -> models.PropertyDefinition | None:
    stmt = select(models.PropertyDefinition).where(
        models.PropertyDefinition.defined_at_curriculum_node_id == node_id,
        models.PropertyDefinition.canonical_path == canonical_path,
    )
    return db.scalar(stmt)


def ensure_property_definition(
    db: Session,
    *,
    node_id: str,
    spec: PropertySpec,
) -> models.PropertyDefinition:
    parent_id: str | None = None
    if spec.parent_lookup is not None:
        parent_node_path, parent_canonical_path = spec.parent_lookup
        parent_node = get_constant_node_by_path(db, parent_node_path)
        parent = get_property_definition_by_node_and_path(
            db,
            node_id=parent_node.id,
            canonical_path=parent_canonical_path,
        )
        if parent is None:
            raise ValueError(f"Parent property bulunamadı: {parent_node_path} -> {parent_canonical_path}")
        parent_id = parent.id

    existing = get_property_definition_by_node_and_path(
        db,
        node_id=node_id,
        canonical_path=spec.canonical_path,
    )
    if existing is not None:
        existing.parent_property_id = parent_id
        existing.label = spec.label
        existing.description = spec.description
        existing.property_key = spec.property_key
        existing.data_type = spec.data_type
        existing.constraints_json = json.dumps(spec.constraints, ensure_ascii=False) if spec.constraints is not None else None
        existing.is_required = False
        existing.is_active = True
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    return repository.create_property_definition(
        db,
        defined_at_curriculum_node_id=node_id,
        parent_property_id=parent_id,
        label=spec.label,
        description=spec.description,
        property_key=spec.property_key,
        canonical_path=spec.canonical_path,
        data_type=spec.data_type,
        constraints=spec.constraints,
        is_required=False,
    )


def ensure_subject_property_definitions(db: Session) -> None:
    subject_node = get_constant_node_by_path(db, SUBJECT_PATH)
    for spec in SUBJECT_PROPERTY_SPECS:
        ensure_property_definition(db, node_id=subject_node.id, spec=spec)


def ensure_template_property_definitions(db: Session, folder: models.CurriculumFolderNode, spec: TemplateSpec) -> None:
    for property_spec in TEMPLATE_LOCAL_PROPERTY_SPECS.get(spec.code, ()):
        ensure_property_definition(db, node_id=folder.id, spec=property_spec)


def collect_generation_prompt_rules(payload: dict[str, Any]) -> list[str]:
    generation = get_path(payload, "context", "generation", default={}) or {}
    rules: list[Any] = []
    if isinstance(generation, dict):
        rules.extend(generation.get("kurallar") or [])
        ana_gorsel = generation.get("ana_gorsel") or {}
        sik_gorseli = generation.get("sik_gorseli") or {}
        if isinstance(ana_gorsel, dict):
            rules.extend(ana_gorsel.get("kurallar") or [])
        if isinstance(sik_gorseli, dict):
            rules.extend(sik_gorseli.get("kurallar") or [])
    return unique_strings(rules)


def extract_variant_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    result: dict[str, Any] = {}
    if "varyantlar" in payload:
        result["varyantlar"] = payload.get("varyantlar")
    if "varyant" in payload:
        result["varyant"] = payload.get("varyant")

    question_variants: list[dict[str, Any]] = []
    for question in get_path(payload, "context", "questions", default=[]) or []:
        if not isinstance(question, dict):
            continue
        subset = {
            key: question.get(key)
            for key in ("slot", "varyant_no", "varyant_adi", "varyant_kullanim", "aktif_varyantlar")
            if key in question
        }
        if subset:
            question_variants.append(subset)
    if question_variants:
        result["question_variants"] = question_variants

    visual_variants = {
        key: value
        for key, value in (payload.get("gorsel") or {}).items()
        if isinstance(key, str) and key.startswith("varyant_")
    } if isinstance(payload.get("gorsel"), dict) else {}
    if visual_variants:
        result["visual_variants"] = visual_variants

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    meta_variant = {
        key: meta.get(key)
        for key in ("varyant_kodu", "varyant_kodlari", "varyant_sayisi")
        if key in meta
    }
    if meta_variant:
        result["meta"] = meta_variant

    return result or None


def extract_variant_codes(payload: dict[str, Any]) -> list[str]:
    codes: list[Any] = []
    for item in payload.get("varyantlar") or []:
        if isinstance(item, dict):
            codes.append(item.get("kod"))
    for item in payload.get("varyant") or []:
        if isinstance(item, dict):
            codes.append(item.get("kod"))
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    if "varyant_kodu" in meta:
        codes.append(meta.get("varyant_kodu"))
    codes.extend(meta.get("varyant_kodlari") or [])
    return unique_strings(codes)


def extract_active_variant_codes(payload: dict[str, Any], codes: list[str]) -> list[str]:
    active: list[Any] = []
    for question in get_path(payload, "context", "questions", default=[]) or []:
        if isinstance(question, dict):
            active.extend(question.get("aktif_varyantlar") or [])
    if active:
        return unique_strings(active)

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    if meta.get("varyant_kodu"):
        return unique_strings([meta.get("varyant_kodu")])
    if meta.get("varyant_kodlari"):
        return unique_strings(list(meta.get("varyant_kodlari") or []))
    return unique_strings(codes)


def extract_subject_property_values(payload: dict[str, Any], filename: str) -> dict[str, Any]:
    meta = get_path(payload, "meta", default={}) or {}
    paragraph = get_path(payload, "format", "paragraph", default={}) or {}
    options = get_path(payload, "format", "options", default={}) or {}
    gorsel = get_path(payload, "gorsel", default={}) or {}
    ana_gorsel = gorsel.get("ana_gorsel") if isinstance(gorsel, dict) else {}
    sik_gorseli = gorsel.get("sik_gorseli") if isinstance(gorsel, dict) else {}
    tymm = get_path(payload, "tymm_uyum_kurallari", default={}) or {}
    tymm_allowed = tymm.get("izinli_icerik") if isinstance(tymm, dict) else {}
    allowed = get_path(payload, "izinli_icerikler", default={}) or {}

    concept_values = unique_strings(
        list((tymm_allowed or {}).get("kavramlar") or []) + list((allowed or {}).get("kavramlar") or [])
    )
    skill_values = unique_strings(
        list((tymm_allowed or {}).get("beceriler") or []) + list((allowed or {}).get("beceriler") or [])
    )
    operation_values = unique_strings(list((allowed or {}).get("soru_islemleri") or []))

    difficulty_level = meta.get("difficulty")
    if difficulty_level is None:
        difficulty_level = get_path(payload, "zorluk_seviyesi", "duzey")

    option_required = normalize_bool_like((sik_gorseli or {}).get("gerekli"))

    values: dict[str, Any] = {
        "option_count": get_path(payload, "format", "options", "count"),
        "visual.exists": True,
        "format_class": "metin-gorsel-soru-secenekler",
        "content.pattern_id": meta.get("id"),
        "content.source_filename": filename,
        "content.frequency_level": normalize_enum_text(meta.get("frequency")),
        "content.difficulty_level": normalize_enum_text(difficulty_level),
        "generation.image_type": normalize_enum_text(get_path(payload, "context", "generation", "image_type")),
        "generation.structure_rules": unique_strings(list(get_path(payload, "context", "generation", "structure", default=[]) or [])),
        "generation.prompt_rules": collect_generation_prompt_rules(payload),
        "question.question_count": get_path(payload, "context", "question_count"),
        "question.slot_types": unique_strings(
            [question.get("type") for question in get_path(payload, "context", "questions", default=[]) or [] if isinstance(question, dict)]
        ),
        "paragraph.required": paragraph.get("required"),
        "paragraph.word_count_min": paragraph.get("word_count_min"),
        "paragraph.word_count_max": paragraph.get("word_count_max"),
        "paragraph.sentence_count_min": paragraph.get("sentence_count_min"),
        "paragraph.sentence_count_max": paragraph.get("sentence_count_max"),
        "option.labels": list(options.get("labels") or []),
        "option.correct_count": options.get("correct_count"),
        "option.style": normalize_enum_text(options.get("style")),
        "option.word_count_min": options.get("word_count_min"),
        "option.word_count_max": options.get("word_count_max"),
        "visual.main_style": normalize_enum_text((ana_gorsel or {}).get("stil")),
        "visual.main_size": normalize_enum_text((ana_gorsel or {}).get("boyut")),
        "visual.option_required": option_required,
        "visual.option_rules": unique_strings(list((sik_gorseli or {}).get("kurallar") or [])),
        "answer.rules": unique_strings(list(get_path(payload, "dogru_cevap", "kurallar", default=[]) or [])),
        "distractor.rules": unique_strings(list(get_path(payload, "distractors", "kurallar", default=[]) or [])),
        "distractor.forbidden_rules": unique_strings(list(get_path(payload, "distractors", "yasaklar", default=[]) or [])),
        "curriculum.learning_outcome": get_path(payload, "tymm_uyum_kurallari", "ogrenme_ciktisi"),
        "curriculum.theme_boundary": get_path(payload, "tymm_uyum_kurallari", "tema_siniri"),
        "curriculum.allowed_concepts": concept_values,
        "curriculum.allowed_skills": skill_values,
        "curriculum.allowed_operations": operation_values,
    }
    return {key: value for key, value in values.items() if value not in (None, "", [])}


def extract_template_property_values(spec: TemplateSpec, payload: dict[str, Any]) -> dict[str, Any]:
    options = get_path(payload, "format", "options", default={}) or {}
    variant_codes = extract_variant_codes(payload)
    active_variant_codes = extract_active_variant_codes(payload, variant_codes)
    variant_payload = extract_variant_payload(payload)
    variant_enabled = bool(variant_codes or active_variant_codes or variant_payload)

    raw_values: dict[str, Any] = {
        "option.content_type": normalize_enum_text(options.get("content_type")),
        "option.render_mode": normalize_enum_text(options.get("render_mode")),
        "option.presentation_mode": normalize_enum_text(options.get("presentation")),
        "option.personas": options.get("personas"),
        "variant.enabled": variant_enabled,
        "variant.codes": variant_codes,
        "variant.active_codes": active_variant_codes,
        "variant.definitions": variant_payload,
        "difficulty.explanation": get_path(payload, "zorluk_seviyesi", "aciklama"),
    }

    allowed_paths = {item.canonical_path for item in TEMPLATE_LOCAL_PROPERTY_SPECS.get(spec.code, ())}
    values: dict[str, Any] = {}
    for canonical_path, value in raw_values.items():
        if canonical_path not in allowed_paths:
            continue
        if value in (None, "", []):
            continue
        values[canonical_path] = value
    return values


def upsert_instance_property_value(
    db: Session,
    *,
    instance_id: str,
    property_definition_id: str,
    value: Any,
) -> models.YamlInstancePropertyValue:
    stmt = select(models.YamlInstancePropertyValue).where(
        models.YamlInstancePropertyValue.instance_id == instance_id,
        models.YamlInstancePropertyValue.property_definition_id == property_definition_id,
    )
    existing = db.scalar(stmt)
    if existing is not None:
        existing.value_json = json.dumps(value, ensure_ascii=False)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    row = models.YamlInstancePropertyValue(
        instance_id=instance_id,
        property_definition_id=property_definition_id,
        value_json=json.dumps(value, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def ensure_instance_property_values(
    db: Session,
    *,
    folder: models.CurriculumFolderNode,
    instance: models.YamlInstance,
    payload: dict[str, Any],
    filename: str,
    spec: TemplateSpec,
) -> int:
    effective_properties = {
        row.canonical_path: row
        for row in repository.list_effective_properties(db, folder.id)
    }
    values = extract_subject_property_values(payload, filename)
    values.update(extract_template_property_values(spec, payload))

    updated = 0
    for canonical_path, value in values.items():
        property_definition = effective_properties.get(canonical_path)
        if property_definition is None:
            raise ValueError(f"Effective property bulunamadı: {folder.path} -> {canonical_path}")
        upsert_instance_property_value(
            db,
            instance_id=instance.id,
            property_definition_id=property_definition.id,
            value=value,
        )
        updated += 1
    return updated


def import_ortak_yaml() -> None:
    payloads = load_yaml_files()
    validate_bucket_count(payloads)
    by_file = validate_template_mapping(payloads)

    with SessionLocal() as db:
        subject_node = get_constant_node_by_path(db, SUBJECT_PATH)
        ensure_subject_property_definitions(db)

        folders_touched: list[str] = []
        templates_touched: list[str] = []
        instances_touched: list[str] = []
        property_value_count = 0

        for spec in TEMPLATE_SPECS:
            sample_payload = payloads[spec.filenames[0]]
            folder = ensure_folder_node(db, spec)
            ensure_template_property_definitions(db, folder, spec)
            template = ensure_yaml_template(
                db,
                spec=spec,
                folder=folder,
                sample_payload=sample_payload,
            )

            folders_touched.append(folder.id)
            templates_touched.append(template.id)

            for filename in spec.filenames:
                payload = payloads[filename]
                instance_name = normalize_text(get_path(payload, "meta", "id"))
                if not instance_name:
                    raise ValueError(f"meta.id boş olamaz: {filename}")
                instance = ensure_yaml_instance(
                    db,
                    template=template,
                    instance_name=instance_name,
                    payload=payload,
                )
                property_value_count += ensure_instance_property_values(
                    db,
                    folder=folder,
                    instance=instance,
                    payload=payload,
                    filename=filename,
                    spec=spec,
                )
                instances_touched.append(instance.id)

        folder_count = db.scalar(
            select(func.count()).select_from(models.CurriculumFolderNode).where(models.CurriculumFolderNode.code.in_([spec.code for spec in TEMPLATE_SPECS]))
        )
        template_count = db.scalar(
            select(func.count()).select_from(models.YamlTemplate).where(models.YamlTemplate.created_by == IMPORT_CREATED_BY)
        )
        instance_count = db.scalar(
            select(func.count()).select_from(models.YamlInstance).where(models.YamlInstance.created_by == IMPORT_CREATED_BY)
        )
        property_value_total = db.scalar(select(func.count()).select_from(models.YamlInstancePropertyValue))

        print("ortak YAML import tamamlandı")
        print(f"subject_node={subject_node.path}")
        print(f"yaml_files={len(payloads)}")
        print(f"template_specs={len(TEMPLATE_SPECS)}")
        print(f"folders_import_owned={folder_count}")
        print(f"templates_import_owned={template_count}")
        print(f"instances_import_owned={instance_count}")
        print(f"folders_touched={len(set(folders_touched))}")
        print(f"templates_touched={len(set(templates_touched))}")
        print(f"instances_touched={len(set(instances_touched))}")
        print(f"instance_property_values_upserted={property_value_count}")
        print(f"yaml_instance_property_values_total={property_value_total}")


if __name__ == "__main__":
    import_ortak_yaml()
