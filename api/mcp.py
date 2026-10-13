"""
A folder's MCP server: Claude, Copilot Studio and others ask questions about the folder's live extraction.

Streamable HTTP without sessions: one POST with a JSON-RPC message in, JSON out, no SSE. The rows are loaded into
an in-memory SQLite on every call, so the questions never reach Postgres or another folder. The same file in Kvarn
and Kvarn Enterprise: it only needs the templates.
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
