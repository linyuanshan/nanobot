"""Minimal token-based auth and role checks for hatchery services."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

ROLE_RANK = {
    "viewer": 10,
    "operator": 20,
    "admin": 30,
}


@dataclass(slots=True)
class AuthContext:
    token: str | None
    role: str
    actor: str


def extract_token(request: Request) -> str | None:
    direct = request.headers.get("X-Hatchery-Token")
    if direct:
        return direct
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def authorize_request(
    request: Request,
    *,
    enabled: bool,
    tokens: dict[str, str],
    minimum_role: str,
    require_actor: bool = False,
) -> AuthContext:
    if not enabled:
        actor = request.headers.get("X-Hatchery-Actor", "anonymous")
        return AuthContext(token=None, role="admin", actor=actor)

    token = extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="missing hatchery token")

    role = tokens.get(token)
    if role is None:
        raise HTTPException(status_code=401, detail="invalid hatchery token")
    if ROLE_RANK.get(role, 0) < ROLE_RANK.get(minimum_role, 999):
        raise HTTPException(status_code=403, detail="insufficient hatchery role")

    actor = request.headers.get("X-Hatchery-Actor", "").strip()
    if require_actor and not actor:
        raise HTTPException(status_code=400, detail="missing X-Hatchery-Actor header")
    if not actor:
        actor = f"token:{role}"
    return AuthContext(token=token, role=role, actor=actor)


__all__ = ["AuthContext", "authorize_request", "extract_token"]
