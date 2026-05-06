from __future__ import annotations

from app.services.legacy_session_output_store import (
    MAX_ARTIFACT_BYTES,
    MAX_SESSION_BYTES,
    TTL_SECONDS,
    LegacySessionOutputStore,
    StoredOutputFile,
)


def _file(rel: str, size: int, mime: str = "application/octet-stream") -> StoredOutputFile:
    return StoredOutputFile(rel_path=rel, content=b"x" * size, mime_type=mime, size=size)


def test_rejects_artifact_larger_than_limit() -> None:
    store = LegacySessionOutputStore()
    result = store.put_run_package(
        session_id="s1",
        run_id="r1",
        kind="geometry",
        files=[_file("a.png", MAX_ARTIFACT_BYTES + 1, "image/png")],
    )
    assert result["stored"] is True
    assert result["stored_file_count"] == 0
    assert result["dropped_file_count"] == 1
    nodes, available, _ = store.get_output_nodes(
        session_id="s1",
        run_id="r1",
        output_base_url="/v1/legacy/runs/r1/outputs",
    )
    assert available is True
    assert nodes == []


def test_eviction_is_package_based_fifo() -> None:
    store = LegacySessionOutputStore()
    forty_five_mb = 45 * 1024 * 1024
    forty_mb = 40 * 1024 * 1024

    r1 = store.put_run_package(session_id="s1", run_id="r1", kind="geometry", files=[_file("1.json", forty_five_mb)])
    r2 = store.put_run_package(session_id="s1", run_id="r2", kind="geometry", files=[_file("2.json", forty_five_mb)])
    r3 = store.put_run_package(session_id="s1", run_id="r3", kind="geometry", files=[_file("3.json", forty_five_mb)])
    r4 = store.put_run_package(session_id="s1", run_id="r4", kind="geometry", files=[_file("4.json", forty_five_mb)])
    r5 = store.put_run_package(session_id="s1", run_id="r5", kind="geometry", files=[_file("5.json", forty_five_mb)])
    assert r1["stored"] is True
    assert r2["stored"] is True
    assert r3["stored"] is True
    assert r4["stored"] is True
    assert r5["stored"] is True

    # 225MB + 40MB > 250MB, oldest package (r1) must be evicted.
    r6 = store.put_run_package(session_id="s1", run_id="r6", kind="geometry", files=[_file("6.json", forty_mb)])
    assert r6["stored"] is True

    assert store.get_run_package("s1", "r1") is None
    assert store.get_run_package("s1", "r2") is not None
    assert store.get_run_package("s1", "r6") is not None


def test_package_too_large_degrades_without_storing() -> None:
    store = LegacySessionOutputStore()
    result = store.put_run_package(
        session_id="s1",
        run_id="r1",
        kind="geometry",
        files=[
            _file("a.bin", MAX_ARTIFACT_BYTES),
            _file("b.bin", MAX_ARTIFACT_BYTES),
            _file("c.bin", MAX_ARTIFACT_BYTES),
            _file("d.bin", MAX_ARTIFACT_BYTES),
            _file("e.bin", MAX_ARTIFACT_BYTES),
            _file("f.bin", 1),
        ],
    )
    assert result["stored"] is False
    assert result.get("reason") == "package_too_large"
    assert store.get_run_package("s1", "r1") is None


def test_ttl_expiry_removes_session_outputs() -> None:
    store = LegacySessionOutputStore()
    now = 1000.0
    store._now = lambda: now  # type: ignore[method-assign]

    store.put_run_package(
        session_id="s1",
        run_id="r1",
        kind="geometry",
        files=[_file("a.json", 128)],
    )
    assert store.get_run_package("s1", "r1") is not None

    now += TTL_SECONDS + 31
    assert store.get_run_package("s1", "r1") is None
