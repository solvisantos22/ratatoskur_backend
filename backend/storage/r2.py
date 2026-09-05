from __future__ import annotations

import os
from functools import lru_cache

import boto3
from botocore.client import Config


class R2ConfigurationError(RuntimeError):
    pass


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise R2ConfigurationError(f"{name} is not set")
    return value


@lru_cache(maxsize=1)
def _build_s3_client():
    account_id = _required_env("R2_ACCOUNT_ID")
    access_key_id = _required_env("R2_ACCESS_KEY_ID")
    secret_access_key = _required_env("R2_SECRET_ACCESS_KEY")
    endpoint_url = os.getenv("R2_ENDPOINT_URL") or f"https://{account_id}.r2.cloudflarestorage.com"
    region = os.getenv("R2_REGION", "auto")
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )


def upload_bytes(*, key: str, data: bytes, content_type: str) -> str:
    if os.getenv("STORAGE_BACKEND", "r2").lower() == "local":
        from backend.storage.local import upload_local
        return upload_local(key=key, data=data)
    bucket_name = _required_env("R2_BUCKET_NAME")
    client = _build_s3_client()
    client.put_object(
        Bucket=bucket_name,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key


def presigned_get_url(*, key: str, expires_in_seconds: int = 900) -> str:
    if os.getenv("STORAGE_BACKEND", "r2").lower() == "local":
        from backend.storage.local import local_get_url
        return local_get_url(key=key, expires_in_seconds=expires_in_seconds)
    bucket_name = _required_env("R2_BUCKET_NAME")
    client = _build_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": key},
        ExpiresIn=expires_in_seconds,
    )


def delete_bytes(*, key: str) -> None:
    if os.getenv("STORAGE_BACKEND", "r2").lower() == "local":
        from backend.storage.local import artifact_path
        artifact_path(key).unlink(missing_ok=True)
        return
    _build_s3_client().delete_object(Bucket=_required_env("R2_BUCKET_NAME"), Key=key)


def download_bytes(*, key: str, max_bytes: int = 32 * 1024 * 1024) -> bytes:
    """Read a known server-owned object with a bounded allocation."""
    if os.getenv("STORAGE_BACKEND", "r2").lower() == "local":
        from backend.storage.local import artifact_path
        with artifact_path(key).open("rb") as stream:
            data = stream.read(max_bytes + 1)
    else:
        response = _build_s3_client().get_object(Bucket=_required_env("R2_BUCKET_NAME"), Key=key)
        stream = response["Body"]
        try:
            data = stream.read(max_bytes + 1)
        finally:
            stream.close()
    if len(data) > max_bytes:
        raise ValueError("Artifact exceeds the read limit")
    return data
