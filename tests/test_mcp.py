"""A folder's MCP server: Claude and Copilot Studio ask questions about the folder's live extraction with the
folder's key, and only when MCP is turned on for the folder."""
import json

import pytest

from api import mcp
from tests.test_live import folder, reading, upload  # noqa: F401 - fixtures
from tests.test_public_api import outside  # noqa: F401 - fixture

TEMPLATE = {"name": "Innehav", "prompt": "Hitta bolagen.",
            "tables": [{"name": "innehav", "description": "Bolagen i fonden",
                        "fields": [{"name": "bolag", "description": "Bolagets namn"},
                                   {"name": "varde", "type": "choice", "choices": ["1", "2"]},
                                   {"name": "belopp (kr)"}, {"name": "samling"}, {"name": "citat"}]}]}


@pytest.fixture
def key(anna, folder):
    """Anna's folder "Fonder" with MCP on, two read documents in its live extraction, and the folder's key."""
    template = anna.put("/templates", json=TEMPLATE).json()["id"]
    anna.patch(f"/folders/{folder}", json={"template_id": template, "auto_extract": True, "mcp_enabled": True})
    upload(anna, folder, "a.pdf", "Alfa")
    upload(anna, folder, "b.pdf", "Beta")
    return anna.post(f"/folders/{folder}/api-key").json()["key"]


def rpc(client, folder, key, method, params=None, id=1):
    body = {"jsonrpc": "2.0", "method": method} | ({"id": id} if id is not None else {})
    body |= {"params": params} if params is not None else {}
    return client.post(f"/public/folders/{folder}/mcp", json=body, headers={
        "Authorization": f"Bearer {key}", "Accept": "application/json, text/event-stream"})


def tool(client, folder, key, name, **arguments):
    """(answer, is_error): the answer parsed from JSON, or the error text."""
    result = rpc(client, folder, key, "tools/call", {"name": name, "arguments": arguments}).json()["result"]
    text = result["content"][0]["text"]
    return (text, True) if result.get("isError") else (json.loads(text), False)


def sql(client, folder, key, query):
    return tool(client, folder, key, "kvarn_sql", fraga=query)


def test_mcp_is_off_until_turned_on(anna, folder):
    [f] = anna.get("/folders").json()
    assert f["mcp_enabled"] is False
    assert anna.patch(f"/folders/{folder}", json={"mcp_enabled": True}).json()["mcp_enabled"] is True
    [f] = anna.get("/folders").json()
    assert f["mcp_enabled"] is True


def test_only_the_owner_turns_it_on(anna, bertil, folder):
    assert bertil.patch(f"/folders/{folder}", json={"mcp_enabled": True}).status_code == 404
    [f] = anna.get("/folders").json()
    assert f["mcp_enabled"] is False


def test_initialize_names_the_server_after_the_folder(outside, folder, key):
    result = rpc(outside, folder, key, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                     "clientInfo": {"name": "test", "version": "1"}}).json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "Fonder"
    assert result["capabilities"] == {"tools": {}}
    assert "kvarn_schema" in result["instructions"] and "citat" in result["instructions"]


def test_an_unknown_protocol_version_gets_ours(outside, folder, key):
    result = rpc(outside, folder, key, "initialize", {"protocolVersion": "1999-01-01"}).json()["result"]
    assert result["protocolVersion"] == mcp.VERSIONS[0]


def test_notifications_get_202(outside, folder, key):
    response = rpc(outside, folder, key, "notifications/initialized", id=None)
    assert response.status_code == 202 and response.content == b""


def test_the_two_tools(outside, folder, key):
    tools = rpc(outside, folder, key, "tools/list").json()["result"]["tools"]
    assert [t["name"] for t in tools] == ["kvarn_schema", "kvarn_sql"]
    assert all(t["annotations"]["readOnlyHint"] for t in tools)


def test_schema_has_the_templates_descriptions_and_the_values(outside, folder, key):
    answer, error = tool(outside, folder, key, "kvarn_schema")
    assert not error
    assert answer["samling"] == "Fonder" and answer["mall"] == "Innehav"
    assert answer["dokument"] == ["a.pdf", "b.pdf"]
    innehav = answer["tabeller"]["innehav"]
    assert innehav["beskrivning"] == "Bolagen i fonden" and innehav["rader"] == 2
    assert list(innehav["kolumner"]) == ["samling", "dokument", "bolag", "varde", "belopp (kr)", "citat", "sida"]
    assert innehav["kolumner"]["bolag"] == "Bolagets namn"
    assert innehav["värden i varde"] == ["1"]


def test_sql_gives_rows_with_the_folder_and_the_source(outside, folder, key):
    rows, error = sql(outside, folder, key, "SELECT samling, dokument, bolag, sida FROM innehav ORDER BY dokument")
    assert not error
    assert rows == [{"samling": "Fonder", "dokument": "a.pdf", "bolag": "Alfa", "sida": 1},
                    {"samling": "Fonder", "dokument": "b.pdf", "bolag": "Beta", "sida": 1}]
    rows, _ = sql(outside, folder, key, 'SELECT "belopp (kr)", citat FROM innehav LIMIT 1')
    assert rows == [{"belopp (kr)": None, "citat": None}]


def test_sql_only_reads(outside, folder, key, tmp_path):
    for query in ["DELETE FROM innehav", "UPDATE innehav SET bolag = 'x'", "DROP TABLE innehav",
                  "PRAGMA query_only = OFF", f"ATTACH DATABASE '{tmp_path / 'x.db'}' AS x",
                  "SELECT 1; DELETE FROM innehav"]:
        text, error = sql(outside, folder, key, query)
        assert error and "kvarn_schema" in text, query
    assert not (tmp_path / "x.db").exists()
    rows, _ = sql(outside, folder, key, "SELECT count(*) AS n FROM innehav")
    assert rows == [{"n": 2}]


def test_sql_gives_at_most_200_rows(outside, folder, key):
    rows, error = sql(outside, folder, key, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n "
                                            "WHERE i < 500) SELECT i FROM n")
    assert not error and len(rows) == 200


def test_a_query_that_never_ends_is_stopped(outside, folder, key, monkeypatch):
    monkeypatch.setattr(mcp, "SECONDS", 0.2)
    text, error = sql(outside, folder, key, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) "
                                            "SELECT count(*) FROM n")
    assert error and "för lång tid" in text


def test_sql_errors_point_to_the_schema(outside, folder, key):
    text, error = sql(outside, folder, key, "SELECT finns_inte FROM innehav")
    assert error and "finns_inte" in text and "kvarn_schema" in text
    text, error = tool(outside, folder, key, "kvarn_sql")
    assert error and "fraga" in text


def test_without_a_live_table_the_tools_say_so(anna, outside, folder, key):
    anna.patch(f"/folders/{folder}", json={"auto_extract": False})  # the live extraction ends
    assert rpc(outside, folder, key, "initialize", {}).status_code == 200
    for name in ["kvarn_schema", "kvarn_sql"]:
        text, error = tool(outside, folder, key, name, fraga="SELECT 1")
        assert error and "Extrahera automatiskt" in text


def test_wrong_key_turned_off_and_get(anna, outside, folder, key):
    assert rpc(outside, folder, "kvarn_gissad", "tools/list").status_code == 401
    assert rpc(outside, "finns-inte", key, "tools/list").status_code == 401
    anna.patch(f"/folders/{folder}", json={"mcp_enabled": False})
    response = rpc(outside, folder, key, "tools/list")
    assert response.status_code == 404 and response.json()["detail"] == "MCP är inte påslaget för samlingen."
    anna.patch(f"/folders/{folder}", json={"mcp_enabled": True})
    get = outside.get(f"/public/folders/{folder}/mcp", headers={"Authorization": f"Bearer {key}"})
    assert get.status_code == 405


def test_json_rpc_errors(outside, folder, key):
    assert rpc(outside, folder, key, "finns/inte").json()["error"]["code"] == -32601
    response = rpc(outside, folder, key, "tools/call", {"name": "finns_inte", "arguments": {}})
    assert response.json()["error"]["code"] == -32602
    response = outside.post(f"/public/folders/{folder}/mcp", content=b"{inte json",
                            headers={"Authorization": f"Bearer {key}"})
    assert response.json()["error"]["code"] == -32700


def test_huge_values_and_answers_are_refused(outside, folder, key):
    text, error = sql(outside, folder, key, "SELECT zeroblob(5000000) AS b")
    assert error and "kvarn_schema" in text
    text, error = sql(outside, folder, key, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n "
                                            "WHERE i < 20) SELECT printf('%.*c', 200000, 'x') FROM n")
    assert error and "för stort" in text


def test_names_that_differ_only_in_case_still_work(anna, outside, folder):
    template = anna.put("/templates", json={"name": "Skiftläge", "prompt": "Hitta bolagen.", "tables": [
        {"name": "innehav", "fields": [{"name": "Dokument"}, {"name": "bolag"}, {"name": "Bolag"}]},
        {"name": "Innehav", "fields": [{"name": "x"}]}]}).json()["id"]
    anna.patch(f"/folders/{folder}", json={"template_id": template, "auto_extract": True, "mcp_enabled": True})
    upload(anna, folder, "a.pdf", "Alfa")
    key = anna.post(f"/folders/{folder}/api-key").json()["key"]
    answer, error = tool(outside, folder, key, "kvarn_schema")
    assert not error and list(answer["tabeller"]["innehav"]["kolumner"]) == [
        "samling", "dokument", "bolag", "sida", "citat"]
    rows, error = sql(outside, folder, key, "SELECT dokument, bolag FROM innehav")
    assert not error and rows == [{"dokument": "a.pdf", "bolag": "Alfa"}]


def test_a_cut_answer_says_so(outside, folder, key):
    result = rpc(outside, folder, key, "tools/call", {"name": "kvarn_sql", "arguments": {
        "fraga": "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 500) SELECT i FROM n"}}
                 ).json()["result"]
    assert len(json.loads(result["content"][0]["text"])) == 200
    assert "200" in result["content"][1]["text"] and "COUNT" in result["content"][1]["text"]
    result = rpc(outside, folder, key, "tools/call", {"name": "kvarn_sql", "arguments": {
        "fraga": "SELECT count(*) FROM innehav"}}).json()["result"]
    assert len(result["content"]) == 1


def test_the_instruction_does_not_promise_quotes(outside, folder, key):
    result = rpc(outside, folder, key, "initialize", {}).json()["result"]
    assert "citat när det finns" in result["instructions"]
