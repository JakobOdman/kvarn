"""
db.py - folders, documents, extractions and templates in Postgres (Supabase), original files on disk.

DATABASE_URL            the database (schema in schema.sql). Default: the local one in data/postgres/
storage.py              the uploaded files, once per owner (Supabase Storage, or data/filer/ locally)
Cache                   the owner's cached AI answers (llm.py), in llm_cache

JSON (read results, extraction tables) goes into a JSONB column as it is.

    venv/bin/python -m api.db schema    # create the tables
"""
import atexit
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from api import limits, storage

LOCAL_DATABASE = "postgresql://postgres@localhost:5433/kvarn"  # started with pg_ctl, see context

_pool: ConnectionPool | None = None


def connect():
    """A connection from the pool, as a context manager: commits when the block ends, rolls back on an error.
    prepare_threshold=None because Supabase's pooler does not keep prepared statements between calls."""
    global _pool
    if _pool is None:
        url = os.environ.get("DATABASE_URL")
        if not url and os.environ.get("VERCEL"):
            raise RuntimeError("DATABASE_URL is not set in Vercel.")  # never the local database there
        _pool = ConnectionPool(url or LOCAL_DATABASE, min_size=1, max_size=5, open=True,
                               kwargs={"row_factory": dict_row, "prepare_threshold": None})
        atexit.register(close)
    return _pool.connection()


def close():
    """Close the pool, e.g. before pointing DATABASE_URL at another database."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def create_schema():
    with connect() as con:
        con.execute((Path(__file__).parent / "schema.sql").read_text())


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- Cache, per owner ---

class Cache:
    """The owner's saved AI answers, for llm.ask: get(key) and put(key, saved)."""

    def __init__(self, user_id: str):
        self.user_id = user_id

    def get(self, key: str) -> dict | None:
        with connect() as con:
            return con.execute("SELECT model, tokens_in, tokens_out, answer FROM llm_cache WHERE user_id = %s AND key = %s",
                               (self.user_id, key)).fetchone()

    def put(self, key: str, saved: dict):
        with connect() as con:
            con.execute("INSERT INTO llm_cache (user_id, key, model, tokens_in, tokens_out, answer, created) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        (self.user_id, key, saved["model"], saved["tokens_in"], saved["tokens_out"],
                         Jsonb(saved["answer"]), _now()))


class Meter:
    """The owner's AI spending this month, in the table usage: remaining() and add(usd, ...). See limits.py."""

    def __init__(self, user_id: str):
        self.user_id = user_id

    def spent(self) -> float:
        with connect() as con:
            row = con.execute("SELECT usd FROM usage WHERE user_id = %s AND month = %s",
                              (self.user_id, _month())).fetchone()
        return row["usd"] if row else 0.0

    def remaining(self) -> float:
        return limits.MONTHLY_USD - self.spent()

    def add(self, usd: float, tokens_in: int = 0, tokens_out: int = 0, model_pages: int = 0):
        with connect() as con:
            con.execute("""
                INSERT INTO usage (user_id, month, usd, tokens_in, tokens_out, model_pages)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, month) DO UPDATE SET usd = usage.usd + excluded.usd,
                    tokens_in = usage.tokens_in + excluded.tokens_in, tokens_out = usage.tokens_out + excluded.tokens_out,
                    model_pages = usage.model_pages + excluded.model_pages""",
                        (self.user_id, _month(), usd, tokens_in, tokens_out, model_pages))


def _month() -> str:
    return datetime.now().strftime("%Y-%m")


# --- Folders ---

def add_folder(name: str, user_id: str) -> dict:
    folder = {"id": uuid4().hex, "name": name, "created": _now(), "user_id": user_id}
    with connect() as con:
        con.execute("INSERT INTO folders (id, name, created, user_id) VALUES (%(id)s, %(name)s, %(created)s, %(user_id)s)",
                    folder)
    return folder


def rename_folder(folder_id: str, user_id: str, name: str) -> bool:
    with connect() as con:
        return con.execute("UPDATE folders SET name = %s WHERE id = %s AND user_id = %s",
                           (name, folder_id, user_id)).rowcount > 0


def get_folder(folder_id: str, user_id: str) -> dict | None:
    """The folder, or None if it doesn't exist or is someone else's."""
    with connect() as con:
        return con.execute("SELECT * FROM folders WHERE id = %s AND user_id = %s", (folder_id, user_id)).fetchone()


def list_folders(user_id: str) -> list[dict]:
    """The user's folders by name, with the number of documents in each."""
    with connect() as con:
        return con.execute("""
            SELECT f.id, f.name, f.created, count(d.id) AS document_count
            FROM folders f LEFT JOIN documents d ON d.folder_id = f.id
            WHERE f.user_id = %s
            GROUP BY f.id ORDER BY lower(f.name)""", (user_id,)).fetchall()


def delete_folder(folder_id: str, user_id: str) -> bool:
    """The folder and its documents. Extractions keep their rows."""
    with connect() as con:
        if con.execute("SELECT 1 FROM folders WHERE id = %s AND user_id = %s", (folder_id, user_id)).fetchone() is None:
            return False
        doc_ids = [r["id"] for r in con.execute("SELECT id FROM documents WHERE folder_id = %s", (folder_id,))]
    for doc_id in doc_ids:
        delete_document(doc_id)
    with connect() as con:
        con.execute("DELETE FROM folders WHERE id = %s", (folder_id,))
    return True


# --- Documents ---

def add_document(doc_id: str, name: str, sha256: str, options: dict, folder_id: str):
    """The file is already stored (storage.py)."""
    with connect() as con:
        con.execute("INSERT INTO documents (id, name, sha256, created, options, status, folder_id) "
                    "VALUES (%s, %s, %s, %s, %s, 'queued', %s)",
                    (doc_id, name, sha256, _now(), Jsonb(options), folder_id))


def update_document(doc_id: str, status: str, result: dict | None = None, error: str | None = None):
    with connect() as con:
        con.execute("UPDATE documents SET status = %s, result = %s, error = %s WHERE id = %s",
                    (status, Jsonb(result) if result is not None else None, error, doc_id))


def reset_document(doc_id: str, options: dict):
    """Read the document again with new options: back to queued, the old result gone."""
    with connect() as con:
        con.execute("UPDATE documents SET options = %s, status = 'queued', result = NULL, error = NULL, created = %s "
                    "WHERE id = %s", (Jsonb(options), _now(), doc_id))


def get_document(doc_id: str, user_id: str | None = None) -> dict | None:
    """The document, with its owner's user_id. With user_id: None also when its folder is someone else's."""
    with connect() as con:
        return con.execute("SELECT d.*, f.user_id FROM documents d JOIN folders f ON f.id = d.folder_id "
                           "WHERE d.id = %(doc)s AND (%(user)s::text IS NULL OR f.user_id = %(user)s)",
                           {"doc": doc_id, "user": user_id}).fetchone()


def delete_document(doc_id: str) -> bool:
    """Remove the document, and its file if the owner has no other document with the same one.
    False if it didn't exist."""
    with connect() as con:
        row = con.execute("SELECT d.sha256, f.user_id FROM documents d JOIN folders f ON f.id = d.folder_id "
                          "WHERE d.id = %s", (doc_id,)).fetchone()
        if row is None:
            return False
        con.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
        still_used = con.execute("SELECT 1 FROM documents d JOIN folders f ON f.id = d.folder_id "
                                 "WHERE d.sha256 = %s AND f.user_id = %s", (row["sha256"], row["user_id"])).fetchone()
    if not still_used:
        storage.delete(row["user_id"], row["sha256"])
    return True


def list_documents(user_id: str, folder_id: str | None = None) -> list[dict]:
    """The user's documents (or one folder's), newest first. Instead of the read result (it can be large),
    a summary counted in SQL."""
    with connect() as con:
        return con.execute("""
            SELECT d.id, d.name, d.sha256, d.created, d.options, d.status, d.error, d.folder_id,
                   d.result -> 'ok' AS ok,
                   d.result -> 'page_count' AS page_count,
                   jsonb_array_length(d.result -> 'pages') AS pages,
                   (SELECT count(*) FROM jsonb_array_elements(d.result -> 'pages') p
                     WHERE p ->> 'reader' = 'claude_vision') AS model_pages,
                   d.result -> 'partial' AS partial,
                   d.result -> 'skipped' AS skipped
            FROM documents d JOIN folders f ON f.id = d.folder_id
            WHERE f.user_id = %(user)s AND (%(folder)s::text IS NULL OR d.folder_id = %(folder)s)
            ORDER BY d.created DESC, d.seq DESC""", {"user": user_id, "folder": folder_id}).fetchall()


# --- Extractions ---

def add_extraction(extraction_id: str, template: dict, documents: list[dict], folder_id: str | None, user_id: str):
    """template is the whole template as it was at the run, so the result can always be traced to its prompt."""
    tables = {t["name"]: [] for t in template["tables"]}
    with connect() as con:
        con.execute("INSERT INTO extractions (id, template_id, template, created, status, documents, tables, folder_id, "
                    "user_id) VALUES (%s, %s, %s, %s, 'queued', %s, %s, %s, %s)",
                    (extraction_id, template["id"], Jsonb(template), _now(), Jsonb(documents), Jsonb(tables),
                     folder_id, user_id))


def update_extraction(extraction_id: str, status: str, documents: list[dict], tables: dict):
    with connect() as con:
        con.execute("UPDATE extractions SET status = %s, documents = %s, tables = %s WHERE id = %s",
                    (status, Jsonb(documents), Jsonb(tables), extraction_id))


def get_extraction(extraction_id: str, user_id: str | None = None) -> dict | None:
    """The extraction. With user_id: None also when it is someone else's."""
    with connect() as con:
        row = con.execute("SELECT * FROM extractions WHERE id = %(id)s AND (%(user)s::text IS NULL OR user_id = %(user)s)",
                          {"id": extraction_id, "user": user_id}).fetchone()
    if row:
        del row["seq"]
    return row


def start_extraction_document(extraction_id: str, job_id: str) -> dict | None:
    """Mark one document of the extraction as running and return the extraction. None if that document is
    already finished (the job came twice) or the extraction is gone. The row is locked meanwhile, since the
    extraction's other documents are updated by other jobs at the same time."""
    with connect() as con:
        extraction = con.execute("SELECT * FROM extractions WHERE id = %s FOR UPDATE", (extraction_id,)).fetchone()
        doc = next((d for d in extraction["documents"] if d["job_id"] == job_id), None) if extraction else None
        if doc is None or doc["status"] in ("done", "error"):
            return None
        doc["status"] = "running"
        con.execute("UPDATE extractions SET status = 'running', documents = %s WHERE id = %s",
                    (Jsonb(extraction["documents"]), extraction_id))
    return extraction


def finish_extraction_document(extraction_id: str, job_id: str, changes: dict, rows: dict[str, list[dict]]):
    """Store one document's result: its status (and tokens or error) and its rows, appended to the tables in the
    order of the documents. The extraction is done when every document is. Nothing happens if the document is
    already finished."""
    with connect() as con:
        extraction = con.execute("SELECT documents, tables FROM extractions WHERE id = %s FOR UPDATE",
                                 (extraction_id,)).fetchone()
        doc = next((d for d in extraction["documents"] if d["job_id"] == job_id), None) if extraction else None
        if doc is None or doc["status"] in ("done", "error"):
            return
        doc.update(changes)
        documents, tables = extraction["documents"], extraction["tables"]
        order = {d["name"]: i for i, d in reversed(list(enumerate(documents)))}
        for table, table_rows in rows.items():
            tables[table] = sorted(tables.get(table, []) + table_rows, key=lambda r: order.get(r.get("dokument"), 0))
        status = "done" if all(d["status"] in ("done", "error") for d in documents) else "running"
        con.execute("UPDATE extractions SET status = %s, documents = %s, tables = %s WHERE id = %s",
                    (status, Jsonb(documents), Jsonb(tables), extraction_id))


def list_extractions(user_id: str) -> list[dict]:
    """The user's extractions, newest first, without the rows: template name, documents and rows per table."""
    with connect() as con:
        rows = con.execute("""
            SELECT e.id, e.template_id, e.template ->> 'name' AS template_name, e.created, e.status,
                   e.documents, e.folder_id, f.name AS folder_name,
                   (SELECT jsonb_object_agg(key, jsonb_array_length(value)) FROM jsonb_each(e.tables)) AS row_counts
            FROM extractions e LEFT JOIN folders f ON f.id = e.folder_id
            WHERE e.user_id = %s
            ORDER BY e.created DESC, e.seq DESC""", (user_id,)).fetchall()
    return [{**r, "row_counts": r["row_counts"] or {}} for r in rows]


# --- Templates ---

def list_templates(user_id: str) -> list[dict]:
    """The user's templates by name, each as the template JSON."""
    with connect() as con:
        rows = con.execute("SELECT template FROM templates WHERE user_id = %s ORDER BY lower(name)", (user_id,))
        return [r["template"] for r in rows]


def get_template(template_id: str, user_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT template FROM templates WHERE id = %s AND user_id = %s",
                          (template_id, user_id)).fetchone()
        return row["template"] if row else None


def save_template(template_id: str, user_id: str, name: str, template: dict) -> bool:
    """Create or update. False if the id belongs to someone else."""
    now = _now()
    with connect() as con:
        return con.execute("""
            INSERT INTO templates (id, user_id, name, template, created, updated) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET name = excluded.name, template = excluded.template, updated = excluded.updated
            WHERE templates.user_id = excluded.user_id""",
            (template_id, user_id, name, Jsonb(template), now, now)).rowcount > 0


def delete_template(template_id: str, user_id: str) -> bool:
    with connect() as con:
        return con.execute("DELETE FROM templates WHERE id = %s AND user_id = %s", (template_id, user_id)).rowcount > 0


if __name__ == "__main__":
    if sys.argv[1:] == ["schema"]:
        create_schema()
        print("Tabellerna finns.")
    else:
        sys.exit("Användning: python -m api.db schema")
