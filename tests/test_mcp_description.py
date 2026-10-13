"""The folder's MCP description: written by the AI from the template and the folder's tables, kept on the folder,
editable, marked as stale when the template or the documents change, and given to the MCP clients."""
import pytest

from api import llm
from tests.test_live import folder, reading, upload  # noqa: F401 - fixtures
from tests.test_mcp import rpc, tool
from tests.test_public_api import outside  # noqa: F401 - fixture
from tests.test_work import ByName


class Describes(ByName):
    """Answers with a description, and keeps the prompt it got."""
    prompts = []

    def send(self, prompt, schema, model):
        if "beskrivning" not in schema["properties"]:
            return super().send(prompt, schema, model)
        Describes.prompts.append(prompt)
        return {"beskrivning": "Fondernas innehav, ett bolag per rad."}, 10, 5


@pytest.fixture
def mcp_on(anna, folder):
    """Anna's folder with a live extraction of one document, MCP on, and the folder's key."""
    anna.patch(f"/folders/{folder}", json={"auto_extract": True, "mcp_enabled": True})
    upload(anna, folder, "a.pdf", "Alfa")
    return anna.post(f"/folders/{folder}/api-key").json()["key"]


@pytest.fixture
def describes(monkeypatch, reading):
    Describes.prompts = []
    monkeypatch.setattr(llm, "FakeClient", Describes)


def test_no_description_until_made(anna, folder, mcp_on):
    assert anna.get(f"/folders/{folder}/mcp-description").json() == {"description": None, "created": None,
                                                                      "stale": False}


def test_the_ai_writes_it_from_the_template_and_the_tables(anna, folder, mcp_on, describes):
    made = anna.post(f"/folders/{folder}/mcp-description").json()
    assert made["description"] == "Fondernas innehav, ett bolag per rad." and made["created"] and not made["stale"]
    [prompt] = Describes.prompts
    assert "Hitta bolagen." in prompt  # the template's prompt
    assert "innehav" in prompt and "bolag" in prompt and "Alfa" in prompt and "a.pdf" in prompt
    assert anna.get(f"/folders/{folder}/mcp-description").json() == made


def test_it_goes_to_the_mcp_clients(anna, outside, folder, mcp_on, describes):
    anna.post(f"/folders/{folder}/mcp-description")
    instructions = rpc(outside, folder, mcp_on, "initialize", {}).json()["result"]["instructions"]
    assert "kvarn_schema" in instructions and "Fondernas innehav, ett bolag per rad." in instructions
    answer, _ = tool(outside, folder, mcp_on, "kvarn_schema")
    assert answer["beskrivning"] == "Fondernas innehav, ett bolag per rad."


def test_without_a_description_the_mcp_has_none(outside, folder, mcp_on):
    answer, _ = tool(outside, folder, mcp_on, "kvarn_schema")
    assert "beskrivning" not in answer


def test_an_edited_description_is_kept(anna, outside, folder, mcp_on, describes):
    anna.post(f"/folders/{folder}/mcp-description")
    anna.patch(f"/folders/{folder}", json={"mcp_description": "Egen text."})
    assert anna.get(f"/folders/{folder}/mcp-description").json()["description"] == "Egen text."
    assert "Egen text." in rpc(outside, folder, mcp_on, "initialize", {}).json()["result"]["instructions"]


def test_it_is_stale_when_the_documents_or_the_template_change(anna, folder, mcp_on, describes):
    anna.post(f"/folders/{folder}/mcp-description")
    upload(anna, folder, "b.pdf", "Beta")
    assert anna.get(f"/folders/{folder}/mcp-description").json()["stale"] is True

    anna.post(f"/folders/{folder}/mcp-description")
    assert anna.get(f"/folders/{folder}/mcp-description").json()["stale"] is False
    template = anna.get(f"/folders").json()[0]["template_id"]
    changed = anna.get("/templates").json()[0] | {"prompt": "Hitta fonderna."}
    assert anna.put("/templates", json=changed).json()["id"] == template
    assert anna.get(f"/folders/{folder}/mcp-description").json()["stale"] is True


def test_without_paid_calls_it_says_so(anna, folder, mcp_on):
    response = anna.post(f"/folders/{folder}/mcp-description")
    assert response.status_code == 400 and "AI" in response.json()["detail"]


def test_without_a_live_table_it_says_so(anna, folder, describes):
    response = anna.post(f"/folders/{folder}/mcp-description")
    assert response.status_code == 400 and "Extrahera automatiskt" in response.json()["detail"]


def test_only_the_owner(anna, bertil, folder, mcp_on, describes):
    assert bertil.post(f"/folders/{folder}/mcp-description").status_code == 404
    assert bertil.get(f"/folders/{folder}/mcp-description").status_code == 404
    assert Describes.prompts == []
