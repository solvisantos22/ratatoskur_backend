"""Explicit development storage with expiring, key-bound HMAC URLs."""

from __future__ import annotations

import hashlib
import hmac
import mimetypes
import os
from pathlib import Path
import re
import time
from urllib.parse import quote, urlencode, urlsplit

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter(tags=["local artifacts"])


def artifact_path(key: str) -> Path:
    if (
        not key
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", key)
        or any(part in {"", ".", ".."} for part in key.split("/"))
    ):
        raise ValueError("Invalid artifact key")
    root = Path(os.getenv("LOCAL_STORAGE_DIR", ".local/artifacts")).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Artifact key leaves the storage directory")
    return path


def _signature(key: str, expires: int) -> str:
    secret = os.getenv("LOCAL_STORAGE_SIGNING_SECRET", "")
    if len(secret) < 32:
        from backend.storage.r2 import R2ConfigurationError

        raise R2ConfigurationError(
            "LOCAL_STORAGE_SIGNING_SECRET must contain at least 32 characters"
        )
    return hmac.new(
        secret.encode(), f"{key}\n{expires}".encode(), hashlib.sha256
    ).hexdigest()


def upload_local(*, key: str, data: bytes) -> str:
    path = artifact_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def local_get_url(*, key: str, expires_in_seconds: int = 900) -> str:
    artifact_path(key)
    base_url = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.query
        or parsed.fragment
        or parsed.username
    ):
        from backend.storage.r2 import R2ConfigurationError

        raise R2ConfigurationError(
            "PUBLIC_BASE_URL must be an absolute HTTP(S) base URL"
        )
    expires = int(time.time()) + min(max(expires_in_seconds, 1), 900)
    params = urlencode({"expires": expires, "signature": _signature(key, expires)})
    return f"{base_url}/local-artifacts/{quote(key, safe='/')}?{params}"


@router.get("/local-artifacts/{key:path}", include_in_schema=False)
def read_local_artifact(key: str, expires: int, signature: str):
    if os.getenv("STORAGE_BACKEND", "r2").lower() != "local":
        raise HTTPException(status_code=404, detail="Not found")
    try:
        path = artifact_path(key)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Invalid artifact link") from exc
    now = int(time.time())
    if (
        expires <= now
        or expires > now + 900
        or not hmac.compare_digest(_signature(key, expires), signature)
    ):
        raise HTTPException(status_code=403, detail="Invalid or expired artifact link")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(
        path,
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
