from __future__ import annotations


def test_register_login_flow_smoke(client) -> None:
    register_payload = {
        "email": "smoke@example.com",
        "password": "smoke-pass-123",
        "display_name": "Smoke User",
    }

    register = client.post("/v1/auth/register", json=register_payload)
    assert register.status_code == 201, register.text
    token = register.json().get("token")
    assert isinstance(token, str) and token

    login = client.post(
        "/v1/auth/login",
        json={"email": register_payload["email"], "password": register_payload["password"]},
    )
    assert login.status_code == 200, login.text
    assert isinstance(login.json().get("token"), str)
