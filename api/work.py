"""
work.py - the background work, one document per job: reading it (step 1) or extracting it (step 2).

Started through jobs.py: Vercel Queues in production, a thread locally. A job may arrive more than once
(Queues delivers at least once), so a document that is already done is skipped.
"""
from dataclasses import asdict

from api import db, limits, llm, storage
from api.extract import extract_document
from api.templates import Template, load_template
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
    # AI reading only in paid mode, and only as many pages as the limit and the month's budget allow
    meter = db.Meter(doc["user_id"])
    allow_model = opts["allow_model"] and llm.paid_allowed()
    max_pages = None
    if allow_model:
        max_pages = min(opts["max_model_pages"] or limits.MAX_MODEL_PAGES, limits.MAX_MODEL_PAGES,
                        int(meter.remaining() // limits.PAGE_USD))
        allow_model = max_pages > 0
    try:
        out = read_document(storage.read(doc["user_id"], doc["sha256"]), doc["name"], allow_model=allow_model,
                            max_model_pages=max_pages if allow_model else None, model=opts["model"])
        result = asdict(out)
        if not opts["words"]:
            for p in result["pages"]:
                p.pop("words", None)
        model_pages = sum(p["reader"] == "claude_vision" for p in result["pages"])
        if model_pages:
            meter.add(model_pages * limits.PAGE_USD, model_pages=model_pages)
        db.update_document(job_id, "done", result=result)
    except Exception as e:  # noqa: BLE001 - one bad file must not take the server down
        db.update_document(job_id, "error", error=str(e))
        return
    if result["ok"]:
        extract_automatically(doc)


def extract_automatically(doc: dict):
    """A read document in a folder with automatic extraction goes into the folder's live extraction, paid."""
    from api import jobs  # jobs imports this module
    folder = db.get_folder(doc["folder_id"], doc["user_id"])
    if not folder["auto_extract"] or not folder["template_id"]:
        return
    template = load_template(folder["template_id"], doc["user_id"])
    if template is None:
        return  # the template is gone
    extraction_id = db.add_to_live_extraction(folder, doc["id"], doc["name"], template.model_dump())
    if extraction_id:
        jobs.enqueue_from_job("extract", {"extraction_id": extraction_id, "job_id": doc["id"], "paid": True})


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
                                       db.Meter(extraction["user_id"]), client=client, paid=payload["paid"])
        changes = usage | {"status": "done"}
    except llm.NotCached:
        changes = {"status": "error", "error": "Inget sparat svar. Kör betalt för att skicka till AI:n."}
    except Exception as e:  # noqa: BLE001 - one bad document must not stop the others
        changes = {"status": "error", "error": str(e)}
    db.finish_extraction_document(extraction_id, job_id, changes, rows)


HANDLERS = {"read": read_job, "extract": extract_job}
