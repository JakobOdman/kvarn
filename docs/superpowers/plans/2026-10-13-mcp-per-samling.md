# MCP-server per samling – implementationsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Varje samling kan slå på en MCP-server som låter Claude och Copilot Studio fråga samlingens live-extraktion med två verktyg.

**Architecture:** En ny fil `api/mcp.py` med MCP över tillståndslös Streamable HTTP (JSON-RPC i en POST, JSON ut) och verktygen `kvarn_schema` och `kvarn_sql`. Live-extraktionen läses in i en SQLite i minnet vid varje anrop. Endpointen ligger på den publika routern i `api/main.py` och använder samlingens befintliga API-nyckel. Brytaren `folders.mcp_enabled` sätts med samma PATCH som `auto_extract` och visas i fliken Integrera.

**Tech Stack:** Python 3.12, FastAPI, psycopg, sqlite3 (standardbiblioteket), pytest; React + TypeScript (Vite) i `frontend/`.

**Spec:** `docs/superpowers/specs/2026-10-13-mcp-per-samling-design.md`

## Global Constraints

- Inga nya Python-paket. MCP-protokollet skrivs för hand, inte med MCP-SDK:n.
- `api/mcp.py` får bara bero på `api.db` och `api.templates`, inget från Vercel, Supabase eller Azure (filen kopieras oförändrad till kvarn-enterprise).
- Adress: `POST /api/public/folders/{folder_id}/mcp`.
- Nyckel: `Authorization: Bearer kvarn_...`, samma kontroll som tabelladresserna. Fel nyckel: 401 `"Fel eller saknad API-nyckel."`.
- MCP avstängt: 404 `"MCP är inte påslaget för samlingen."`.
- Ingen live-extraktion: verktygsfel `"Samlingen har ingen aktuell tabell. Slå på Extrahera automatiskt i Kvarn."`.
- Kolumner i varje tabell: `samling`, `dokument`, mallens fält i mallens ordning, `sida`, `citat`.
- `kvarn_sql`: bara läsning, högst 200 rader.
- `folders.mcp_enabled BOOLEAN NOT NULL DEFAULT false`.
- Instruktion: `"Svara bara utifrån tabellerna. Ange alltid källa: dokument, sida och citat. Anropa kvarn_schema först."`
- Inga kundnamn i koden, testerna eller commit-meddelandena (repot ligger på GitHub).
- Kodstil som resten av repot: engelska kommentarer och docstrings, svenska texter mot användaren, inga onödiga abstraktioner.

## Review Focus

- Claude skickar SQL som försöker skriva eller nå disk (`ATTACH`, `PRAGMA`, `DELETE`) → verktygsfel, ingen fil skapas. Test i Task 2.
- En fråga som aldrig blir klar (rekursiv CTE utan slut, stor korsprodukt) → avbryts efter några sekunder med verktygsfel i stället för att låsa funktionen. Test i Task 2.
- Fältnamn med mellanslag, parenteser eller citattecken i mallen → tabellen skapas ändå och kolumnen går att fråga med `"..."`. Test i Task 2.
- Ett mallfält som heter `samling` eller `citat` (inte reserverade i mallarna) → ingen dubbelkolumn, frågan fungerar. Test i Task 2.
- Notifieringar (`notifications/initialized`) och okända protokollversioner från klienten → 202 respektive vår senaste version, inte ett fel. Test i Task 2.

---

## Filer

- Modify: `api/schema.sql` – kolumnen `mcp_enabled`
- Modify: `api/db.py` – `update_folder`, `list_folders`, `get_live_extraction`, ny `public_folder`
- Modify: `api/main.py` – `FolderChanges.mcp_enabled`, nyckelkontrollen bryts ut till `check_key`, MCP-endpointen
- Create: `api/mcp.py` – protokollet och verktygen
- Create: `tests/test_mcp.py`
- Modify: `frontend/src/api.ts` – `Folder.mcp_enabled`, `updateFolder`
- Modify: `frontend/src/components/ApiKey.tsx` – exportera `Copy`
- Create: `frontend/src/components/McpServer.tsx` – brytaren, adressen och instruktionen
- Modify: `frontend/src/components/IntegrateView.tsx` – visa `McpServer`

---

### Task 1: Brytaren `mcp_enabled`

**Files:**
- Modify: `api/schema.sql` (efter raden `ALTER TABLE folders ADD COLUMN IF NOT EXISTS api_key_created TEXT;`)
- Modify: `api/db.py:123-129` (`update_folder`), `api/db.py:154-157` (`get_live_extraction`), `list_folders`
- Modify: `api/main.py:56-60` (`FolderChanges`)
- Test: `tests/test_mcp.py`

**Interfaces:**
- Produces: `folders.mcp_enabled` i `GET /api/folders` och `PATCH /api/folders/{id}` (`{"mcp_enabled": bool}`); `db.public_folder(folder_id: str) -> dict | None` med nycklarna `name`, `mcp_enabled`; `db.get_live_extraction` returnerar även `documents`.

- [ ] **Step 1: Skriv de fallerande testerna**

Skapa `tests/test_mcp.py`:

```python
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
```

- [ ] **Step 2: Kör testerna och se dem fallera**

Run: `venv/bin/pytest tests/test_mcp.py -v`
Expected: FAIL med `KeyError: 'mcp_enabled'`

- [ ] **Step 3: Kolumnen i schemat**

I `api/schema.sql`, direkt efter `ALTER TABLE folders ADD COLUMN IF NOT EXISTS api_key_created TEXT;`:

```sql
-- Whether the folder's MCP server answers (api/mcp.py). Off until the owner turns it on.
ALTER TABLE folders ADD COLUMN IF NOT EXISTS mcp_enabled BOOLEAN NOT NULL DEFAULT false;
```

Kör mot den lokala databasen: `venv/bin/python -m api.db schema`

- [ ] **Step 4: db.py**

`update_folder`: lägg till `mcp_enabled` bland de tillåtna nycklarna och i docstringen:

```python
def update_folder(folder_id: str, user_id: str, changes: dict) -> bool:
    """changes: any of name, template_id, auto_extract, mcp_enabled."""
    changes = {k: v for k, v in changes.items() if k in ("name", "template_id", "auto_extract", "mcp_enabled")}
```

`list_folders`: lägg till `f.mcp_enabled` i SELECT-listan:

```python
            SELECT f.id, f.name, f.created, f.template_id, f.auto_extract, f.mcp_enabled, f.api_key_created,
```

`get_live_extraction`: hämta även `documents` (namnen till `kvarn_schema`):

```python
def get_live_extraction(folder_id: str) -> dict | None:
    with connect() as con:
        return con.execute("SELECT template, tables, documents FROM extractions WHERE folder_id = %s AND live",
                           (folder_id,)).fetchone()
```

Ny funktion direkt efter `folder_api_key_hash`:

```python
def public_folder(folder_id: str) -> dict | None:
    """What the MCP server needs to know about a folder: {"name", "mcp_enabled"}. For the key's holder, not a user."""
    with connect() as con:
        return con.execute("SELECT name, mcp_enabled FROM folders WHERE id = %s", (folder_id,)).fetchone()
```

- [ ] **Step 5: main.py**

```python
class FolderChanges(BaseModel):
    """Only what is sent is changed. template_id null: no template."""
    name: str | None = None
    template_id: str | None = None
    auto_extract: bool | None = None
    mcp_enabled: bool | None = None
```

- [ ] **Step 6: Kör testerna**

Run: `venv/bin/pytest -q`
Expected: alla gröna (106 tidigare + 2 nya)

- [ ] **Step 7: Commit**

```bash
git add api/schema.sql api/db.py api/main.py tests/test_mcp.py
git commit -m "MCP: brytare per samling, av som standard"
```

---

### Task 2: MCP-servern

**Files:**
- Create: `api/mcp.py`
- Modify: `api/main.py:426-437` (`live_tables` → `check_key` + `live_tables`), ny endpoint före `app.include_router(public, ...)`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `db.public_folder`, `db.get_live_extraction` (med `documents`), `db.folder_api_key_hash`, `Template` från `api.templates`.
- Produces: `mcp.handle(body: bytes, folder: dict, live: Callable[[], dict | None]) -> Response`; `mcp.VERSIONS: list[str]`; `mcp.SECONDS: float`; `check_key(folder_id: str, request: Request) -> None` i `api/main.py`.

- [ ] **Step 1: Skriv de fallerande testerna**

Lägg till i `tests/test_mcp.py` (importerna överst i filen ersätter de från Task 1):

```python
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
```

- [ ] **Step 2: Kör testerna och se dem fallera**

Run: `venv/bin/pytest tests/test_mcp.py -v`
Expected: FAIL med `ImportError: cannot import name 'mcp' from 'api'`

- [ ] **Step 3: Skriv `api/mcp.py`**

```python
"""
A folder's MCP server: Claude, Copilot Studio and others ask questions about the folder's live extraction.

Streamable HTTP without sessions: one POST with a JSON-RPC message in, JSON out, no SSE. The rows are loaded into
an in-memory SQLite on every call, so the questions never reach Postgres or another folder. The same file in Kvarn
and Kvarn Enterprise: it only needs db.py and the templates.
"""
import json
import sqlite3
import time
from typing import Callable

from fastapi.responses import JSONResponse, Response

from api.templates import Template

VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]  # newest first; a client asking for another gets the first
MAX_ROWS = 200
SECONDS = 5  # a question that takes longer is stopped
INSTRUCTIONS = ("Svara bara utifrån tabellerna. Ange alltid källa: dokument, sida och citat. "
                "Anropa kvarn_schema först.")
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
TOOLS = [
    {"name": "kvarn_schema",
     "description": "Samlingens tabeller: kolumner med beskrivning, antal rader, dokumenten och vilka värden som "
                    "finns i valfälten. Anropa först.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": READ_ONLY},
    {"name": "kvarn_sql",
     "description": "Kör en SELECT (SQLite) mot tabellerna och returnerar högst 200 rader. Kolumnnamn med mellanslag "
                    "skrivs inom citattecken. Exempel: SELECT dokument, sida, citat FROM krav WHERE kravtyp = 'skall'",
     "inputSchema": {"type": "object", "properties": {"fraga": {"type": "string", "description": "En SELECT"}},
                     "required": ["fraga"]},
     "annotations": READ_ONLY},
]
ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


class ToolError(Exception):
    """Given to the model as the tool's answer, with isError, so it can tell the user."""


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def handle(body: bytes, folder: dict, live: Callable[[], dict | None]) -> Response:
    """One JSON-RPC message from the client. folder: {"name", ...}; live() gives the folder's live extraction."""
    try:
        message = json.loads(body)
    except ValueError:
        return JSONResponse(error(None, -32700, "Ogiltig JSON."))
    if not isinstance(message, dict):
        return JSONResponse(error(None, -32600, "Ett JSON-RPC-meddelande i taget."))
    if "id" not in message or "method" not in message:
        return Response(status_code=202)  # a notification, or an answer to a request we never send
    try:
        result = answer(message["method"], message.get("params") or {}, folder, live)
    except RpcError as e:
        return JSONResponse(error(message["id"], e.code, str(e)))
    return JSONResponse({"jsonrpc": "2.0", "id": message["id"], "result": result})


def error(id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


def answer(method: str, params: dict, folder: dict, live) -> dict:
    if method == "initialize":
        version = params.get("protocolVersion")
        return {"protocolVersion": version if version in VERSIONS else VERSIONS[0],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": folder["name"], "version": "1"},
                "instructions": INSTRUCTIONS}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        return call(params.get("name"), params.get("arguments") or {}, folder, live)
    raise RpcError(-32601, f"Okänd metod: {method}")


def call(name: str, arguments: dict, folder: dict, live) -> dict:
    if name not in ("kvarn_schema", "kvarn_sql"):
        raise RpcError(-32602, f"Okänt verktyg: {name}")
    try:
        extraction = live()
        if extraction is None:
            raise ToolError("Samlingen har ingen aktuell tabell. Slå på Extrahera automatiskt i Kvarn.")
        template = Template.model_validate(extraction["template"])
        con = load(folder["name"], template, extraction["tables"])
        if name == "kvarn_schema":
            result = schema(folder["name"], template, con, [d["name"] for d in extraction["documents"]])
        else:
            result = select(con, arguments.get("fraga") or "")
    except ToolError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}]}


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def columns(table) -> list[str]:
    """samling, dokument, the template's fields, sida, citat. A field with the same name as a fixed one is not
    repeated."""
    return list(dict.fromkeys(["samling", "dokument", *(f.name for f in table.fields), "sida", "citat"]))


def value(v):
    if v == "":
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def load(folder_name: str, template: Template, tables: dict) -> sqlite3.Connection:
    """The live extraction's rows in an in-memory SQLite that only reads from here on."""
    con = sqlite3.connect(":memory:")
    for table in template.tables:
        names = columns(table)
        con.execute(f"CREATE TABLE {quote(table.name)} ({', '.join(map(quote, names))})")
        rows = [[folder_name if c == "samling" else value(row.get(c)) for c in names]
                for row in tables.get(table.name, [])]
        con.executemany(f"INSERT INTO {quote(table.name)} VALUES ({', '.join('?' * len(names))})", rows)
    con.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in ALLOWED else sqlite3.SQLITE_DENY)
    return con


def schema(folder_name: str, template: Template, con: sqlite3.Connection, documents: list[str]) -> dict:
    fixed = {"samling": "Samlingens namn", "dokument": "Filnamnet", "sida": "Sidan i dokumentet",
             "citat": "Ordagrant ur dokumentet"}
    tables = {}
    for table in template.tables:
        descriptions = fixed | {f.name: f.description for f in table.fields}
        t = quote(table.name)
        tables[table.name] = {"beskrivning": table.description,
                              "rader": con.execute(f"SELECT count(*) FROM {t}").fetchone()[0],
                              "kolumner": {c: descriptions[c] for c in columns(table)}}
        for f in table.fields:
            if f.choices:
                found = con.execute(f"SELECT DISTINCT {quote(f.name)} FROM {t} WHERE {quote(f.name)} IS NOT NULL")
                tables[table.name][f"värden i {f.name}"] = [r[0] for r in found]
    return {"samling": folder_name, "mall": template.name, "dokument": documents, "tabeller": tables}


def select(con: sqlite3.Connection, query: str) -> list[dict]:
    if not query.strip():
        raise ToolError("Ange en SELECT i fraga.")
    deadline = time.monotonic() + SECONDS
    con.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
    try:
        cursor = con.execute(query)
        rows = cursor.fetchmany(MAX_ROWS)
    except sqlite3.OperationalError as e:
        if str(e) == "interrupted":
            raise ToolError(f"Frågan tog för lång tid (över {SECONDS} s). Begränsa den, t.ex. med WHERE eller LIMIT.")
        raise ToolError(f"{e}. Kontrollera tabell- och kolumnnamn med kvarn_schema. Bara SELECT är tillåtet.")
    except sqlite3.Error as e:
        raise ToolError(f"{e}. Kontrollera tabell- och kolumnnamn med kvarn_schema. Bara SELECT är tillåtet.")
    names = [d[0] for d in cursor.description or []]
    return [dict(zip(names, r)) for r in rows]
```

Obs: `sqlite3.SQLITE_RECURSIVE` finns från Python 3.11. Om `"SELECT 1; DELETE FROM innehav"` ger `sqlite3.ProgrammingError` ("You can only execute one statement at a time") fångas den av `except sqlite3.Error`.

- [ ] **Step 4: Nyckelkontrollen och endpointen i `api/main.py`**

Importera `mcp` tillsammans med de andra: `from api import db, jobs, limits, llm, mcp, storage`.

Bryt ut nyckelkontrollen ur `live_tables` (beteendet för tabelladresserna är oförändrat):

```python
def check_key(folder_id: str, request: Request):
    """401 unless the request has the folder's key in "Authorization: Bearer kvarn_...". A wrong key and an unknown
    folder look the same."""
    scheme, _, key = request.headers.get("authorization", "").partition(" ")
    stored = db.folder_api_key_hash(folder_id)
    given = hashlib.sha256(key.encode()).hexdigest()
    if scheme.lower() != "bearer" or not stored or not hmac.compare_digest(stored, given):
        raise HTTPException(401, "Fel eller saknad API-nyckel.")


def live_tables(folder_id: str, request: Request) -> dict:
    """The folder's live extraction, if the request has the folder's key."""
    check_key(folder_id, request)
    extraction = db.get_live_extraction(folder_id)
    if extraction is None:
        raise HTTPException(404, "Samlingen har ingen aktuell tabell. Slå på Extrahera automatiskt i Kvarn.")
    return extraction
```

Efter `public_table`, före `app.include_router(public, prefix="/api/public")`:

```python
@public.post("/folders/{folder_id}/mcp")
async def mcp_server(folder_id: str, request: Request):
    """The folder's MCP server (api/mcp.py), with the folder's key, when MCP is turned on for the folder."""
    check_key(folder_id, request)
    folder = db.public_folder(folder_id)
    if not folder["mcp_enabled"]:
        raise HTTPException(404, "MCP är inte påslaget för samlingen.")
    return mcp.handle(await request.body(), folder, lambda: db.get_live_extraction(folder_id))


@public.get("/folders/{folder_id}/mcp")
async def mcp_stream(folder_id: str):
    """No server-sent events: everything is answered in the POST."""
    return Response(status_code=405, headers={"Allow": "POST"})
```

- [ ] **Step 5: Kör testerna**

Run: `venv/bin/pytest -q`
Expected: alla gröna. Fallerar `test_sql_only_reads` på `PRAGMA`: kontrollera att `set_authorizer` sätts efter att tabellerna är skapade (i `load`, efter loopen).

- [ ] **Step 6: Commit**

```bash
git add api/mcp.py api/main.py tests/test_mcp.py
git commit -m "MCP-server per samling: kvarn_schema och kvarn_sql mot live-extraktionen"
```

---

### Task 3: Fliken Integrera

**Files:**
- Modify: `frontend/src/api.ts:335-367` (`Folder`, `updateFolder`)
- Modify: `frontend/src/components/ApiKey.tsx` (`function Copy` → `export function Copy`)
- Create: `frontend/src/components/McpServer.tsx`
- Modify: `frontend/src/components/IntegrateView.tsx`

**Interfaces:**
- Consumes: `PATCH /api/folders/{id}` med `{"mcp_enabled": bool}` (Task 1), adressen `/api/public/folders/{id}/mcp` (Task 2), `Toggle` från `./Toggle`.
- Produces: `McpServer({ folder, onFolderChanged })`.

- [ ] **Step 1: api.ts**

I `interface Folder`, efter `api_key_created`:

```ts
  mcp_enabled: boolean // Claude and Copilot Studio can ask about the live extraction with the folder's key
```

`updateFolder`:

```ts
export const updateFolder = (
  id: string,
  changes: { template_id?: string | null; auto_extract?: boolean; mcp_enabled?: boolean },
): Promise<Folder> => sendJson(`/folders/${id}`, 'PATCH', changes)
```

- [ ] **Step 2: Exportera `Copy` i `ApiKey.tsx`**

```tsx
export function Copy({ value }: { value: string }) {
```

- [ ] **Step 3: `McpServer.tsx`**

```tsx
import { updateFolder, type Folder } from '../api'
import { Copy } from './ApiKey'
import { Toggle } from './Toggle'

/** The folder's MCP server: Claude and Copilot Studio ask questions about the live extraction with the folder's key. */
export function McpServer({ folder, onFolderChanged }: { folder: Folder; onFolderChanged: (folder: Folder) => void }) {
  async function change(on: boolean) {
    onFolderChanged(await updateFolder(folder.id, { mcp_enabled: on }))
  }

  return (
    <div className="api-key">
      <Toggle
        label="MCP-server"
        description="Claude och Copilot Studio ställer frågor om samlingens aktuella tabell, med samlingens API-nyckel."
        checked={folder.mcp_enabled}
        onChange={change}
      />
      {folder.mcp_enabled && (
        <>
          <span className="caps">Adress</span>
          <Copy value={`${location.origin}/api/public/folders/${folder.id}/mcp`} />
          {!folder.api_key_created && <p className="queue-meta">Skapa en API-nyckel ovan för att ansluta.</p>}
          <p className="queue-meta">
            <strong>Claude:</strong> Inställningar → Connectors → Lägg till anpassad connector. Ange adressen och,
            under Request headers, <code>Authorization</code> med värdet <code>Bearer &lt;nyckel&gt;</code>.
          </p>
          <p className="queue-meta">
            <strong>Copilot Studio:</strong> Verktyg → Lägg till verktyg → Model Context Protocol. Ange adressen, välj
            API-nyckel som header med namnet <code>Authorization</code> och värdet <code>Bearer &lt;nyckel&gt;</code>.
          </p>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Visa den i `IntegrateView.tsx`**

Importera `import { McpServer } from './McpServer'` och lägg den direkt efter `<ApiKey ... />` inuti samma gren (`folder.auto_extract ? (...)`), så att grenen blir ett fragment:

```tsx
          {folder.auto_extract ? (
            <>
              <ApiKey
                key={folder.id}
                folder={folder}
                template={templates.find((t) => t.id === folder.template_id)}
                onFolderChanged={changed}
              />
              <McpServer folder={folder} onFolderChanged={changed} />
            </>
          ) : (
```

Och i statusraden i listan:

```tsx
const status = (f: Folder) =>
  !f.auto_extract
    ? 'Ingen aktuell tabell'
    : (f.api_key_created ? 'API-nyckel finns' : 'Ingen API-nyckel') + (f.mcp_enabled ? ' · MCP på' : '')
```

- [ ] **Step 5: Bygg och lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: inga fel

- [ ] **Step 6: Titta i appen**

Vite (`npm run dev`) laddar om själv. Öppna `http://localhost:5173/app/` → Integrera → en samling med Extrahera automatiskt på. Slå på MCP-server, kontrollera att adressen och instruktionerna visas, ladda om sidan och se att brytaren är kvar.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "Integrera: brytare för samlingens MCP-server, med adress och instruktion"
```

---

### Task 4: Kontroll mot localhost

Ingen kod. Görs tillsammans med Jakob.

- [ ] **Step 1:** Jakob slår på Extrahera automatiskt för en samling (kör om dokumenten i en ny live-extraktion; det mesta bör komma från cachen) och MCP-server, och skapar en API-nyckel.
- [ ] **Step 2:** Anrop med curl mot `http://localhost:5173/api/public/folders/<id>/mcp`: `initialize`, `tools/list`, `tools/call` med `kvarn_schema`. Förväntat: samlingens tabeller och rader.
- [ ] **Step 3:** Koppla in i Claude Code: `claude mcp add --transport http kvarn-test http://localhost:5173/api/public/folders/<id>/mcp --header "Authorization: Bearer <nyckel>"`, ställ en fråga och kontrollera att svaret har dokument, sida och citat.
- [ ] **Step 4:** Uppdatera `read-document-context.md` (lokalt, ej i git) med beslutet och nyckelfilerna.

---

### Task 5: Kvarn Enterprise (efter Jakobs godkännande av Task 4)

**Files (i `../kvarn-enterprise`):** `api/mcp.py` (kopia), `tests/test_mcp.py` (kopia), samma ändringar som Task 1–3 i `api/schema.sql`, `api/db.py`, `api/main.py` och frontenden.

- [ ] **Step 1:** Jämför `api/db.py`, `api/main.py` (publika routern) och `frontend/src/components/IntegrateView.tsx` mellan repona med `diff` och notera skillnader innan något ändras.
- [ ] **Step 2:** Kopiera `api/mcp.py` och `tests/test_mcp.py` oförändrade och gör Task 1–3:s ändringar för hand.
- [ ] **Step 3:** `venv/bin/pytest -q` i kvarn-enterprise. Förväntat: gröna.
- [ ] **Step 4:** Lägg till ett avsnitt om MCP i `infra/azure/installation-lathund.html`: Copilot Studio först, Claude som medvetet val (datan går då via Anthropic).
- [ ] **Step 5:** Commit i kvarn-enterprise: `MCP-server per samling (samma api/mcp.py som Kvarn)`.

Inte i den här planen: köra schemat mot Supabase och pusha `main` (driftsättning, Jakobs beslut).
