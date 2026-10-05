"""
work.py - the background work, one document per job: reading it (step 1) or extracting it (step 2).

Started through jobs.py: Vercel Queues in production, a thread locally. A job may arrive more than once
(Queues delivers at least once), so a document that is already done is skipped.
"""
from dataclasses import asdict

from api import db, llm, storage
from api.extract import extract_document
from api.templates import Template
from read_document import read_document

MAX_ATTEMPTS = 3  # after this many deliveries a document gets an error instead of being tried again
FINISHED = ("done", "error")


def read_job(payload: dict, attempt: int = 1):
    """Read one document and store the result. payload = {"job_id"}."""
    job_id = payload["job_id"]
    doc = db.get_document(job_id)
    if doc is None or doc["status"] in FINISHED:
        return
    if attempt > MAX_ATTEMPTS:
        db.update_document(job_id, "error", error="Läsningen tog för lång tid.")
        return
    opts = doc["options"]
    db.update_document(job_id, "running")
    try:
        out = read_document(storage.read(doc["user_id"], doc["sha256"]), doc["name"], allow_model=opts["allow_model"],
                            max_model_pages=opts["max_model_pages"], model=opts["model"])
        result = asdict(out)
        if not opts["words"]:
            for p in result["pages"]:
                p.pop("words", None)
        db.update_document(job_id, "done", result=result)
    except Exception as e:  # noqa: BLE001 - one bad file must not take the server down
        db.update_document(job_id, "error", error=str(e))


def extract_job(payload: dict, attempt: int = 1):
    """Extract one document of an extraction. payload = {"extraction_id", "job_id", "paid"}.
    The other documents of the same extraction run in their own jobs, at the same time."""
    extraction_id, job_id = payload["extraction_id"], payload["job_id"]
    if attempt > MAX_ATTEMPTS:
        db.finish_extraction_document(extraction_id, job_id, {"status": "error", "error": "Tog för lång tid."}, {})
        return
    extraction = db.start_extraction_document(extraction_id, job_id)
    if extraction is None:
        return  # done already, or gone
    template = Template.model_validate(extraction["template"])
    # Without READ_DOCUMENT_PAID=1 the server is in development mode: cached answers or the fake client
    client = llm.AzureClient() if llm.paid_allowed() else llm.FakeClient()
    job = db.get_document(job_id)
    rows = {}
    try:
        if job is None or job["status"] != "done":
            raise ValueError("Dokumentet är inte läst.")
        rows, usage = extract_document(job["name"], job["result"], template, db.Cache(extraction["user_id"]),
                                       client=client, paid=payload["paid"])
        changes = usage | {"status": "done"}
    except llm.NotCached:
        changes = {"status": "error", "error": "Inget sparat svar. Kör betalt för att skicka till AI:n."}
    except Exception as e:  # noqa: BLE001 - one bad document must not stop the others
        changes = {"status": "error", "error": str(e)}
    db.finish_extraction_document(extraction_id, job_id, changes, rows)


HANDLERS = {"read": read_job, "extract": extract_job}
