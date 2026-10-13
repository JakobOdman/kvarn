"""A folder's MCP server: Claude and Copilot Studio ask questions about the folder's live extraction with the
folder's key, and only when MCP is turned on for the folder."""
from tests.test_live import folder, reading, upload  # noqa: F401 - fixtures


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
