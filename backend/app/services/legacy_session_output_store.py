from __future__ import annotations

import io
import threading
import time
import zipfile
from collections import deque
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterator
from urllib.parse import quote


MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
MAX_SESSION_BYTES = 250 * 1024 * 1024
TTL_SECONDS = 30 * 60
_CLEANUP_INTERVAL_SECONDS = 30


@dataclass
class StoredOutputFile:
    rel_path: str
    content: bytes
    mime_type: str
    size: int


@dataclass
class RunOutputPackage:
    run_id: str
    kind: str
    created_at: float
    last_access_at: float
    total_size: int
    files: dict[str, StoredOutputFile]


@dataclass
class SessionBucket:
    session_id: str
    created_at: float
    last_access_at: float
    total_size: int
    run_order: deque[str]
    runs: dict[str, RunOutputPackage]


class LegacySessionOutputStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, SessionBucket] = {}
        self._last_cleanup_at = 0.0

    def _now(self) -> float:
        return time.time()

    def _normalize_rel_path(self, rel_path: str) -> str:
        candidate = PurePosixPath((rel_path or "").strip().lstrip("/"))
        if not str(candidate) or str(candidate) in {".", ".."}:
            raise ValueError("Geçersiz dosya yolu")
        if any(part in {"", ".", ".."} for part in candidate.parts):
            raise ValueError("Geçersiz dosya yolu")
        return candidate.as_posix()

    def _maybe_cleanup_locked(self, now: float) -> None:
        if now - self._last_cleanup_at < _CLEANUP_INTERVAL_SECONDS:
            return
        self._last_cleanup_at = now
        expired_sessions = []
        for sid, session in self._sessions.items():
            if now - session.last_access_at > TTL_SECONDS:
                expired_sessions.append(sid)
                continue
            expired_runs = [rid for rid, pkg in session.runs.items() if now - pkg.last_access_at > TTL_SECONDS]
            for rid in expired_runs:
                self._drop_run_locked(session, rid)
        for sid in expired_sessions:
            self._sessions.pop(sid, None)

    def _drop_run_locked(self, session: SessionBucket, run_id: str) -> None:
        pkg = session.runs.pop(run_id, None)
        if pkg is None:
            return
        session.total_size = max(0, session.total_size - pkg.total_size)
        session.run_order = deque(rid for rid in session.run_order if rid != run_id)

    def _touch_session_locked(self, session: SessionBucket, now: float) -> None:
        session.last_access_at = now

    def put_run_package(
        self,
        *,
        session_id: str,
        run_id: str,
        kind: str,
        files: list[StoredOutputFile],
    ) -> dict[str, int | str | bool]:
        safe_session = (session_id or "").strip()
        if not safe_session:
            return {"stored": False, "stored_file_count": 0, "dropped_file_count": len(files), "package_size": 0}

        safe_files: dict[str, StoredOutputFile] = {}
        dropped = 0
        package_size = 0
        for file in files:
            if file.size > MAX_ARTIFACT_BYTES:
                dropped += 1
                continue
            try:
                rel = self._normalize_rel_path(file.rel_path)
            except ValueError:
                dropped += 1
                continue
            safe_files[rel] = StoredOutputFile(
                rel_path=rel,
                content=file.content,
                mime_type=file.mime_type,
                size=file.size,
            )
            package_size += file.size

        now = self._now()
        with self._lock:
            self._maybe_cleanup_locked(now)
            session = self._sessions.get(safe_session)
            if session is None:
                session = SessionBucket(
                    session_id=safe_session,
                    created_at=now,
                    last_access_at=now,
                    total_size=0,
                    run_order=deque(),
                    runs={},
                )
                self._sessions[safe_session] = session

            if run_id in session.runs:
                self._drop_run_locked(session, run_id)

            if package_size > MAX_SESSION_BYTES:
                return {
                    "stored": False,
                    "stored_file_count": len(safe_files),
                    "dropped_file_count": dropped,
                    "package_size": package_size,
                    "reason": "package_too_large",
                }

            while session.total_size + package_size > MAX_SESSION_BYTES and session.run_order:
                oldest = session.run_order.popleft()
                self._drop_run_locked(session, oldest)

            if session.total_size + package_size > MAX_SESSION_BYTES:
                return {
                    "stored": False,
                    "stored_file_count": len(safe_files),
                    "dropped_file_count": dropped,
                    "package_size": package_size,
                    "reason": "session_limit_unavailable",
                }

            pkg = RunOutputPackage(
                run_id=run_id,
                kind=kind,
                created_at=now,
                last_access_at=now,
                total_size=package_size,
                files=safe_files,
            )
            session.runs[run_id] = pkg
            session.run_order.append(run_id)
            session.total_size += package_size
            self._touch_session_locked(session, now)
            return {
                "stored": True,
                "stored_file_count": len(safe_files),
                "dropped_file_count": dropped,
                "package_size": package_size,
            }

    def _get_package_locked(self, session_id: str, run_id: str, now: float) -> RunOutputPackage | None:
        self._maybe_cleanup_locked(now)
        session = self._sessions.get(session_id)
        if session is None:
            return None
        pkg = session.runs.get(run_id)
        if pkg is None:
            return None
        session.last_access_at = now
        pkg.last_access_at = now
        return pkg

    def get_run_package(self, session_id: str, run_id: str) -> RunOutputPackage | None:
        safe_session = (session_id or "").strip()
        if not safe_session:
            return None
        now = self._now()
        with self._lock:
            return self._get_package_locked(safe_session, run_id, now)

    def get_output_nodes(
        self, *, session_id: str, run_id: str, output_base_url: str
    ) -> tuple[list[dict], bool, str | None]:
        pkg = self.get_run_package(session_id, run_id)
        if pkg is None:
            return [], False, "Bu oturumun çıktıları süresi dolduğu için erişilemiyor."

        tree: dict[str, dict] = {}
        roots: dict[str, dict] = {}

        def _ensure_dir_node(path_parts: tuple[str, ...]) -> dict:
            key = "/".join(path_parts)
            if key in tree:
                return tree[key]
            name = path_parts[-1]
            rel = key
            node = {
                "name": name,
                "type": "dir",
                "rel_path": rel,
                "children": [],
            }
            tree[key] = node
            if len(path_parts) == 1:
                roots[key] = node
            else:
                parent = _ensure_dir_node(path_parts[:-1])
                parent["children"].append(node)
            return node

        for rel_path in sorted(pkg.files.keys()):
            f = pkg.files[rel_path]
            parts = tuple(PurePosixPath(rel_path).parts)
            if len(parts) > 1:
                parent = _ensure_dir_node(parts[:-1])
            else:
                parent = None

            url = f"{output_base_url}/{quote(rel_path, safe='/')}?sid={quote(session_id)}"
            file_node = {
                "name": parts[-1],
                "type": "file",
                "rel_path": rel_path,
                "url": url,
                "size": f.size,
            }
            if parent is None:
                roots[rel_path] = file_node
            else:
                parent["children"].append(file_node)

        def _sort_children(node: dict) -> None:
            children = node.get("children", [])
            children.sort(key=lambda x: (0 if x.get("type") == "dir" else 1, x.get("name", "")))
            for child in children:
                if child.get("type") == "dir":
                    _sort_children(child)

        root_nodes = list(roots.values())
        root_nodes.sort(key=lambda x: (0 if x.get("type") == "dir" else 1, x.get("name", "")))
        for node in root_nodes:
            if node.get("type") == "dir":
                _sort_children(node)
        return root_nodes, True, None

    def get_file(self, *, session_id: str, run_id: str, rel_path: str) -> StoredOutputFile | None:
        try:
            safe_rel = self._normalize_rel_path(rel_path)
        except ValueError:
            return None
        pkg = self.get_run_package(session_id, run_id)
        if pkg is None:
            return None
        return pkg.files.get(safe_rel)

    def iter_zip_stream(
        self,
        *,
        session_id: str,
        run_id: str,
        subdir: str | None = None,
    ) -> tuple[Iterator[bytes], str]:
        pkg = self.get_run_package(session_id, run_id)
        if pkg is None:
            raise FileNotFoundError("Run çıktıları bu session için bulunamadı")

        prefix = None
        if subdir:
            prefix = self._normalize_rel_path(subdir)

        files = []
        for rel, file in pkg.files.items():
            if prefix is None:
                files.append((rel, file))
            elif rel == prefix or rel.startswith(prefix + "/"):
                files.append((rel, file))
        if not files:
            raise FileNotFoundError("İndirilecek çıktı bulunamadı")

        suggested = (prefix.replace("/", "_") if prefix else run_id) + ".zip"
        base_len = len(prefix) + 1 if prefix else 0

        def _iterator() -> Iterator[bytes]:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                for rel, file in sorted(files, key=lambda x: x[0]):
                    arcname = rel[base_len:] if prefix and rel.startswith(prefix + "/") else PurePosixPath(rel).name
                    zf.writestr(arcname, file.content)
            buffer.seek(0)
            while True:
                chunk = buffer.read(64 * 1024)
                if not chunk:
                    break
                yield chunk

        return _iterator(), suggested


_LEGACY_OUTPUT_STORE = LegacySessionOutputStore()


def get_legacy_output_store() -> LegacySessionOutputStore:
    return _LEGACY_OUTPUT_STORE

