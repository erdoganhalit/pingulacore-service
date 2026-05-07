from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services import sub_pipeline_files_service as sp_files


def _flatten(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        out.append(item)
        children = item.get("children") or []
        if isinstance(children, list):
            out.extend(_flatten(children))
    return out


def test_explorer_tree_and_read(client) -> None:
    settings = get_settings()
    runs_file = settings.runs_dir / "full" / "tree_test" / "render_1.png"
    q_file = settings.root_dir / "sp_files" / "q_json" / "tree_test.question.json"
    l_file = settings.root_dir / "sp_files" / "layout" / "tree_test.layout.json"
    for path in [runs_file, q_file, l_file]:
        path.parent.mkdir(parents=True, exist_ok=True)

    runs_file.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    q_file.write_text(json.dumps({"question_id": "q-tree"}, ensure_ascii=False), encoding="utf-8")
    l_file.write_text(json.dumps({"schema_version": "layout-plan.v2"}, ensure_ascii=False), encoding="utf-8")

    try:
        runs_tree = client.get("/v1/explorer/tree?root=runs")
        assert runs_tree.status_code == 200
        runs_nodes = _flatten(runs_tree.json()["items"])
        assert any(node["path"] == "full/tree_test/render_1.png" for node in runs_nodes)

        sp_tree = client.get("/v1/explorer/tree?root=sp_files")
        assert sp_tree.status_code == 200
        sp_nodes = _flatten(sp_tree.json()["items"])
        assert any(node["path"] == "q_json/tree_test.question.json" for node in sp_nodes)
        assert any(node["path"] == "layout/tree_test.layout.json" for node in sp_nodes)

        read_question = client.get("/v1/explorer/file?root=sp_files&path=q_json/tree_test.question.json")
        assert read_question.status_code == 200
        assert read_question.json()["content_type"] == "json"
        assert read_question.json()["content"]["question_id"] == "q-tree"

        read_render = client.get("/v1/explorer/file?root=runs&path=full/tree_test/render_1.png")
        assert read_render.status_code == 200
        body = read_render.json()
        assert body["content_type"] == "image"
        assert body["asset_url"] == "/v1/assets/runs/full/tree_test/render_1.png"
    finally:
        if runs_file.exists():
            runs_file.unlink()
        if q_file.exists():
            q_file.unlink()
        if l_file.exists():
            l_file.unlink()


def test_explorer_favorite_scope_and_toggle(client) -> None:
    settings = get_settings()
    q_file = settings.root_dir / "sp_files" / "q_json" / "fav_scope.question.json"
    render_file = settings.runs_dir / "sub" / "fav_scope" / "render_final.png"
    non_allowed = settings.runs_dir / "sub" / "fav_scope" / "scene.png"
    for path in [q_file, render_file, non_allowed]:
        path.parent.mkdir(parents=True, exist_ok=True)

    q_file.write_text(json.dumps({"question_id": "q-fav-scope"}, ensure_ascii=False), encoding="utf-8")
    render_file.write_bytes(b"\x89PNG\r\n\x1a\nrender")
    non_allowed.write_bytes(b"\x89PNG\r\n\x1a\nscene")

    try:
        mark_q = client.patch(
            "/v1/explorer/file/favorite",
            json={"root": "sp_files", "path": "q_json/fav_scope.question.json", "is_favorite": True},
        )
        assert mark_q.status_code == 200
        assert sp_files.get_stored_json_favorite("q_json", "fav_scope.question.json") is True

        mark_render = client.patch(
            "/v1/explorer/file/favorite",
            json={"root": "runs", "path": "sub/fav_scope/render_final.png", "is_favorite": True},
        )
        assert mark_render.status_code == 200
        assert sp_files.get_path_favorite("runs", "sub/fav_scope/render_final.png") is True

        reject = client.patch(
            "/v1/explorer/file/favorite",
            json={"root": "runs", "path": "sub/fav_scope/scene.png", "is_favorite": True},
        )
        assert reject.status_code == 400
    finally:
        if q_file.exists():
            q_file.unlink()
        if render_file.exists():
            render_file.unlink()
        if non_allowed.exists():
            non_allowed.unlink()
        sp_files.set_stored_json_favorite("q_json", "fav_scope.question.json", False)
        sp_files.set_path_favorite("runs", "sub/fav_scope/render_final.png", False)


def test_explorer_delete_cleans_favorites_and_db_link(client) -> None:
    settings = get_settings()
    q_file = settings.root_dir / "sp_files" / "q_json" / "fav_delete.question.json"
    q_file.parent.mkdir(parents=True, exist_ok=True)
    q_file.write_text(json.dumps({"question_id": "q-delete"}, ensure_ascii=False), encoding="utf-8")

    try:
        mark = client.patch(
            "/v1/explorer/file/favorite",
            json={"root": "sp_files", "path": "q_json/fav_delete.question.json", "is_favorite": True},
        )
        assert mark.status_code == 200

        delete_resp = client.delete("/v1/explorer/file?root=sp_files&path=q_json/fav_delete.question.json")
        assert delete_resp.status_code == 204

        assert not q_file.exists()
        assert sp_files.get_stored_json_favorite("q_json", "fav_delete.question.json") is False

        list_resp = client.get("/v1/sp-files/q_json")
        assert list_resp.status_code == 200
        assert not any(item["filename"] == "fav_delete.question.json" for item in list_resp.json()["items"])
    finally:
        if q_file.exists():
            q_file.unlink()
        sp_files.set_stored_json_favorite("q_json", "fav_delete.question.json", False)


def test_explorer_guards_and_errors(client) -> None:
    invalid_root = client.get("/v1/explorer/tree?root=invalid")
    assert invalid_root.status_code == 422

    traversal = client.get("/v1/explorer/file?root=sp_files&path=../../etc/passwd")
    assert traversal.status_code == 400

    absolute = client.delete("/v1/explorer/file?root=runs&path=/tmp/foo.txt")
    assert absolute.status_code == 400

    missing = client.get("/v1/explorer/file?root=sp_files&path=q_json/missing.question.json")
    assert missing.status_code == 404
