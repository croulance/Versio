import httpx
from django.conf import settings


def _base() -> str:
    return settings.AUTH_API_URL.rstrip("/")


def login(email: str, password: str) -> dict | None:
    try:
        r = httpx.post(
            f"{_base()}/auth/login/",
            json={"email": email, "password": password},
            timeout=5,
        )
    except httpx.RequestError:
        return None
    return r.json() if r.status_code == 200 else None


def refresh(token: str) -> str | None:
    """Exchange a still-valid token for a new one. Returns new token string or None."""
    try:
        r = httpx.post(
            f"{_base()}/auth/refresh/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
    except httpx.RequestError:
        return None
    if r.status_code == 200:
        return r.json().get("token")
    return None


def introspect(token: str) -> dict | None:
    """
    Look up the opaque session token against the auth service.
    Returns the decoded supplier identity (supplier_id, supplier_account_id,
    email, groups, permissions, expires_at) or None if invalid/expired.
    """
    try:
        r = httpx.get(
            f"{_base()}/auth/me/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
    except httpx.RequestError:
        return None
    return r.json() if r.status_code == 200 else None
