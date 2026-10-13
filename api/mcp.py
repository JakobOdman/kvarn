"""
A folder's MCP server: Claude, Copilot Studio and others ask questions about the folder's live extraction.

Streamable HTTP without sessions: one POST with a JSON-RPC message in, JSON out, no SSE. The rows are loaded into
an in-memory SQLite on every call, so the questions never reach Postgres or another folder. The same file in Kvarn
and Kvarn Enterprise: it only needs the templates.
"""
import hashlib
import json
import sqlite3
import time
from typing import Callable

from fastapi.responses import JSONResponse, Response

from api.templates import Template

VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]  # newest first; a client asking for another gets the first
MAX_ROWS = 200
MAX_CHARS = 1_000_000  # the most an answer may hold, and the longest value SQLite may make
SECONDS = 5  # a question that takes longer is stopped
INSTRUCTIONS = ("Svara bara utifrån tabellerna. Ange alltid källa: dokument och sida, och citat när det finns. "
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
                "instructions": INSTRUCTIONS + (f"\n\n{folder['mcp_description']}"
                                                if folder.get("mcp_description") else "")}
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
            if folder.get("mcp_description"):
                result = {"beskrivning": folder["mcp_description"]} | result
            cut = False
        else:
            result, cut = select(con, arguments.get("fraga") or "")
    except ToolError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    content = [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}]
    if cut:
        content.append({"type": "text", "text": f"Svaret är avkortat till {MAX_ROWS} rader. Räkna med COUNT eller "
                                                "begränsa med WHERE i stället för att räkna raderna."})
    return {"content": content}


def quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def tables(template: Template) -> list:
    """The template's tables, without one whose name is taken: SQLite ignores case in names."""
    found = {}
    for table in template.tables:
        found.setdefault(table.name.casefold(), table)
    return list(found.values())


def columns(table) -> list[str]:
    """samling, dokument, the template's fields, sida, citat. A field whose name is taken, also in another case,
    is left out."""
    found = {}
    for name in ["samling", "dokument", *(f.name for f in table.fields), "sida", "citat"]:
        found.setdefault(name.casefold(), name)
    return list(found.values())


def value(v):
    if v == "":
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def load(folder_name: str, template: Template, rows: dict) -> sqlite3.Connection:
    """The live extraction's rows in an in-memory SQLite that only reads from here on."""
    con = sqlite3.connect(":memory:")
    con.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_CHARS)
    for table in tables(template):
        names = columns(table)
        con.execute(f"CREATE TABLE {quote(table.name)} ({', '.join(map(quote, names))})")
        values = [[folder_name if c == "samling" else value(row.get(c)) for c in names]
                for row in rows.get(table.name, [])]
        con.executemany(f"INSERT INTO {quote(table.name)} VALUES ({', '.join('?' * len(names))})", values)
    con.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in ALLOWED else sqlite3.SQLITE_DENY)
    return con


def schema(folder_name: str, template: Template, con: sqlite3.Connection, documents: list[str]) -> dict:
    fixed = {"samling": "Samlingens namn", "dokument": "Filnamnet", "sida": "Sidan i dokumentet",
             "citat": "Ordagrant ur dokumentet, när det finns"}
    found = {}
    for table in tables(template):
        descriptions = fixed | {f.name: f.description for f in table.fields}
        t = quote(table.name)
        found[table.name] = {"beskrivning": table.description,
                              "rader": con.execute(f"SELECT count(*) FROM {t}").fetchone()[0],
                              "kolumner": {c: descriptions[c] for c in columns(table)}}
        for f in table.fields:
            if f.choices and f.name in found[table.name]["kolumner"]:
                distinct = con.execute(f"SELECT DISTINCT {quote(f.name)} FROM {t} WHERE {quote(f.name)} IS NOT NULL")
                found[table.name][f"värden i {f.name}"] = [r[0] for r in distinct]
    return {"samling": folder_name, "mall": template.name, "dokument": documents, "tabeller": found}


def select(con: sqlite3.Connection, query: str) -> tuple[list[dict], bool]:
    """The rows, at most MAX_ROWS, and whether there were more."""
    if not query.strip():
        raise ToolError("Ange en SELECT i fraga.")
    deadline = time.monotonic() + SECONDS
    con.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)
    rows, size, cut = [], 0, False
    try:
        cursor = con.execute(query)
        for row in cursor:
            if len(rows) == MAX_ROWS:
                cut = True
                break
            size += sum(len(str(v)) for v in row)
            if size > MAX_CHARS:
                raise ToolError(f"Svaret är för stort (över {MAX_CHARS:,} tecken). Välj färre kolumner eller rader."
                                .replace(",", " "))
            rows.append(row)
    except sqlite3.OperationalError as e:
        if str(e) == "interrupted":
            raise ToolError(f"Frågan tog för lång tid (över {SECONDS} s). Begränsa den, t.ex. med WHERE eller LIMIT.")
        raise ToolError(f"{e}. Kontrollera tabell- och kolumnnamn med kvarn_schema. Bara SELECT är tillåtet.")
    except sqlite3.Error as e:
        raise ToolError(f"{e}. Kontrollera tabell- och kolumnnamn med kvarn_schema. Bara SELECT är tillåtet.")
    names = [d[0] for d in cursor.description or []]
    return [dict(zip(names, r)) for r in rows], cut


# --- The folder's description, written by the AI once and kept on the folder ---

DESCRIPTION_SCHEMA = {"type": "object", "properties": {"beskrivning": {"type": "string"}},
                      "required": ["beskrivning"], "additionalProperties": False}
EXAMPLE_ROWS = 5
EXAMPLE_CHARS = 200


def basis(template: Template, documents: list[str]) -> str:
    """sha256 of what a description is written from: the template's prompt and tables, and the read documents."""
    content = {"prompt": template.prompt, "tables": [t.model_dump() for t in template.tables],
               "documents": sorted(documents)}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def description_prompt(folder_name: str, template: Template, extraction: dict) -> str:
    """The prompt for the AI that writes the description: the template and a few rows of every table."""
    lines = [
        "Du skriver en kort beskrivning för en AI-assistent som ska svara på frågor om en samling dokument genom att "
        "fråga tabeller med SQL. Tabellerna har tagits fram ur dokumenten med instruktionen och mallen nedan.",
        "",
        "Skriv på svenska, högst 250 ord, i löpande text eller korta punkter, utan rubriker. Ta med: vad samlingen "
        "handlar om (utifrån datan), vad varje tabell innehåller, hur tabellerna hänger ihop, och fallgropar, t.ex. "
        "hur valfälten ska tolkas och vad som aldrig finns i datan. Ta bara med det som instruktionen eller datan "
        "stöder.",
        "",
        f"## Samlingen: {folder_name}",
        "Dokument: " + ", ".join(d["name"] for d in extraction["documents"]),
        "",
        "## Instruktionen som användes när dokumenten lästes",
        template.prompt,
        "",
        "## Tabellerna",
    ]
    for table in template.tables:
        rows = extraction["tables"].get(table.name, [])
        lines.append(f"### {table.name} ({len(rows)} rader){': ' + table.description if table.description else ''}")
        for f in table.fields:
            choices = f" (val: {', '.join(f.choices)})" if f.choices else ""
            lines.append(f"- {f.name}{choices}{': ' + f.description if f.description else ''}")
        for row in rows[:EXAMPLE_ROWS]:
            example = {k: str(v)[:EXAMPLE_CHARS] for k, v in row.items() if v not in (None, "")}
            lines.append("  Exempel: " + json.dumps(example, ensure_ascii=False))
    return "\n".join(lines)
