"""Everyone sees only their own: someone else's folder, document, template or extraction is a 404."""

import pytest
from fastapi.testclient import TestClient

from api import db, llm, storage
from api.extract import ENGINE_PROMPT
from api.main import app
from api.templates import Template, schema_for
from tests.conftest import API, TEMPLATE, add_read_document

OWN = ["/jobs/{doc}", "/jobs/{doc}/file", "/templates/{template}", "/extractions/{extraction}",
       "/extractions/{extraction}/xlsx"]


def test_logged_out_gets_401(annas):
    client = TestClient(app, base_url=API)
    for path in ["/folders", "/jobs", "/templates", "/extractions", *(p.format(**annas) for p in OWN)]:
        assert client.get(path).status_code == 401, path


def test_lists_show_only_your_own(annas, anna, bertil):
    for path in ["/folders", "/jobs", "/templates", "/extractions"]:
        assert len(anna.get(path).json()) == 1, path
        assert bertil.get(path).json() == [], path


@pytest.mark.parametrize("path", OWN)
def test_getting_someone_elses_is_404(annas, anna, bertil, path):
    path = path.format(**annas)
    assert anna.get(path).status_code == 200
    assert bertil.get(path).status_code == 404


def test_changing_someone_elses_is_404(annas, anna, bertil):
    own_template = bertil.put("/templates", json=TEMPLATE).json()["id"]
    attempts = [
        bertil.patch(f"/folders/{annas['folder']}", json={"name": "Bertils nu"}),
        bertil.delete(f"/folders/{annas['folder']}"),
        bertil.delete(f"/jobs/{annas['doc']}"),
        bertil.post(f"/jobs/{annas['doc']}/reread"),
        bertil.delete(f"/templates/{annas['template']}"),
        bertil.put("/templates", json={**TEMPLATE, "id": annas["template"], "name": "Kapad"}),
        bertil.post("/uploads", json={"folder_id": annas["folder"], "sha256": "0" * 64}),
        bertil.post("/jobs", json={"folder_id": annas["folder"], "name": "a.txt", "sha256": "0" * 64}),
        bertil.post("/extractions", json={"template_id": annas["template"]}),
        bertil.post("/extractions", json={"template_id": own_template, "folder_id": annas["folder"]}),
        bertil.post("/extractions", json={"template_id": own_template, "job_ids": [annas["doc"]]}),
    ]
    assert [r.status_code for r in attempts] == [404] * len(attempts)

    # And nothing of Anna's has changed
    assert anna.get("/folders").json()[0]["name"] == "Annas mapp"
    assert anna.get("/folders").json()[0]["document_count"] == 1
    assert anna.get(f"/templates/{annas['template']}").json()["name"] == "Innehav"
    assert len(anna.get("/extractions").json()) == 1


def test_your_own_work(bertil):
    folder = bertil.post("/folders", json={"name": "Bertils mapp"}).json()["id"]
    add_read_document(folder)
    template = bertil.put("/templates", json=TEMPLATE).json()
    extraction = bertil.post("/extractions", json={"template_id": template["id"], "folder_id": folder}).json()
    assert len(template["id"]) == 32  # a random id, not made from the name
    assert bertil.get(f"/extractions/{extraction['extraction_id']}").json()["status"] == "done"


def test_the_same_file_is_stored_once_per_owner(anna, bertil):
    a = anna.post("/folders", json={"name": "A"}).json()["id"]
    b = bertil.post("/folders", json={"name": "B"}).json()["id"]
    doc_a, doc_b = add_read_document(a, text="Samma"), add_read_document(b, text="Samma")
    sha = db.get_document(doc_a)["sha256"]
    owners = {p.parent.name for p in (storage.DATA / "filer").glob(f"*/{sha}")}
    assert owners == {anna.user_id, bertil.user_id}

    anna.delete(f"/jobs/{doc_a}")
    assert len(list((storage.DATA / "filer").glob(f"*/{sha}"))) == 1
    assert bertil.get(f"/jobs/{doc_b}/file").content == b"Samma"


def test_the_cache_is_per_owner(anna, bertil, monkeypatch):
    """Anna's saved answer is free for Anna, but Bertil running the same text and template gets nothing from it."""
    monkeypatch.setattr(llm, "FakeClient", NotCalled)
    prompt = f"{TEMPLATE['prompt']}\n\n{ENGINE_PROMPT}\n=== Sida 1 ===\nSamma text"
    db.Cache(anna.user_id).put(llm.cache_key(prompt, schema_for(Template(**TEMPLATE)), llm.MODEL),
                               {"model": llm.MODEL, "tokens_in": 1, "tokens_out": 1, "answer": {"innehav": []}})

    def run(client):
        folder = client.post("/folders", json={"name": "F"}).json()["id"]
        add_read_document(folder, text="Samma text")
        template = client.put("/templates", json=TEMPLATE).json()["id"]
        e = client.post("/extractions", json={"template_id": template, "folder_id": folder}).json()["extraction_id"]
        return client.get(f"/extractions/{e}").json()["documents"][0]

    assert run(anna)["cached"] is True
    assert run(bertil)["error"] == "Inget sparat svar"  # not in Bertil's cache, so it went to the client


class NotCalled(llm.FakeClient):
    def send(self, *args):
        raise RuntimeError("Inget sparat svar")


def test_times_are_utc_with_their_offset(anna):
    """The browser reads a time without an offset as its own local time: on Vercel (UTC) that was 2 hours off."""
    folder = anna.post("/folders", json={"name": "F"}).json()
    assert folder["created"].endswith("+00:00")
