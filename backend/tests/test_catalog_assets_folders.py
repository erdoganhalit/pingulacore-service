"""Tests for catalog-assets folder operations: prefix listing, move-into-folder, rename.

ObjectStorageService is replaced with an in-memory fake so tests don't need MinIO.
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

import pytest

from app.api import catalog_assets as catalog_assets_module


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch):
    """Replace ObjectStorageService with an in-memory backend mimicking the methods the API uses."""
    state: dict[str, dict[str, bytes]] = {}
    metadata: dict[str, dict[str, datetime]] = {}

    class _FakeStorage:
        def __init__(self, settings) -> None:  # noqa: ANN001
            self.settings = settings

        def object_exists(self, *, bucket: str, key: str) -> bool:
            return key in state.get(bucket, {})

        def upload_bytes(self, *, bucket: str, key: str, data: bytes, content_type: str) -> None:
            state.setdefault(bucket, {})[key] = data
            metadata.setdefault(bucket, {})[key] = datetime.now(tz=timezone.utc)

        def delete_object(self, *, bucket: str, key: str) -> bool:
            bucket_state = state.get(bucket, {})
            if key not in bucket_state:
                return False
            del bucket_state[key]
            metadata.get(bucket, {}).pop(key, None)
            return True

        def copy_object(self, *, bucket: str, source_key: str, dest_key: str) -> None:
            bucket_state = state.get(bucket, {})
            if source_key not in bucket_state:
                raise RuntimeError(f"copy source not found: {source_key}")
            bucket_state[dest_key] = bucket_state[source_key]
            metadata.setdefault(bucket, {})[dest_key] = datetime.now(tz=timezone.utc)

        def list_objects(self, *, bucket: str, prefix: str | None = None):
            items = []
            for key, data in state.get(bucket, {}).items():
                if prefix and not key.startswith(prefix):
                    continue
                items.append({
                    "key": key,
                    "size": len(data),
                    "last_modified": metadata.get(bucket, {}).get(key),
                })
            return items

        def list_with_folders(self, *, bucket: str, prefix: str | None = None):
            items = []
            folder_set: set[str] = set()
            normalized_prefix = prefix or ""
            for key, data in state.get(bucket, {}).items():
                if not key.startswith(normalized_prefix):
                    continue
                remainder = key[len(normalized_prefix):]
                if "/" in remainder:
                    folder_name = remainder.split("/", 1)[0]
                    if folder_name:
                        folder_set.add(folder_name)
                    continue
                items.append({
                    "key": key,
                    "size": len(data),
                    "last_modified": metadata.get(bucket, {}).get(key),
                })
            return items, sorted(folder_set)

    monkeypatch.setattr(catalog_assets_module, "ObjectStorageService", _FakeStorage)
    return state


def _auth_token(client) -> str:
    response = client.post(
        "/v1/auth/register",
        json={
            "email": "folder-tester@example.com",
            "password": "folder-pass-123",
            "display_name": "Folder Tester",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


def _auth_headers(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {_auth_token(client)}"}


def _upload_one(client, headers, filename: str, *, prefix: str | None = None) -> str:
    files = [("file", (filename, BytesIO(b"\x89PNG\r\n\x1a\nXXX"), "image/png"))]
    url = "/v1/catalog-assets"
    if prefix:
        url = f"{url}?prefix={prefix}"
    response = client.post(url, files=files, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["key"]


# ----- Listing: folders and prefix -----------------------------------------------------------


def test_list_at_root_groups_folders(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "root.png")
    _upload_one(client, headers, "child.png", prefix="klasor1/")

    response = client.get("/v1/catalog-assets", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    keys = [it["key"] for it in body["items"]]
    assert "root.png" in keys
    # The file under klasor1/ should NOT appear as an item at root.
    assert "klasor1/child.png" not in keys
    assert "klasor1" in body["folders"]


def test_list_inside_folder_shows_only_that_folder_contents(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "root.png")
    _upload_one(client, headers, "a.png", prefix="klasor1/")
    _upload_one(client, headers, "b.png", prefix="klasor1/")

    response = client.get("/v1/catalog-assets?prefix=klasor1/", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    keys = sorted(it["key"] for it in body["items"])
    assert keys == ["klasor1/a.png", "klasor1/b.png"]
    assert body["prefix"] == "klasor1/"
    assert body["folders"] == []


def test_list_rejects_traversal_in_prefix(client, fake_storage) -> None:
    headers = _auth_headers(client)
    response = client.get("/v1/catalog-assets?prefix=../etc", headers=headers)
    assert response.status_code == 400, response.text


# ----- Upload with prefix --------------------------------------------------------------------


def test_upload_with_prefix_stores_under_folder(client, fake_storage) -> None:
    headers = _auth_headers(client)
    key = _upload_one(client, headers, "img.png", prefix="klasor1/")
    assert key == "klasor1/img.png"


def test_upload_with_same_prefix_renames_on_collision(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "img.png", prefix="klasor1/")
    second = _upload_one(client, headers, "img.png", prefix="klasor1/")
    assert second == "klasor1/img_1.png"


def test_upload_same_filename_in_different_folders_does_not_rename(client, fake_storage) -> None:
    headers = _auth_headers(client)
    a = _upload_one(client, headers, "img.png", prefix="klasor1/")
    b = _upload_one(client, headers, "img.png", prefix="klasor2/")
    assert a == "klasor1/img.png"
    assert b == "klasor2/img.png"


# ----- Move into folder ----------------------------------------------------------------------


def test_move_into_folder_happy_path(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "a.png")
    _upload_one(client, headers, "b.png")

    response = client.post(
        "/v1/catalog-assets/move-into-folder",
        headers=headers,
        json={"folder": "yeniler", "keys": ["a.png", "b.png"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success_count"] == 2
    assert body["failure_count"] == 0
    new_keys = sorted(r["new_key"] for r in body["results"])
    assert new_keys == ["yeniler/a.png", "yeniler/b.png"]

    # Verify root no longer has them.
    list_response = client.get("/v1/catalog-assets", headers=headers)
    root_keys = [it["key"] for it in list_response.json()["items"]]
    assert "a.png" not in root_keys
    assert "b.png" not in root_keys
    assert "yeniler" in list_response.json()["folders"]


def test_move_into_folder_collides_with_existing_renames(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "a.png")
    _upload_one(client, headers, "a.png", prefix="yeniler/")  # destination already has a.png

    response = client.post(
        "/v1/catalog-assets/move-into-folder",
        headers=headers,
        json={"folder": "yeniler", "keys": ["a.png"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success_count"] == 1
    assert body["results"][0]["new_key"] == "yeniler/a_1.png"


def test_move_into_folder_missing_key_reports_failure(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "a.png")
    response = client.post(
        "/v1/catalog-assets/move-into-folder",
        headers=headers,
        json={"folder": "yeniler", "keys": ["a.png", "ghost.png"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success_count"] == 1
    assert body["failure_count"] == 1
    by_key = {r["key"]: r for r in body["results"]}
    assert by_key["ghost.png"]["success"] is False


def test_move_into_folder_rejects_bad_folder_name(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "a.png")
    for bad_name in ["", "../up", "foo/bar", ".hidden", "x" * 200]:
        response = client.post(
            "/v1/catalog-assets/move-into-folder",
            headers=headers,
            json={"folder": bad_name, "keys": ["a.png"]},
        )
        assert response.status_code == 400, f"{bad_name}: {response.text}"


def test_move_into_folder_empty_keys_rejected(client, fake_storage) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/v1/catalog-assets/move-into-folder",
        headers=headers,
        json={"folder": "yeniler", "keys": []},
    )
    assert response.status_code == 400, response.text


# ----- Rename --------------------------------------------------------------------------------


def test_rename_at_root(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "old.png")
    response = client.post(
        "/v1/catalog-assets/rename",
        headers=headers,
        json={"key": "old.png", "new_name": "new.png"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["old_key"] == "old.png"
    assert body["new_key"] == "new.png"

    list_response = client.get("/v1/catalog-assets", headers=headers)
    keys = [it["key"] for it in list_response.json()["items"]]
    assert "old.png" not in keys
    assert "new.png" in keys


def test_rename_inside_folder_preserves_prefix(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "old.png", prefix="klasor1/")
    response = client.post(
        "/v1/catalog-assets/rename",
        headers=headers,
        json={"key": "klasor1/old.png", "new_name": "yeni.png"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["new_key"] == "klasor1/yeni.png"


def test_rename_rejects_non_image_extension(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "old.png")
    response = client.post(
        "/v1/catalog-assets/rename",
        headers=headers,
        json={"key": "old.png", "new_name": "broken.txt"},
    )
    assert response.status_code == 400, response.text


def test_rename_rejects_slash_in_new_name(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "old.png")
    response = client.post(
        "/v1/catalog-assets/rename",
        headers=headers,
        json={"key": "old.png", "new_name": "folder/file.png"},
    )
    assert response.status_code == 400, response.text


def test_rename_conflict_when_target_exists(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "a.png")
    _upload_one(client, headers, "b.png")
    response = client.post(
        "/v1/catalog-assets/rename",
        headers=headers,
        json={"key": "a.png", "new_name": "b.png"},
    )
    assert response.status_code == 409, response.text


def test_rename_missing_source_returns_404(client, fake_storage) -> None:
    headers = _auth_headers(client)
    response = client.post(
        "/v1/catalog-assets/rename",
        headers=headers,
        json={"key": "ghost.png", "new_name": "found.png"},
    )
    assert response.status_code == 404, response.text


def test_rename_noop_when_new_name_equals_old(client, fake_storage) -> None:
    headers = _auth_headers(client)
    _upload_one(client, headers, "same.png")
    response = client.post(
        "/v1/catalog-assets/rename",
        headers=headers,
        json={"key": "same.png", "new_name": "same.png"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["new_key"] == "same.png"
