"""
storage.py - the uploaded files, stored once per owner as <user_id>/<sha256>.

With SUPABASE_SERVICE_KEY set: Supabase Storage, the private bucket "filer" (in production, on Vercel).
Without it: data/filer/ on disk (local development and the tests).
"""
import hashlib
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from api.auth import SUPABASE_URL

DATA = Path(os.environ.get("KVARN_DATA") or Path(__file__).parent.parent / "data")
BUCKET = "filer"


def _key() -> str | None:
    return os.environ.get("SUPABASE_SERVICE_KEY")


def _object(path: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}"


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _disk(user_id: str, sha256: str) -> Path:
    folder = DATA / "filer" / user_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder / sha256


def upload_target(user_id: str, sha256: str) -> dict:
    """Where the browser uploads the file itself, so it never passes through a Vercel function (max 4.5 MB):
    {"kind": "supabase", "path", "token"} for supabase-js's uploadToSignedUrl, or {"kind": "local", "url"} locally."""
    if key := _key():
        path = f"{user_id}/{sha256}"
        response = httpx.post(f"{SUPABASE_URL}/storage/v1/object/upload/sign/{BUCKET}/{path}", timeout=30,
                              headers=_headers(key) | {"x-upsert": "true"})
        response.raise_for_status()
        token = parse_qs(urlparse(response.json()["url"]).query)["token"][0]
        return {"kind": "supabase", "path": path, "token": token}
    return {"kind": "local", "url": f"/uploads/{sha256}"}


def save(user_id: str, data: bytes) -> str:
    """Store the file (once per owner) and return its sha256."""
    sha = hashlib.sha256(data).hexdigest()
    if key := _key():
        response = httpx.post(_object(f"{user_id}/{sha}"), content=data, timeout=120,
                              headers=_headers(key) | {"Content-Type": "application/octet-stream", "x-upsert": "true"})
        response.raise_for_status()
    elif not _disk(user_id, sha).exists():
        _disk(user_id, sha).write_bytes(data)
    return sha


def read(user_id: str, sha256: str) -> bytes:
    if key := _key():
        response = httpx.get(_object(f"{user_id}/{sha256}"), headers=_headers(key), timeout=120)
        response.raise_for_status()
        return response.content
    return _disk(user_id, sha256).read_bytes()


def delete(user_id: str, sha256: str):
    if key := _key():
        httpx.delete(_object(f"{user_id}/{sha256}"), headers=_headers(key), timeout=30).raise_for_status()
    else:
        _disk(user_id, sha256).unlink(missing_ok=True)
