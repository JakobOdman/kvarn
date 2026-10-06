"""Other systems read a folder's live extraction with the folder's API key, and nothing else."""
import pytest
from fastapi.testclient import TestClient

from api.main import app
from tests.conftest import API
from tests.test_live import folder, reading, upload  # noqa: F401 - fixtures


@pytest.fixture
def outside():
    """Another system: not logged in, only the key."""
    return TestClient(app, base_url=API)


def get(client, path, key):
    return client.get(f"/public{path}", headers={"Authorization": f"Bearer {key}"})


def test_the_live_table_with_the_folders_key(anna, folder, outside):
    anna.patch(f"/folders/{folder}", json={"auto_extract": True})
    upload(anna, folder, "a.pdf", "Alfa")
    key = anna.post(f"/folders/{folder}/api-key").json()["key"]
    assert key.startswith("kvarn_")
    assert get(outside, f"/folders/{folder}/tables", key).json() == ["innehav"]
    assert get(outside, f"/folders/{folder}/tables/innehav", key).json() == [
        {"dokument": "a.pdf", "bolag": "Alfa", "varde": "1", "sida": 1}]
    assert get(outside, f"/folders/{folder}/tables/finns-inte", key).status_code == 404


def test_the_key_is_shown_once_and_a_new_one_replaces_it(anna, folder, outside):
    anna.patch(f"/folders/{folder}", json={"auto_extract": True})
    upload(anna, folder, "a.pdf", "Alfa")
    old = anna.post(f"/folders/{folder}/api-key").json()["key"]
    [f] = anna.get("/folders").json()
    assert f["api_key_created"] and "api_key_hash" not in f and old not in str(f)
    assert "api_key_hash" not in anna.patch(f"/folders/{folder}", json={"name": "Ny"}).json()

    new = anna.post(f"/folders/{folder}/api-key").json()["key"]
    assert get(outside, f"/folders/{folder}/tables", old).status_code == 401
    assert get(outside, f"/folders/{folder}/tables", new).status_code == 200
    anna.delete(f"/folders/{folder}/api-key")
    assert get(outside, f"/folders/{folder}/tables", new).status_code == 401


def test_wrong_key_and_unknown_folder_look_the_same(anna, bertil, folder, outside):
    key = anna.post(f"/folders/{folder}/api-key").json()["key"]
    own = bertil.post("/folders", json={"name": "Bertils"}).json()["id"]
    bertils = bertil.post(f"/folders/{own}/api-key").json()["key"]
    responses = [get(outside, f"/folders/{folder}/tables", "kvarn_gissad"),
                 get(outside, f"/folders/{folder}/tables", bertils),  # a real key, for another folder
                 get(outside, "/folders/finns-inte/tables", key),
                 outside.get(f"/public/folders/{folder}/tables")]  # no key
    assert [(r.status_code, r.json()["detail"]) for r in responses] == [(401, "Fel eller saknad API-nyckel.")] * 4


def test_without_a_live_table_it_says_so(anna, folder, outside):
    key = anna.post(f"/folders/{folder}/api-key").json()["key"]
    response = get(outside, f"/folders/{folder}/tables", key)
    assert response.status_code == 404 and "Extrahera automatiskt" in response.json()["detail"]


def test_the_key_does_not_log_in(anna, folder, outside):
    key = anna.post(f"/folders/{folder}/api-key").json()["key"]
    for path in ["/folders", f"/jobs?folder_id={folder}", "/templates", "/extractions"]:
        assert outside.get(path, headers={"Authorization": f"Bearer {key}"}).status_code == 401
