from jose import jwt

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.core.exceptions import UnauthorizedException


def test_project_order_by_is_enum_limited(client, auth_header):
    valid = client.get("/api/projects?order_by=name&order=asc", headers=auth_header)
    assert valid.status_code == 200
    assert valid.json()["code"] == 0

    invalid = client.get("/api/projects?order_by=owner_id", headers=auth_header)
    assert invalid.status_code == 422
    assert invalid.json()["code"] == 42200


def test_registration_and_login_normalize_email_and_duplicate_is_conflict(client):
    registered = client.post(
        "/api/auth/register",
        json={"email": "  CaseUser@Example.COM ", "password": "password123", "nickname": "Case User"},
    )
    assert registered.status_code == 200, registered.text
    assert registered.json()["data"]["user"]["email"] == "caseuser@example.com"

    duplicate = client.post(
        "/api/auth/register",
        json={"email": "CASEUSER@example.com", "password": "password123", "nickname": "Other"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == 40900

    login = client.post(
        "/api/auth/login",
        json={"email": " CASEUSER@EXAMPLE.COM ", "password": "password123"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["data"]["user"]["email"] == "caseuser@example.com"


def test_jwt_sub_must_be_positive_integer():
    settings = get_settings()
    for raw_sub in [None, "abc", "0", "-1", "9" * 5000, 0, -1, True, 1.5]:
        claims = {"exp": 4102444800}
        if raw_sub is not None:
            claims["sub"] = raw_sub
        token = jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)
        try:
            decode_access_token(token)
        except UnauthorizedException:
            pass
        else:
            raise AssertionError(f"非法 sub 未被拒绝: {raw_sub!r}")

    valid = jwt.encode({"sub": "1", "exp": 4102444800}, settings.secret_key, algorithm=settings.algorithm)
    assert decode_access_token(valid)["sub"] == "1"
