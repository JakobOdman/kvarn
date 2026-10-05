"""Uploading: where to put the file, the upload, then reading it. Locally the files go to disk."""
import hashlib

import httpx
import pytest

from api import db, storage, work

FILE = b"%PDF-1.4 en liten rapport"
SHA = hashlib.sha256(FILE).hexdigest()


@pytest.fixture
def started(monkeypatch):
    """The reading itself is not tested here: the read job only records which document it got, and its file."""
    calls = []
    monkeypatch.setitem(work.HANDLERS, "read", lambda payload: calls.append(
        (payload["job_id"], storage.read(db.get_document(payload["job_id"])["user_id"], SHA))))
    return calls


@pytest.fixture
def folder(anna):
    return anna.post("/folders", json={"name": "Fonder"}).json()["id"]


def upload(client, folder, data=FILE, sha=SHA):
    target = client.post("/uploads", json={"folder_id": folder, "sha256": sha}).json()
    assert target == {"kind": "local", "url": f"/uploads/{sha}"}
    return client.put(target["url"], content=data)


def test_upload_then_read(anna, folder, started):
    assert upload(anna, folder).status_code == 200
    job = anna.post("/jobs", json={"folder_id": folder, "name": "rapport.pdf", "sha256": SHA, "words": True})
    assert job.status_code == 200
    assert started == [(job.json()["job_id"], FILE)]
    assert [d["name"] for d in anna.get(f"/jobs?folder_id={folder}").json()] == ["rapport.pdf"]
    assert storage.read(anna.user_id, SHA) == FILE


def test_a_file_that_does_not_match_its_sha_is_refused(anna, folder, started):
    assert upload(anna, folder, data=b"annat innehall").status_code == 400
    assert anna.post("/jobs", json={"folder_id": folder, "name": "a.pdf", "sha256": SHA}).status_code == 400
    assert started == []


def test_someone_elses_file_cannot_be_claimed(anna, bertil, folder, started):
    """Bertil knows the sha256 of Anna's file, but it is not in his storage."""
    upload(anna, folder)
    own = bertil.post("/folders", json={"name": "B"}).json()["id"]
    response = bertil.post("/jobs", json={"folder_id": own, "name": "kopia.pdf", "sha256": SHA})
    assert response.status_code == 400 and response.json()["detail"] == "Filen är inte uppladdad."
    assert started == []


def test_the_sha256_must_look_like_one(anna, folder):
    assert anna.post("/uploads", json={"folder_id": folder, "sha256": "../../annas"}).status_code == 422


def test_in_production_the_upload_goes_to_supabase(anna, folder, monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_test")
    signed = []

    def post(url, headers, timeout):
        signed.append(url)
        return httpx.Response(200, json={"url": f"/object/upload/sign/filer/{anna.user_id}/{SHA}?token=abc"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    target = anna.post("/uploads", json={"folder_id": folder, "sha256": SHA}).json()
    assert target == {"kind": "supabase", "path": f"{anna.user_id}/{SHA}", "token": "abc"}
    assert signed == [f"{storage.SUPABASE_URL}/storage/v1/object/upload/sign/filer/{anna.user_id}/{SHA}"]
    assert anna.put(f"/uploads/{SHA}", content=FILE).status_code == 404  # no local upload in production
