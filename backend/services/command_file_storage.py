"""Private object storage for internal Command files."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

import boto3
from fastapi import HTTPException, UploadFile

from config import settings


def command_object_key(filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", filename)
    safe = re.sub(r"-+\.", ".", safe).strip("-.") or "file"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"command-files/{stamp}-{uuid4().hex[:12]}-{safe}"


async def upload_command_file(file: UploadFile) -> tuple[str, str, str]:
    if not (settings.R2_ENDPOINT and settings.R2_ACCESS_KEY_ID and settings.R2_SECRET_ACCESS_KEY):
        raise HTTPException(503, "Internal file storage is not configured")
    key = command_object_key(file.filename or "file")
    body = await file.read()
    if not body:
        raise HTTPException(422, "Cannot store an empty file")
    if len(body) > 25 * 1024 * 1024:
        raise HTTPException(413, "Internal files are limited to 25 MB")
    client = boto3.client("s3", endpoint_url=settings.R2_ENDPOINT, aws_access_key_id=settings.R2_ACCESS_KEY_ID, aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY, region_name=settings.R2_REGION or "auto")
    client.put_object(Bucket=settings.R2_BUCKET_NAME, Key=key, Body=body, ContentType=file.content_type or "application/octet-stream")
    return file.filename or "file", key, file.content_type or "application/octet-stream"
