"""
Shared fixtures. The tests run against a throwaway Postgres, started once and emptied between tests.
Every test gets an empty data folder and cache of its own, and can never make a paid call.

    venv/bin/pytest    # Postgres's initdb and pg_ctl from PG_BIN, default /Library/PostgreSQL/15/bin
"""
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from api import auth, db, jobs, llm, storage
from api.main import app

TEMPLATE = {"name": "Innehav", "prompt": "Hitta bolagen.",
            "tables": [{"name": "innehav", "fields": [{"name": "bolag"}, {"name": "varde"}]}]}


API = "http://testserver/api"  # the clients' base: client.get("/folders") is /api/folders
PG_BIN = Path(os.environ.get("PG_BIN", "/Library/PostgreSQL/15/bin"))
TABLES = "folders, documents, extractions, templates, llm_cache, usage"
KEY = ec.generate_private_key(ec.SECP256R1())  # stands in for Supabase's signing key


@pytest.fixture(scope="session", autouse=True)
def postgres():
    """A Postgres of our own in a temp folder, on a free port. Stopped and removed after the tests."""
    folder = Path(tempfile.mkdtemp(prefix="kvarn-pg-"))
    with socket.socket() as s:
        s.bind(("localhost", 0))
        port = s.getsockname()[1]
    subprocess.run([PG_BIN / "initdb", "-D", folder / "data", "-U", "postgres", "--auth=trust", "-E", "UTF8"],
                   check=True, capture_output=True)
    subprocess.run([PG_BIN / "pg_ctl", "-D", folder / "data", "-l", folder / "log", "-w", "start",
                    "-o", f"-p {port} -c listen_addresses=localhost -k {folder}"], check=True, capture_output=True)
    os.environ["DATABASE_URL"] = f"postgresql://postgres@localhost:{port}/postgres"
    db.close()
    db.create_schema()
    yield
    db.close()
    subprocess.run([PG_BIN / "pg_ctl", "-D", folder / "data", "-m", "immediate", "stop"], capture_output=True)
    shutil.rmtree(folder, ignore_errors=True)


class TestKeys:
    """Instead of Supabase's public keys: our test key's."""

    def get_signing_key_from_jwt(self, token):
        return KEY.public_key()


class NoPaidCalls:
    def __init__(self):
        raise AssertionError("Testerna får aldrig skapa en riktig AI-klient.")


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    with db.connect() as con:
        con.execute(f"TRUNCATE {TABLES}")
    monkeypatch.setattr(storage, "DATA", tmp_path / "data")
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)  # files on disk, never in Supabase
    monkeypatch.delenv("READ_DOCUMENT_PAID", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(llm, "AzureClient", NoPaidCalls)
    monkeypatch.setattr(auth, "_keys", TestKeys())
    monkeypatch.setattr(jobs, "INLINE", True)  # background jobs run right away, so the tests can check them
    monkeypatch.delenv("VERCEL", raising=False)


def token(user_id: str, email: str, key=KEY, **claims) -> str:
    """An access token like the ones Supabase gives, signed with the test key."""
    payload = {"sub": user_id, "email": email, "aud": "authenticated", "iss": auth.ISSUER,
               "exp": int(time.time()) + 3600, "user_metadata": {"name": email.split("@")[0].title()}}
    return jwt.encode(payload | claims, key, algorithm="ES256")


def login(email: str) -> TestClient:
    """A client logged in as a new user. client.user_id is the user's id."""
    client = TestClient(app, base_url=API)
    client.user_id = str(uuid4())
    client.headers["Authorization"] = f"Bearer {token(client.user_id, email)}"
    assert client.get("/me").status_code == 200
    return client


@pytest.fixture
def anna() -> TestClient:
    return login("anna@example.se")


@pytest.fixture
def bertil() -> TestClient:
    return login("bertil@example.se")


def add_read_document(folder_id: str, name: str = "rapport.pdf", text: str = "Bolag AB 100") -> str:
    """A document that is already read, without going through read_document.py."""
    doc_id = uuid4().hex
    with db.connect() as con:
        owner = con.execute("SELECT user_id FROM folders WHERE id = %s", (folder_id,)).fetchone()["user_id"]
    sha = storage.save(owner, text.encode())
    db.add_document(doc_id, name, sha, {"allow_model": False, "max_model_pages": None, "model": "", "words": False},
                    folder_id)
    db.update_document(doc_id, "done", result={"ok": True, "page_count": 1,
                                               "pages": [{"page_no": 1, "text": text, "reader": "pdf_text"}]})
    return doc_id


@pytest.fixture
def annas(anna) -> dict:
    """Anna's folder, document, template and extraction (run with the fake client)."""
    folder = anna.post("/folders", json={"name": "Annas mapp"}).json()["id"]
    doc = add_read_document(folder)
    template = anna.put("/templates", json=TEMPLATE).json()["id"]
    extraction = anna.post("/extractions", json={"template_id": template, "folder_id": folder}).json()["extraction_id"]
    return {"folder": folder, "doc": doc, "template": template, "extraction": extraction}
