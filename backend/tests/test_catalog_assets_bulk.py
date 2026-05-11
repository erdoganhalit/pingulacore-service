from __future__ import annotations

from io import BytesIO

import pytest

from app.api import catalog_assets as catalog_assets_module


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch):
    """Replace ObjectStorageService methods used by the bulk endpoint with in-memory fakes."""
    state: dict[str, dict[str, bytes]] = {}

    class _FakeStorage:
        def __init__(self, settings) -> None:  # noqa: ANN001 - signature mirrors the real class
            self.settings = settings

        def object_exists(self, *, bucket: str, key: str) -> bool:
            return key in state.get(bucket, {})

        def upload_bytes(self, *, bucket: str, key: str, data: bytes, content_type: str) -> None:
            state.setdefault(bucket, {})[key] = data

    monkeypatch.setattr(catalog_assets_module, "ObjectStorageService", _FakeStorage)
    return state


def _auth_token(client) -> str:
    payload = {
        "email": "bulk-uploader@example.com",
        "password": "bulk-pass-123",
        "display_name": "Bulk Uploader",
    }
    response = client.post("/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    token = response.json().get("token")
    assert isinstance(token, str) and token
    return token


def _auth_headers(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {_auth_token(client)}"}


def test_bulk_upload_all_success(client, fake_storage) -> None:
    headers = _auth_headers(client)
    files = [
        ("files", ("a.png", BytesIO(b"\x89PNG\r\n\x1a\nAAA"), "image/png")),
        ("files", ("b.png", BytesIO(b"\x89PNG\r\n\x1a\nBBB"), "image/png")),
    ]
    response = client.post("/v1/catalog-assets/bulk", files=files, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success_count"] == 2
    assert body["failure_count"] == 0
    keys = sorted(r["key"] for r in body["results"])
    assert keys == ["a.png", "b.png"]
    catalog_bucket = next(iter(fake_storage))
    assert set(fake_storage[catalog_bucket].keys()) == {"a.png", "b.png"}


def test_bulk_upload_rejects_non_image(client, fake_storage) -> None:
    headers = _auth_headers(client)
    files = [
        ("files", ("good.png", BytesIO(b"\x89PNG\r\n\x1a\nOK"), "image/png")),
        ("files", ("bad.txt", BytesIO(b"plain text"), "text/plain")),
    ]
    response = client.post("/v1/catalog-assets/bulk", files=files, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success_count"] == 1
    assert body["failure_count"] == 1
    results_by_name = {r["filename"]: r for r in body["results"]}
    assert results_by_name["good.png"]["success"] is True
    assert results_by_name["bad.txt"]["success"] is False
    assert "görsel" in results_by_name["bad.txt"]["error"].lower()


def test_bulk_upload_renames_same_name_files_in_call(client, fake_storage) -> None:
    headers = _auth_headers(client)
    files = [
        ("files", ("dup.png", BytesIO(b"\x89PNG\r\n\x1a\n1"), "image/png")),
        ("files", ("dup.png", BytesIO(b"\x89PNG\r\n\x1a\n2"), "image/png")),
        ("files", ("dup.png", BytesIO(b"\x89PNG\r\n\x1a\n3"), "image/png")),
    ]
    response = client.post("/v1/catalog-assets/bulk", files=files, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success_count"] == 3
    keys = sorted(r["key"] for r in body["results"])
    assert keys == ["dup.png", "dup_1.png", "dup_2.png"]


def test_bulk_upload_rejects_empty_file(client, fake_storage) -> None:
    headers = _auth_headers(client)
    files = [
        ("files", ("ok.png", BytesIO(b"\x89PNG\r\n\x1a\nOK"), "image/png")),
        ("files", ("empty.png", BytesIO(b""), "image/png")),
    ]
    response = client.post("/v1/catalog-assets/bulk", files=files, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success_count"] == 1
    assert body["failure_count"] == 1
    results_by_name = {r["filename"]: r for r in body["results"]}
    assert results_by_name["empty.png"]["success"] is False
    assert "boş" in results_by_name["empty.png"]["error"].lower()


def test_bulk_upload_requires_at_least_one_file(client, fake_storage) -> None:
    headers = _auth_headers(client)
    response = client.post("/v1/catalog-assets/bulk", files=[], headers=headers)
    assert response.status_code == 422, response.text
