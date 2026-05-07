from __future__ import annotations

import json

from app.core.config import get_settings
from app.db.database import Base, engine, init_db


def test_list_yaml_files_from_primary_and_fallback(client) -> None:
    resp = client.get("/v1/yaml-files")
    assert resp.status_code == 200
    data = resp.json()
    assert "files" in data
    assert "o08_iki_adimli_toplama.yaml" in data["files"]


def test_get_yaml_file_content(client) -> None:
    resp = client.get("/v1/yaml-files/o08_iki_adimli_toplama.yaml")
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "o08_iki_adimli_toplama.yaml"
    assert isinstance(body["data"], dict)
    assert "meta" in body["data"]


def test_runtime_info_endpoint(client) -> None:
    resp = client.get("/v1/runtime-info")
    assert resp.status_code == 200
    body = resp.json()
    assert "use_stub_agents" in body
    assert "text_model" in body
    assert "light_model" in body
    assert "image_model" in body
    assert "has_google_api_key" in body
    assert "has_anthropic_api_key" in body


def test_get_generated_asset_success_and_path_guard(client) -> None:
    settings = get_settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.catalog_dir.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    asset_path = settings.output_dir / "test_asset.png"
    catalog_asset_path = settings.catalog_dir / "test_catalog_asset.png"
    run_asset_path = settings.runs_dir / "full" / "test_run" / "render_1.png"
    asset_path.write_bytes(b"png-data")
    catalog_asset_path.write_bytes(b"catalog-png-data")
    run_asset_path.parent.mkdir(parents=True, exist_ok=True)
    run_asset_path.write_bytes(b"run-png-data")

    try:
        ok = client.get("/v1/assets/test_asset.png")
        assert ok.status_code == 200
        assert ok.content == b"png-data"

        ok_catalog = client.get("/v1/assets/test_catalog_asset.png")
        assert ok_catalog.status_code == 200
        assert ok_catalog.content == b"catalog-png-data"

        ok_run = client.get("/v1/assets/runs/full/test_run/render_1.png")
        assert ok_run.status_code == 200
        assert ok_run.content == b"run-png-data"

        bad = client.get("/v1/assets/nested/test_asset.png")
        assert bad.status_code == 400
    finally:
        if asset_path.exists():
            asset_path.unlink()
        if catalog_asset_path.exists():
            catalog_asset_path.unlink()
        if run_asset_path.exists():
            run_asset_path.unlink()


def test_sp_files_list_and_read_endpoints(client) -> None:
    settings = get_settings()
    q_dir = settings.root_dir / "sp_files" / "q_json"
    l_dir = settings.root_dir / "sp_files" / "layout"
    h_dir = settings.root_dir / "sp_files" / "q_html"
    q_dir.mkdir(parents=True, exist_ok=True)
    l_dir.mkdir(parents=True, exist_ok=True)
    h_dir.mkdir(parents=True, exist_ok=True)

    q_file = q_dir / "test_question.question.json"
    l_file = l_dir / "test_layout.layout.json"
    h_file = h_dir / "test_question.question.html"

    q_file.write_text(json.dumps({"question_id": "q-test"}, ensure_ascii=False), encoding="utf-8")
    l_file.write_text(json.dumps({"schema_version": "layout-plan.v2"}, ensure_ascii=False), encoding="utf-8")
    h_file.write_text("<div>html</div>", encoding="utf-8")

    try:
        q_list = client.get("/v1/sp-files/q_json")
        assert q_list.status_code == 200
        assert "test_question.question.json" in q_list.json()["files"]
        q_items = q_list.json()["items"]
        assert any(item["filename"] == "test_question.question.json" for item in q_items)

        l_list = client.get("/v1/sp-files/layout")
        assert l_list.status_code == 200
        assert "test_layout.layout.json" in l_list.json()["files"]
        l_items = l_list.json()["items"]
        assert any(item["filename"] == "test_layout.layout.json" for item in l_items)

        h_list = client.get("/v1/sp-files/q_html")
        assert h_list.status_code == 200
        assert "test_question.question.html" in h_list.json()["files"]

        q_get = client.get("/v1/sp-files/q_json/test_question.question.json")
        assert q_get.status_code == 200
        assert q_get.json()["data"]["question_id"] == "q-test"

        l_get = client.get("/v1/sp-files/layout/test_layout.layout.json")
        assert l_get.status_code == 200
        assert l_get.json()["data"]["schema_version"] == "layout-plan.v2"

        h_get = client.get("/v1/sp-files/q_html/test_question.question.html")
        assert h_get.status_code == 200
        assert "html" in h_get.json()["html_content"]
    finally:
        if q_file.exists():
            q_file.unlink()
        if l_file.exists():
            l_file.unlink()
        if h_file.exists():
            h_file.unlink()


def test_favorites_crud_endpoints(client) -> None:
    create_payload = {
        "name": "Beğendiğim Soru V1",
        "kind": "question",
        "data": {"question_id": "q-fav-1", "stem": "örnek"},
        "source_sub_pipeline_id": "sp-123",
    }
    create_resp = client.post("/v1/favorites", json=create_payload)
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["name"] == create_payload["name"]
    assert created["kind"] == "question"
    assert created["data"]["question_id"] == "q-fav-1"
    favorite_id = created["id"]

    list_resp = client.get("/v1/favorites?kind=question")
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert any(item["id"] == favorite_id for item in listed)

    get_resp = client.get(f"/v1/favorites/{favorite_id}")
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["id"] == favorite_id
    assert fetched["name"] == create_payload["name"]

    delete_resp = client.delete(f"/v1/favorites/{favorite_id}")
    assert delete_resp.status_code == 204

    missing_resp = client.get(f"/v1/favorites/{favorite_id}")
    assert missing_resp.status_code == 404


def test_sp_file_favorite_toggle_and_filter(client) -> None:
    settings = get_settings()
    q_dir = settings.root_dir / "sp_files" / "q_json"
    q_dir.mkdir(parents=True, exist_ok=True)
    q_file = q_dir / "favorite_toggle.question.json"
    q_file.write_text(json.dumps({"question_id": "q-fav-toggle"}, ensure_ascii=False), encoding="utf-8")

    try:
        list_before = client.get("/v1/sp-files/q_json")
        assert list_before.status_code == 200
        assert any(item["filename"] == q_file.name for item in list_before.json()["items"])

        mark = client.patch(f"/v1/sp-files/q_json/{q_file.name}/favorite", json={"is_favorite": True})
        assert mark.status_code == 200
        assert mark.json()["is_favorite"] is True

        only_favs = client.get("/v1/sp-files/q_json?favorites_only=true")
        assert only_favs.status_code == 200
        assert any(item["filename"] == q_file.name for item in only_favs.json()["items"])
    finally:
        if q_file.exists():
            q_file.unlink()


def test_sp_file_favorites_survive_db_reinit_via_sp_files_metadata(client) -> None:
    settings = get_settings()
    q_dir = settings.root_dir / "sp_files" / "q_json"
    l_dir = settings.root_dir / "sp_files" / "layout"
    q_dir.mkdir(parents=True, exist_ok=True)
    l_dir.mkdir(parents=True, exist_ok=True)
    q_file = q_dir / "favorite_persist.question.json"
    l_file = l_dir / "favorite_persist.layout.json"
    favorites_meta = settings.root_dir / "sp_files" / ".stored_json_favorites.json"

    q_file.write_text(json.dumps({"question_id": "q-fav-persist"}, ensure_ascii=False), encoding="utf-8")
    l_file.write_text(json.dumps({"schema_version": "layout-plan.v2"}, ensure_ascii=False), encoding="utf-8")

    try:
        mark_q = client.patch(f"/v1/sp-files/q_json/{q_file.name}/favorite", json={"is_favorite": True})
        assert mark_q.status_code == 200
        mark_l = client.patch(f"/v1/sp-files/layout/{l_file.name}/favorite", json={"is_favorite": True})
        assert mark_l.status_code == 200

        # Simulate backend restart with a recreated DB schema.
        Base.metadata.drop_all(bind=engine)
        init_db()

        q_list = client.get("/v1/sp-files/q_json")
        assert q_list.status_code == 200
        q_item = next(item for item in q_list.json()["items"] if item["filename"] == q_file.name)
        assert q_item["is_favorite"] is True

        l_list = client.get("/v1/sp-files/layout")
        assert l_list.status_code == 200
        l_item = next(item for item in l_list.json()["items"] if item["filename"] == l_file.name)
        assert l_item["is_favorite"] is True
    finally:
        if q_file.exists():
            q_file.unlink()
        if l_file.exists():
            l_file.unlink()
        if favorites_meta.exists():
            favorites_meta.unlink()


def test_favorite_create_rejects_blank_name(client) -> None:
    resp = client.post(
        "/v1/favorites",
        json={
            "name": "   ",
            "kind": "question",
            "data": {"question_id": "q-x"},
        },
    )
    assert resp.status_code == 400


def test_favorite_create_rejects_invalid_kind(client) -> None:
    resp = client.post(
        "/v1/favorites",
        json={
            "name": "Invalid Kind",
            "kind": "html",
            "data": {"question_id": "q-x"},
        },
    )
    assert resp.status_code == 422


def test_favorite_create_rejects_null_data(client) -> None:
    resp = client.post(
        "/v1/favorites",
        json={
            "name": "No Data",
            "kind": "layout",
            "data": None,
        },
    )
    assert resp.status_code == 422


def test_favorite_list_rejects_invalid_kind(client) -> None:
    resp = client.get("/v1/favorites?kind=bogus")
    assert resp.status_code == 400


def test_favorite_delete_nonexistent_returns_404(client) -> None:
    resp = client.delete("/v1/favorites/999999")
    assert resp.status_code == 404
