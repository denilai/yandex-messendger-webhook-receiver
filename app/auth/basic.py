from __future__ import annotations

import logging
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def _challenge(realm: str) -> dict[str, str]:
    # Realm must be quoted per RFC 7617.
    return {"WWW-Authenticate": f'Basic realm="{realm}"'}


def require_basic_auth(
    credentials: HTTPBasicCredentials | None = Depends(HTTPBasic(auto_error=False)),
    settings: Settings = Depends(get_settings),
) -> None:
    if credentials is None:
        logger.warning("Auth failed: no credentials provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers=_challenge(settings.basic_auth_realm),
        )

    ok_user = secrets.compare_digest(credentials.username, settings.basic_auth_username)
    ok_pass = secrets.compare_digest(credentials.password, settings.basic_auth_password)
    if not (ok_user and ok_pass):
        logger.warning("Auth failed: invalid credentials username=%s", credentials.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers=_challenge(settings.basic_auth_realm),
        )

