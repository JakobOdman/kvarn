"""A folder's live extraction: with automatic extraction on, every read document goes into it, and it always
has the folder's documents as they are now."""
import hashlib

import pytest

from api import db, llm, work
from tests.conftest import TEMPLATE, add_read_document
from tests.test_work import ByName, Read


@pytest.fixture
def reading(monkeypatch):
    """Reading gives the file's content as the text of its one page. ByName makes one row of it."""
    monkeypatch.setattr(llm, "FakeClient", ByName)
    monkeypatch.setattr(work, "read_document", lambda data, name, **kw: Read(
        pages=[{"page_no": 1, "text": data.decode(), "reader": "pdf_text"}]))


@pytest.fixture
def folder(anna, reading):
    """Anna's folder with a template, automatic extraction still off."""
    template = anna.put("/templates", json=TEMPLATE).json()["id"]
    folder = anna.post("/folders", json={"name": "Fonder"}).json()["id"]
    assert anna.patch(f"/folders/{folder}", json={"template_id": template}).status_code == 200
    return folder


def upload(client, folder, name, text):
    """Upload and read a file, as the app does."""
    data = text.encode()
    sha = hashlib.sha256(data).hexdigest()
    client.post("/uploads", json={"folder_id": folder, "sha256": sha})
    client.put(f"/uploads/{sha}", content=data)
    return client.post("/jobs", json={"folder_id": folder, "name": name, "sha256": sha}).json()["job_id"]


def live(client):
    runs = [e for e in client.get("/extractions").json() if e["live"]]
    assert len(runs) <= 1
    return client.get(f"/extractions/{runs[0]['id']}").json() if runs else None


def rows(extraction):
    return [(r["dokument"], r["bolag"]) for r in extraction["tables"]["innehav"]]


def test_without_automatic_extraction_nothing_is_extracted(anna, folder):
    upload(anna, folder, "a.pdf", "Alfa")
    assert anna.get("/extractions").json() == []


def test_read_documents_go_into_the_live_extraction(anna, folder):
    anna.patch(f"/folders/{folder}", json={"auto_extract": True})
    assert live(anna) is None  # nothing read yet
    upload(anna, folder, "a.pdf", "Alfa")
    upload(anna, folder, "b.pdf", "Beta")
    extraction = live(anna)
    assert extraction["status"] == "done"
    assert rows(extraction) == [("a.pdf", "Alfa"), ("b.pdf", "Beta")]


def test_turning_it_on_runs_the_documents_already_read(anna, folder):
    add_read_document(folder, "a.pdf", "Alfa")
    add_read_document(folder, "b.pdf", "Beta")
    anna.patch(f"/folders/{folder}", json={"auto_extract": True})
    assert rows(live(anna)) == [("a.pdf", "Alfa"), ("b.pdf", "Beta")]
    anna.patch(f"/folders/{folder}", json={"auto_extract": True})  # on again: nothing is run again
    assert len(anna.get("/extractions").json()) == 1


def test_a_new_version_replaces_its_rows(anna, folder):
    anna.patch(f"/folders/{folder}", json={"auto_extract": True})
    upload(anna, folder, "a.pdf", "Alfa")
    upload(anna, folder, "b.pdf", "Beta")
    upload(anna, folder, "a.pdf", "Alfa version 2")
    extraction = live(anna)
    assert sorted(rows(extraction)) == [("a.pdf", "Alfa version 2"), ("b.pdf", "Beta")]
    assert [d["name"] for d in extraction["documents"]] == ["b.pdf", "a.pdf"]


def test_a_removed_document_leaves_with_its_rows(anna, folder):
    anna.patch(f"/folders/{folder}", json={"auto_extract": True})
    a = upload(anna, folder, "a.pdf", "Alfa")
    upload(anna, folder, "b.pdf", "Beta")
    anna.delete(f"/jobs/{a}")
    assert rows(live(anna)) == [("b.pdf", "Beta")]


def test_turned_off_it_becomes_an_ordinary_extraction(anna, folder):
    anna.patch(f"/folders/{folder}", json={"auto_extract": True})
    upload(anna, folder, "a.pdf", "Alfa")
    anna.patch(f"/folders/{folder}", json={"auto_extract": False})
    upload(anna, folder, "b.pdf", "Beta")
    assert live(anna) is None
    [earlier] = anna.get("/extractions").json()
    assert rows(anna.get(f"/extractions/{earlier['id']}").json()) == [("a.pdf", "Alfa")]


def test_a_deleted_folder_keeps_its_rows(anna, folder):
    anna.patch(f"/folders/{folder}", json={"auto_extract": True})
    upload(anna, folder, "a.pdf", "Alfa")
    anna.delete(f"/folders/{folder}")
    [earlier] = anna.get("/extractions").json()
    assert not earlier["live"]
    assert rows(anna.get(f"/extractions/{earlier['id']}").json()) == [("a.pdf", "Alfa")]


def test_a_changed_template_is_shown_and_run_again_on_request(anna, folder):
    anna.patch(f"/folders/{folder}", json={"auto_extract": True})
    upload(anna, folder, "a.pdf", "Alfa")
    first = live(anna)
    assert first["template_changed"] is False

    template = anna.get(f"/templates/{first['template_id']}").json()
    anna.put("/templates", json=template | {"prompt": "Hitta alla bolag."})
    assert live(anna)["template_changed"] is True
    upload(anna, folder, "b.pdf", "Beta")  # still with the template it started with
    assert live(anna)["template"]["prompt"] == "Hitta bolagen."

    again = anna.post(f"/folders/{folder}/live").json()["extraction_id"]
    now = live(anna)
    assert now["id"] == again and now["template_changed"] is False
    assert now["template"]["prompt"] == "Hitta alla bolag."
    assert rows(now) == [("a.pdf", "Alfa"), ("b.pdf", "Beta")]
    assert not anna.get(f"/extractions/{first['id']}").json()["live"]


def test_automatic_extraction_needs_a_template(anna, reading):
    folder = anna.post("/folders", json={"name": "Utan mall"}).json()["id"]
    response = anna.patch(f"/folders/{folder}", json={"auto_extract": True})
    assert response.status_code == 400
    assert anna.post(f"/folders/{folder}/live").status_code == 400
    assert anna.get("/folders").json()[0]["auto_extract"] is False


def test_only_what_is_sent_is_changed(anna, folder):
    anna.patch(f"/folders/{folder}", json={"name": "Nytt namn"})
    [f] = anna.get("/folders").json()
    assert (f["name"], f["auto_extract"]) == ("Nytt namn", False) and f["template_id"]
    assert anna.patch(f"/folders/{folder}", json={"name": " "}).status_code == 400
    assert anna.patch(f"/folders/{folder}", json={"template_id": None}).json()["template_id"] is None
