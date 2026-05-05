"""Legacy pipeline service — in-process geometry (pomodoro) + turkce (agentic).

Geometri pipeline'ı thread'de in-process koşar (pomodoro). Türkçe pipeline'ı her run için
ayrı subprocess ile çalışır (agentic global state thread-safe değil). Batch akışında bir
asyncio.Semaphore alt-run sayısını sınırlar. Stdout/stderr satır satır yakalanıp DB'ye +
SSE stream'ine yazılır.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml as _yaml
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db import repository
from app.db.database import SessionLocal
from app.db.models import Pipeline
from app.services.legacy_session_output_store import StoredOutputFile, get_legacy_output_store
from app.services import log_stream_service
from app.services.pipeline_log_service import write_pipeline_log


LegacyKind = Literal["geometry", "turkce"]


@dataclass(frozen=True)
class LegacyPipelineDef:
    kind: LegacyKind
    label: str


LEGACY_PIPELINES: dict[LegacyKind, LegacyPipelineDef] = {
    "geometry": LegacyPipelineDef(kind="geometry", label="Geometri"),
    "turkce": LegacyPipelineDef(kind="turkce", label="Türkçe"),
}


_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _clean_yaml_path(raw: str) -> str:
    rel = (raw or "").strip().replace("\\", "/").lstrip("/")
    candidate = Path(rel)
    if not rel or rel in {".", ".."}:
        raise ValueError("Geçersiz YAML yolu")
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("Geçersiz YAML yolu")
    return candidate.as_posix()


def _ensure_yaml_extension(name: str) -> str:
    if Path(name).suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("Yalnızca .yaml/.yml uzantıları kabul edilir")
    return name


def _validate_yaml_text(kind: LegacyKind, text: str) -> dict[str, Any]:
    try:
        data = _yaml.safe_load(text)
    except _yaml.YAMLError as exc:
        raise ValueError(f"YAML parse hatası: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("YAML kök öğesi sözlük olmalı")
    schema_errors = _check_kind_schema(kind, data)
    if schema_errors:
        raise ValueError(schema_errors[0].message)
    return data


def _runtime_yaml_dir(kind: LegacyKind, settings: Settings) -> Path:
    if kind == "turkce":
        # Türkçe config'lerinde relative path kullanımı için config dizininde kal.
        return settings.legacy_turkce_configs_dir
    return settings.legacy_state_dir / "runtime_yaml" / kind


def _materialize_runtime_yaml(kind: LegacyKind, yaml_path: str, content: str, settings: Settings) -> Path:
    root = _runtime_yaml_dir(kind, settings)
    root.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(yaml_path).stem or "legacy")
    fd, temp_path = tempfile.mkstemp(prefix=f"_db_{stem}_", suffix=".yaml", dir=str(root))
    os.close(fd)
    target = Path(temp_path)
    target.write_text(content, encoding="utf-8")
    return target


def _get_yaml_row(kind: LegacyKind, yaml_path: str):
    safe_path = _clean_yaml_path(yaml_path)
    with SessionLocal() as db:
        row = repository.get_legacy_yaml_instance_by_path(db, kind=kind, yaml_path=safe_path)
        if row is None:
            raise FileNotFoundError(f"YAML bulunamadı: {safe_path}")
        return row


def _next_unique_yaml_path(kind: LegacyKind, safe_name: str) -> str:
    path = Path(safe_name)
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    with SessionLocal() as db:
        if repository.get_legacy_yaml_instance_by_path(db, kind=kind, yaml_path=safe_name) is None:
            return safe_name
        n = 1
        while True:
            candidate_name = f"{stem}__{n}{suffix}"
            candidate = (parent / candidate_name).as_posix() if str(parent) not in {"", "."} else candidate_name
            if repository.get_legacy_yaml_instance_by_path(db, kind=kind, yaml_path=candidate) is None:
                return candidate
            n += 1


def _is_kind_enabled(kind: LegacyKind, settings: Settings) -> bool:
    """Vendor'lı kodlar her zaman erişilebilir; koşul API key ve ilgili içerik dizinleri."""
    if kind not in LEGACY_PIPELINES:
        return False
    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        return False
    if kind == "geometry":
        return True
    if kind == "turkce":
        required_dirs = (
            settings.legacy_turkce_configs_dir,
            settings.legacy_turkce_templates_dir,
        )
        return all(path.exists() and path.is_dir() for path in required_dirs)
    return False


def _apply_legacy_environment(settings: Settings) -> None:
    """Vendored legacy modules read a few paths from env at import time."""
    os.environ["LEGACY_STATE_DIR"] = str(settings.legacy_state_dir)
    os.environ["LEGACY_TURKCE_CONFIGS_DIR"] = str(settings.legacy_turkce_configs_dir)
    os.environ["LEGACY_TURKCE_TEMPLATES_DIR"] = str(settings.legacy_turkce_templates_dir)
    os.environ["LEGACY_TURKCE_MEB_BOOKS_DIR"] = str(settings.legacy_turkce_meb_books_dir)
    os.environ["LEGACY_TURKCE_DATA_DIR"] = str(settings.legacy_turkce_data_dir)


def list_pipelines(settings: Settings | None = None) -> list[dict[str, Any]]:
    s = settings or get_settings()
    _apply_legacy_environment(s)
    out: list[dict[str, Any]] = []
    for kind, defn in LEGACY_PIPELINES.items():
        out.append(
            {
                "kind": kind,
                "label": defn.label,
                "enabled": _is_kind_enabled(kind, s),
                "default_params": {"difficulty": "orta"} if kind == "geometry" else {},
            }
        )
    return out


def list_yaml_files(kind: LegacyKind, settings: Settings | None = None) -> list[str]:
    _ = settings  # Backward-compatible signature
    with SessionLocal() as db:
        rows = repository.list_legacy_yaml_instances(db, kind)
        return [row.yaml_path for row in rows]


def migrate_file_based_yamls_to_db(settings: Settings | None = None) -> dict[str, Any]:
    s = settings or get_settings()

    sources: list[tuple[LegacyKind, Path, str]] = [
        ("geometry", s.legacy_geo_yaml_dir, ""),
        ("turkce", s.legacy_turkce_configs_dir, ""),
        ("geometry", s.legacy_uploads_dir / "geometry", "uploads/"),
        ("turkce", s.legacy_uploads_dir / "turkce", "uploads/"),
    ]

    migrated = 0
    skipped_invalid = 0
    skipped_unreadable = 0
    scanned = 0

    with SessionLocal() as db:
        for kind, root, prefix in sources:
            if not root.exists() or not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in {".yaml", ".yml"}:
                    continue
                scanned += 1
                try:
                    text = path.read_text(encoding="utf-8")
                except Exception:
                    skipped_unreadable += 1
                    continue
                try:
                    _validate_yaml_text(kind, text)
                except ValueError:
                    skipped_invalid += 1
                    continue

                rel = path.relative_to(root).as_posix()
                yaml_path = _clean_yaml_path(prefix + rel if prefix else rel)
                repository.upsert_legacy_yaml_instance(
                    db,
                    kind=kind,
                    yaml_path=yaml_path,
                    content_text=text,
                )
                migrated += 1

    return {
        "scanned": scanned,
        "migrated": migrated,
        "skipped_invalid": skipped_invalid,
        "skipped_unreadable": skipped_unreadable,
    }


@dataclass
class _ExtractionIssue:
    type: Literal["parse", "schema", "semantic"]
    message: str
    location: str | None = None


@dataclass
class _ExtractionOutcome:
    filename: str
    yaml_path: str | None
    errors: list[_ExtractionIssue]
    warnings: list[_ExtractionIssue]


def _check_kind_schema(kind: LegacyKind, data: dict[str, Any]) -> list[_ExtractionIssue]:
    errors: list[_ExtractionIssue] = []
    if kind == "geometry":
        if not isinstance(data.get("meta"), dict) or not isinstance(data.get("context"), dict):
            errors.append(_ExtractionIssue(
                type="schema",
                message="Geometri YAML'ı `meta` ve `context` bloklarını içermeli",
            ))
    elif kind == "turkce":
        has_generation_entry = any(k in data for k in ("template", "generation_plan", "context_generation_plan"))
        has_topic_source = any(k in data for k in ("topic", "topics_file"))
        if not (has_generation_entry and has_topic_source):
            errors.append(_ExtractionIssue(
                type="schema",
                message="Türkçe YAML'ı `template`/`generation_plan`/`context_generation_plan` ve `topic`/`topics_file` içermeli",
            ))
    return errors


def _semantic_check(kind: LegacyKind, content: str, settings: Settings) -> list[_ExtractionIssue]:
    """Run kind-specific semantic checks on a saved YAML.

    Failure here is reported as a non-fatal warning — the file is already valid YAML
    and matches the structural schema; semantic problems may surface only at run time.
    """
    issues: list[_ExtractionIssue] = []
    if kind == "geometry":
        temp_path: Path | None = None
        try:
            temp_path = _materialize_runtime_yaml(kind, "_semantic_check.yaml", content, settings)
            from legacy_app.geometri.pomodoro.yaml_loader import load_and_parse_template
            load_and_parse_template(str(temp_path))
        except Exception as exc:
            issues.append(_ExtractionIssue(type="semantic", message=str(exc)))
        finally:
            if temp_path is not None:
                with contextlib.suppress(Exception):
                    temp_path.unlink(missing_ok=True)
    return issues


def extract_uploaded_yaml(
    kind: LegacyKind,
    *,
    filename: str,
    content: bytes,
    settings: Settings | None = None,
    overwrite: bool = True,
) -> _ExtractionOutcome:
    """Validate + persist a single uploaded YAML, collecting errors instead of raising.

    Runs three layers: parse (UTF-8/YAML/extension), schema (kind-specific structure),
    semantic (kind-specific deeper load). Parse + schema failures prevent persistence;
    semantic failures are warnings (file is still saved).
    """
    s = settings or get_settings()
    errors: list[_ExtractionIssue] = []
    warnings: list[_ExtractionIssue] = []

    if kind not in LEGACY_PIPELINES:
        errors.append(_ExtractionIssue(type="parse", message=f"Bilinmeyen pipeline türü: {kind}"))
        return _ExtractionOutcome(filename=filename, yaml_path=None, errors=errors, warnings=warnings)

    if len(content) > 2 * 1024 * 1024:
        errors.append(_ExtractionIssue(type="parse", message="YAML dosyası 2 MB sınırını aşıyor"))
        return _ExtractionOutcome(filename=filename, yaml_path=None, errors=errors, warnings=warnings)

    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        errors.append(_ExtractionIssue(type="parse", message="Geçersiz dosya adı"))
        return _ExtractionOutcome(filename=filename, yaml_path=None, errors=errors, warnings=warnings)
    if Path(safe_name).suffix.lower() not in {".yaml", ".yml"}:
        errors.append(_ExtractionIssue(type="parse", message="Yalnızca .yaml/.yml uzantıları kabul edilir"))
        return _ExtractionOutcome(filename=filename, yaml_path=None, errors=errors, warnings=warnings)

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(_ExtractionIssue(type="parse", message=f"YAML UTF-8 değil: {exc}"))
        return _ExtractionOutcome(filename=filename, yaml_path=None, errors=errors, warnings=warnings)

    try:
        _validate_yaml_text(kind, text)
    except ValueError as exc:
        msg = str(exc)
        err_type: Literal["parse", "schema", "semantic"] = "schema"
        if "parse hatası" in msg or "UTF-8" in msg:
            err_type = "parse"
        errors.append(_ExtractionIssue(type=err_type, message=msg))
        return _ExtractionOutcome(filename=filename, yaml_path=None, errors=errors, warnings=warnings)

    base_name = _ensure_yaml_extension(_clean_yaml_path(safe_name))
    yaml_path = base_name if overwrite else _next_unique_yaml_path(kind, base_name)

    with SessionLocal() as db:
        repository.upsert_legacy_yaml_instance(
            db,
            kind=kind,
            yaml_path=yaml_path,
            content_text=text,
        )

    warnings.extend(_semantic_check(kind, text, s))
    return _ExtractionOutcome(
        filename=filename,
        yaml_path=yaml_path,
        errors=errors,
        warnings=warnings,
    )


def extract_uploaded_yamls(
    kind: LegacyKind,
    *,
    files: list[tuple[str, bytes]],
    settings: Settings | None = None,
) -> list[_ExtractionOutcome]:
    """Run extract_uploaded_yaml for each file; partial success — never raises per-file."""
    s = settings or get_settings()
    outcomes: list[_ExtractionOutcome] = []
    for filename, content in files:
        outcomes.append(
            extract_uploaded_yaml(
                kind, filename=filename, content=content, settings=s, overwrite=False
            )
        )
    return outcomes


def save_uploaded_yaml(
    kind: LegacyKind,
    *,
    filename: str,
    content: bytes,
    settings: Settings | None = None,
) -> str:
    """Single-file legacy upload; raises ValueError on the first error.

    Kept for backwards compatibility with the existing single-upload endpoint.
    """
    outcome = extract_uploaded_yaml(
        kind, filename=filename, content=content, settings=settings, overwrite=True
    )
    if outcome.errors:
        raise ValueError(outcome.errors[0].message)
    assert outcome.yaml_path is not None
    return outcome.yaml_path


def inspect_yaml(
    kind: LegacyKind,
    yaml_path: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Bir YAML için varyant bilgisini çıkarır.

    Geometri tarafında pomodoro yaml_loader + variant_rotation kullanılır. Türkçe için
    boş varyant listesi döner ama dosyanın var/geçerli olduğu kontrol edilir.
    """
    s = settings or get_settings()
    row = _get_yaml_row(kind, yaml_path)
    safe_path = _clean_yaml_path(yaml_path)

    if kind == "geometry":
        temp_path: Path | None = None
        try:
            temp_path = _materialize_runtime_yaml(kind, safe_path, row.content_text, s)
            from legacy_app.geometri.pomodoro.yaml_loader import load_and_parse_template
            from legacy_app.geometri.pomodoro.variant_rotation import get_variant_names

            template = load_and_parse_template(str(temp_path))
            names = get_variant_names(template)
        except Exception:
            names = []
        finally:
            if temp_path is not None:
                with contextlib.suppress(Exception):
                    temp_path.unlink(missing_ok=True)
        return {
            "kind": kind,
            "yaml_path": safe_path,
            "has_variants": bool(names),
            "variant_count": len(names),
            "variant_names": names,
        }

    return {
        "kind": kind,
        "yaml_path": safe_path,
        "has_variants": False,
        "variant_count": 0,
        "variant_names": [],
    }


def read_yaml_content(
    kind: LegacyKind,
    yaml_path: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    _ = settings  # Backward-compatible signature
    row = _get_yaml_row(kind, yaml_path)
    return {
        "kind": kind,
        "yaml_path": row.yaml_path,
        "content": row.content_text,
        "is_repo_yaml": False,
    }


def delete_yaml_content(
    kind: LegacyKind,
    yaml_path: str,
) -> bool:
    safe_path = _clean_yaml_path(yaml_path)
    with SessionLocal() as db:
        return repository.delete_legacy_yaml_instance(db, kind=kind, yaml_path=safe_path)


def write_yaml_content(
    kind: LegacyKind,
    yaml_path: str,
    content: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """YAML içeriğini veritabanında günceller (dosya sistemi yerine DB-first)."""
    s = settings or get_settings()

    safe_path = _clean_yaml_path(yaml_path)
    _validate_yaml_text(kind, content)

    backup_root = s.legacy_state_dir / "yaml_backups" / kind
    backup_root.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        row = repository.get_legacy_yaml_instance_by_path(db, kind=kind, yaml_path=safe_path)
        if row is None:
            raise FileNotFoundError(f"YAML bulunamadı: {safe_path}")
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        backup_target = backup_root / f"{Path(safe_path).stem}.{ts}.bak.yaml"
        with contextlib.suppress(Exception):
            backup_target.write_text(row.content_text or "", encoding="utf-8")
        repository.upsert_legacy_yaml_instance(
            db,
            kind=kind,
            yaml_path=safe_path,
            content_text=content,
        )

    return {
        "kind": kind,
        "yaml_path": safe_path,
        "content": content,
        "is_repo_yaml": False,
    }


def _create_ephemeral_run_dir(kind: LegacyKind, run_id: str, settings: Settings) -> Path:
    root = settings.legacy_state_dir / "legacy_run_tmp"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{kind}_{run_id[:8]}_", dir=str(root)))


def _collect_storeable_output_files(run_dir: Path) -> list[StoredOutputFile]:
    if not run_dir.exists() or not run_dir.is_dir():
        return []
    output: list[StoredOutputFile] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in {".json", ".html", ".png"}:
            continue
        try:
            content = path.read_bytes()
        except Exception:
            continue
        rel = path.relative_to(run_dir).as_posix()
        output.append(
            StoredOutputFile(
                rel_path=rel,
                content=content,
                mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                size=len(content),
            )
        )
    return output


# -----------------------------------------------------------------------------
# Stream capture: stdout/stderr satırlarını DB + SSE'ye besle.
# -----------------------------------------------------------------------------


_SELF_PREFIX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T[\d:.+\-]+\s+\[[A-Z]+\]\s+\[legacy_(stdout|stderr|runner)\]\s"
)
_RATE_CAP_PER_SEC = 50
_MAX_LINE_LEN = 4096


def _detach_stale_logging_handlers(captures: tuple[io.TextIOBase, ...]) -> None:
    """Vendored kodlar (özellikle agentic) çalışırken `logging.StreamHandler()` veya
    `logging.basicConfig` çağırırsa, default sys.stderr/stdout o sırada
    capture'a bağlı olduğundan handler stale capture'a sabitlenir. Run bittikten
    sonra root logger ve `agentic` logger'ı tarayıp bu capture'lara bağlı handler'ları
    çıkar — sonraki run'lara sızmamaları için.
    """
    import logging as _logging

    capture_set = set(id(c) for c in captures)
    for name in (None, "agentic"):
        logger = _logging.getLogger(name) if name else _logging.getLogger()
        for handler in list(logger.handlers):
            stream = getattr(handler, "stream", None)
            if stream is not None and id(stream) in capture_set:
                logger.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass


class _RateLimiter:
    """Per-instance simple sliding window rate limiter (1s window)."""

    def __init__(self, max_per_sec: int) -> None:
        self._max = max_per_sec
        self._window_start = 0.0
        self._count = 0
        self._dropped = 0
        self._lock = threading.Lock()

    def allow(self) -> tuple[bool, int]:
        """Return (allowed, dropped_since_last_allowed). dropped is 0 unless
        we just transitioned out of a saturated window."""
        with self._lock:
            now = time.monotonic()
            if now - self._window_start >= 1.0:
                dropped = self._dropped
                self._window_start = now
                self._count = 1
                self._dropped = 0
                return True, dropped
            if self._count < self._max:
                self._count += 1
                return True, 0
            self._dropped += 1
            return False, 0


class _StreamCapture(io.TextIOBase):
    """Per-run stdout/stderr capture. Her newline'da publish'i tetikler.

    Defensive guards:
    - Re-entrancy: aynı thread içinden tekrar girişte capture'a alma (loop kırma).
    - Self-format drop: kendi `<ts> [LEVEL] [legacy_*]` formatımızla başlayan
      satırlar capture'a geri sızmışsa drop et (loop kırma).
    - Rate cap: per-run sn'de _RATE_CAP_PER_SEC üstündeki satırlar atılır,
      pencere bitince sayım özet olarak akar.
    - Length cap: tek satır _MAX_LINE_LEN'i geçerse trunc edilir.

    `loop.call_soon_threadsafe` ile thread-safe; pomodoro/agentic asyncio.to_thread
    içinde koştuğu için event loop'a güvenli teslim eder.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        run_id: str,
        mode: str,
        component: str,
        level: str,
        stream_key: str | None,
    ) -> None:
        self._loop = loop
        self._run_id = run_id
        self._mode = mode
        self._component = component
        self._level = level
        self._stream_key = stream_key
        self._buffer = ""
        self._tls = threading.local()
        self._limiter = _RateLimiter(_RATE_CAP_PER_SEC)

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        if not isinstance(s, str):
            s = str(s)
        # Re-entrancy guard: bir feedback path bizi tekrar çağırırsa orijinal
        # stdout'a sessizce drop et.
        if getattr(self._tls, "in_write", False):
            return len(s)
        self._tls.in_write = True
        try:
            self._buffer += s
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._dispatch(line)
            return len(s)
        finally:
            self._tls.in_write = False

    def flush(self) -> None:
        if getattr(self._tls, "in_write", False):
            return
        if self._buffer:
            self._tls.in_write = True
            try:
                line, self._buffer = self._buffer, ""
                self._dispatch(line)
            finally:
                self._tls.in_write = False

    def _dispatch(self, line: str) -> None:
        line = line.rstrip("\r")
        if not line:
            return
        # Kendi formatımızla başlayan satırlar — feedback loop kanıtı.
        if _SELF_PREFIX_RE.match(line):
            return
        if len(line) > _MAX_LINE_LEN:
            line = line[:_MAX_LINE_LEN] + " …[truncated]"
        allowed, dropped_summary = self._limiter.allow()
        if not allowed:
            return
        if dropped_summary:
            self._safe_emit(
                f"[rate-cap] previous 1s window dropped {dropped_summary} lines (cap={_RATE_CAP_PER_SEC}/s)"
            )
        self._safe_emit(line)

    def _safe_emit(self, line: str) -> None:
        try:
            self._loop.call_soon_threadsafe(
                _emit_log_line,
                self._run_id,
                self._mode,
                self._component,
                self._level,
                line,
                self._stream_key,
            )
        except RuntimeError:
            pass


def _emit_log_line(
    run_id: str,
    mode: str,
    component: str,
    level: str,
    message: str,
    stream_key: str | None,
) -> None:
    """Event loop içinde yakalanan stdout/stderr satırını DB + SSE'ye yazar.

    `write_pipeline_log()` stdout'a da print eder. Legacy runner aktifken stdout
    global capture altında olduğundan burada print etmek aynı log satırını yeniden
    capture edip çoğaltır.
    """
    db = SessionLocal()
    try:
        repository.record_pipeline_log(
            db,
            mode=mode,
            level=level,
            component=component,
            message=message,
            pipeline_id=run_id,
            sub_pipeline_id=None,
            details=None,
        )
        if stream_key:
            ts = datetime.now(timezone.utc).isoformat()
            line = f"{ts} [{level.upper()}] [{component}] {message}"
            log_stream_service.publish(stream_key, line)
    except Exception:
        try:
            if stream_key:
                log_stream_service.publish(stream_key, f"[{level.upper()}] [{component}] {message}")
        except Exception:
            pass
    finally:
        db.close()


# -----------------------------------------------------------------------------
# In-process runners
# -----------------------------------------------------------------------------


def _run_geometry_sync(
    *,
    yaml_abs: Path,
    run_dir: Path,
    difficulty: str,
    variant_name: str | None,
) -> None:
    """Geometri pipeline'ı (pomodoro.graph.run) sync olarak çalıştırır."""
    from legacy_app.geometri.pomodoro.graph import run as pomodoro_run

    pomodoro_run(
        yaml_path=str(yaml_abs),
        difficulty=difficulty,
        output_dir=str(run_dir),
        variant_name=variant_name,
    )


def _prepare_turkce_tmp_yaml(yaml_abs: Path, run_dir: Path) -> Path:
    """Türkçe pipeline için orijinal config'i geçici YAML'e kopyalar ve output.dir
    alanını run_dir'e override eder. Geçici dosya orijinal YAML'in dizininde tutulur
    (relative path'ler korunsun)."""
    with yaml_abs.open("r", encoding="utf-8") as fh:
        config_data = _yaml.safe_load(fh) or {}
    if not isinstance(config_data, dict):
        config_data = {}
    output_block = config_data.get("output")
    if not isinstance(output_block, dict):
        output_block = {}
        config_data["output"] = output_block
    output_block["dir"] = str(run_dir)

    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f"_legacy_run_{yaml_abs.stem}_",
        suffix=".yaml",
        dir=str(yaml_abs.parent),
    )
    os.close(fd)
    tmp_path = Path(tmp_path_str)
    with tmp_path.open("w", encoding="utf-8") as fh:
        _yaml.safe_dump(config_data, fh, allow_unicode=True, sort_keys=False)
    return tmp_path


def _pump_pipe(stream, capture: "_StreamCapture") -> None:
    """Subprocess pipe'ından satır okuyup capture'a iletir."""
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            capture.write(line)
    except Exception:
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _run_turkce_subprocess(
    *,
    yaml_abs: Path,
    run_dir: Path,
    stdout_capture: "_StreamCapture",
    stderr_capture: "_StreamCapture",
    timeout_seconds: int,
) -> None:
    """Türkçe pipeline'ı ayrı subprocess'te çalıştırır (agentic global state thread-safe değil)."""
    tmp_path = _prepare_turkce_tmp_yaml(yaml_abs, run_dir)
    try:
        env = os.environ.copy()
        proc = subprocess.Popen(
            [sys.executable, "-m", "legacy_app.kadir_hoca.agentic", "--config", str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
        )

        t_out = threading.Thread(
            target=_pump_pipe, args=(proc.stdout, stdout_capture), daemon=True
        )
        t_err = threading.Thread(
            target=_pump_pipe, args=(proc.stderr, stderr_capture), daemon=True
        )
        t_out.start()
        t_err.start()

        try:
            exit_code = proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise RuntimeError(f"agentic subprocess timeout ({timeout_seconds}s)")
        finally:
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            stdout_capture.flush()
            stderr_capture.flush()

        if exit_code != 0:
            raise RuntimeError(f"agentic exit_code={exit_code}")
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Service
# -----------------------------------------------------------------------------


@dataclass
class _BatchSubRun:
    run_id: str
    kind: LegacyKind
    yaml_path: str
    yaml_content: str
    session_id: str
    variant_name: str | None
    params: dict[str, Any]
    run_dir: Path


class LegacyPipelineService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.settings = settings or get_settings()
        _apply_legacy_environment(self.settings)

    async def run_batch(
        self,
        *,
        kind: LegacyKind,
        session_id: str,
        items: list[dict[str, Any]],
        parallelism: int | None,
        stream_key: str | None,
    ) -> dict[str, Any]:
        if kind not in LEGACY_PIPELINES:
            raise ValueError(f"Bilinmeyen pipeline: {kind}")
        if not _is_kind_enabled(kind, self.settings):
            raise RuntimeError(
                f"{kind} legacy pipeline yapılandırılmamış (GOOGLE_API_KEY ve gerekli dizinler)"
            )
        if not items:
            raise ValueError("items boş olamaz")

        batch_id = uuid.uuid4().hex[:12]
        mode = f"legacy_{kind}"

        sub_runs: list[_BatchSubRun] = []
        for item in items:
            yaml_path = _clean_yaml_path(item.get("yaml_path") or "")
            params = dict(item.get("params") or {})
            variants: list[str] = list(item.get("variants") or [])
            row = repository.get_legacy_yaml_instance_by_path(self.db, kind=kind, yaml_path=yaml_path)
            if row is None:
                raise FileNotFoundError(f"YAML bulunamadı: {yaml_path}")

            variant_iter: list[str | None] = variants if variants else [None]
            for variant_name in variant_iter:
                row_params = dict(params)
                if variant_name:
                    row_params["variant_name"] = variant_name
                pipeline_row = repository.create_pipeline(
                    self.db,
                    yaml_filename=yaml_path,
                    retry_config={
                        "params": row_params,
                        "batch_id": batch_id,
                        "variant_name": variant_name,
                    },
                )
                pipeline_row.mode = mode
                self.db.add(pipeline_row)
                self.db.commit()
                self.db.refresh(pipeline_row)
                run_id = pipeline_row.id
                sub_runs.append(
                    _BatchSubRun(
                        run_id=run_id,
                        kind=kind,
                        yaml_path=yaml_path,
                        yaml_content=row.content_text,
                        session_id=session_id,
                        variant_name=variant_name,
                        params=row_params,
                        run_dir=_create_ephemeral_run_dir(kind, run_id, self.settings),
                    )
                )

        write_pipeline_log(
            self.db,
            mode=mode,
            component="legacy_runner",
            message=(
                f"Batch başlatılıyor: kind={kind} batch_id={batch_id} "
                f"sub_run={len(sub_runs)} parallelism={parallelism or 'auto'}"
            ),
            pipeline_id=sub_runs[0].run_id if sub_runs else None,
            sub_pipeline_id=None,
            level="info",
            details={
                "batch_id": batch_id,
                "run_ids": [r.run_id for r in sub_runs],
            },
            stream_key=stream_key,
        )

        timeout_seconds = self.settings.legacy_timeout_seconds
        loop = asyncio.get_running_loop()
        max_workers = parallelism or min(len(sub_runs), 4)
        max_workers = max(1, max_workers)
        semaphore = asyncio.Semaphore(max_workers)

        async def _run_one(sub: _BatchSubRun) -> None:
            async with semaphore:
                await self._execute_sub_run(
                    sub=sub,
                    mode=mode,
                    loop=loop,
                    stream_key=stream_key,
                    timeout_seconds=timeout_seconds,
                    batch_id=batch_id,
                )

        async def _supervise_batch() -> None:
            try:
                await asyncio.gather(*[_run_one(sub) for sub in sub_runs])
            finally:
                if stream_key:
                    try:
                        log_stream_service.publish_done(stream_key)
                    except Exception:
                        pass

        task = asyncio.create_task(_supervise_batch())
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

        return {
            "batch_id": batch_id,
            "run_ids": [r.run_id for r in sub_runs],
            "status": "running",
            "stream_key": stream_key,
        }

    async def _execute_sub_run(
        self,
        *,
        sub: _BatchSubRun,
        mode: str,
        loop: asyncio.AbstractEventLoop,
        stream_key: str | None,
        timeout_seconds: int,
        batch_id: str,
    ) -> None:
        suffix = f"[{batch_id[:6]}:{sub.run_id[:6]}]"
        if sub.variant_name:
            suffix += f"[{sub.variant_name}]"

        stdout_capture = _StreamCapture(
            loop=loop,
            run_id=sub.run_id,
            mode=mode,
            component=f"legacy_stdout{suffix}",
            level="info",
            stream_key=stream_key,
        )
        stderr_capture = _StreamCapture(
            loop=loop,
            run_id=sub.run_id,
            mode=mode,
            component=f"legacy_stderr{suffix}",
            level="warning",
            stream_key=stream_key,
        )

        error_msg: str | None = None
        runtime_yaml: Path | None = None
        output_store = get_legacy_output_store()
        store_result: dict[str, Any] | None = None

        def _invoke_geometry_in_thread() -> None:
            with contextlib.redirect_stdout(stdout_capture), contextlib.redirect_stderr(stderr_capture):
                try:
                    if runtime_yaml is None:
                        raise RuntimeError("Runtime YAML üretilemedi")
                    _run_geometry_sync(
                        yaml_abs=runtime_yaml,
                        run_dir=sub.run_dir,
                        difficulty=str(sub.params.get("difficulty") or "orta"),
                        variant_name=sub.variant_name,
                    )
                finally:
                    stdout_capture.flush()
                    stderr_capture.flush()
                    _detach_stale_logging_handlers((stdout_capture, stderr_capture))

        def _invoke_turkce_in_thread() -> None:
            try:
                if runtime_yaml is None:
                    raise RuntimeError("Runtime YAML üretilemedi")
                _run_turkce_subprocess(
                    yaml_abs=runtime_yaml,
                    run_dir=sub.run_dir,
                    stdout_capture=stdout_capture,
                    stderr_capture=stderr_capture,
                    timeout_seconds=timeout_seconds,
                )
            finally:
                stdout_capture.flush()
                stderr_capture.flush()

        try:
            runtime_yaml = _materialize_runtime_yaml(sub.kind, sub.yaml_path, sub.yaml_content, self.settings)
            if sub.kind == "geometry":
                await asyncio.wait_for(
                    asyncio.to_thread(_invoke_geometry_in_thread),
                    timeout=timeout_seconds,
                )
            elif sub.kind == "turkce":
                # Türkçe için subprocess kendi içinde timeout uyguluyor; outer wait_for
                # sadece thread join + cleanup için biraz tampon ekler.
                await asyncio.wait_for(
                    asyncio.to_thread(_invoke_turkce_in_thread),
                    timeout=timeout_seconds + 30,
                )
            else:
                raise RuntimeError(f"Bilinmeyen kind: {sub.kind}")
        except asyncio.TimeoutError:
            error_msg = f"Timeout ({timeout_seconds}s) aşıldı"
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
        finally:
            files = _collect_storeable_output_files(sub.run_dir)
            store_result = output_store.put_run_package(
                session_id=sub.session_id,
                run_id=sub.run_id,
                kind=sub.kind,
                files=files,
            )
            with contextlib.suppress(Exception):
                shutil.rmtree(sub.run_dir, ignore_errors=True)
            if runtime_yaml is not None:
                with contextlib.suppress(Exception):
                    runtime_yaml.unlink(missing_ok=True)

        status = "success" if error_msg is None else "failed"

        bg_db = SessionLocal()
        try:
            try:
                write_pipeline_log(
                    bg_db,
                    mode=mode,
                    component=f"legacy_runner{suffix}",
                    message=f"Sub-run tamamlandı: status={status}",
                    pipeline_id=sub.run_id,
                    sub_pipeline_id=None,
                    level="info" if status == "success" else "error",
                    details={"error": error_msg, "batch_id": batch_id, "output_store": store_result},
                    stream_key=stream_key,
                )
            except Exception:
                pass
            try:
                repository.finish_pipeline(bg_db, sub.run_id, status, error_msg)
            except Exception:
                pass
        finally:
            bg_db.close()

    def _row_to_detail(self, row: Pipeline, kind: LegacyKind, session_id: str) -> dict[str, Any]:
        output_store = get_legacy_output_store()
        outputs, outputs_available, outputs_message = output_store.get_output_nodes(
            session_id=session_id,
            run_id=row.id,
            output_base_url=f"/v1/legacy/runs/{row.id}/outputs",
        )
        if row.status == "running" and not outputs:
            outputs_available = True
            outputs_message = None
        retry_cfg = repository.parse_json(row.retry_config_json) or {}
        variant_name = retry_cfg.get("variant_name") if isinstance(retry_cfg, dict) else None
        return {
            "run_id": row.id,
            "kind": kind,
            "yaml_path": row.yaml_filename,
            "variant_name": variant_name,
            "status": row.status,
            "error": row.error,
            "started_at": row.created_at.isoformat() if row.created_at else "",
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "outputs": outputs,
            "outputs_available": outputs_available,
            "outputs_message": outputs_message,
        }

    def get_run_detail(self, run_id: str, session_id: str) -> dict[str, Any] | None:
        row = self.db.get(Pipeline, run_id)
        if row is None or not str(row.mode).startswith("legacy_"):
            return None
        if row.mode == "legacy_geometry":
            kind: LegacyKind = "geometry"
        elif row.mode == "legacy_turkce":
            kind = "turkce"
        else:
            return None
        return self._row_to_detail(row, kind, session_id)

    def get_batch_detail(self, batch_id: str, session_id: str) -> dict[str, Any] | None:
        rows = (
            self.db.query(Pipeline)
            .filter(Pipeline.mode.in_(["legacy_geometry", "legacy_turkce"]))
            .filter(Pipeline.retry_config_json.like(f'%"batch_id": "{batch_id}"%'))
            .order_by(Pipeline.created_at.asc())
            .all()
        )
        if not rows:
            return None
        kind: LegacyKind = "geometry" if rows[0].mode == "legacy_geometry" else "turkce"
        runs = [self._row_to_detail(row, kind, session_id) for row in rows]
        return {
            "batch_id": batch_id,
            "kind": kind,
            "runs": runs,
        }
