"""
main.py - FastAPI backend for read_document.py.

Run:
  uvicorn api.main:app --reload     # everything under /api, docs at http://localhost:8000/api/docs
"""
import hashlib
import mimetypes
import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from openpyxl import Workbook
from pydantic import BaseModel, Field

from api import db, jobs, limits, llm, storage
from api.auth import user_from_token
from api.checks import run_checks
from api.layout import layout_text
from api.templates import Template, delete_template, list_templates, load_template, save_template
from read_document import DEFAULT_MODEL

app = FastAPI(title="Kvarn", docs_url="/api/docs", openapi_url="/api/openapi.json")


def current_user(request: Request) -> dict:
    """The logged-in user, from the Supabase token in "Authorization: Bearer ...". 401 when not logged in."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    user = user_from_token(token) if scheme.lower() == "bearer" and token else None
    if user is None:
        raise HTTPException(401, "Inte inloggad")
    return user


# Everything on this router needs a logged-in user. Logging in and out is done in Supabase, from the browser.
api = APIRouter(dependencies=[Depends(current_user)])


@api.get("/me")
async def me(user: dict = Depends(current_user)):
    """The logged-in user {"email", "name"}, or 401."""
    return {"email": user["email"], "name": user["name"]}


# --- Folders ---

class FolderRequest(BaseModel):
    name: str


@api.get("/folders")
async def list_folders(user: dict = Depends(current_user)):
    """The user's folders by name: [{"id", "name", "created", "document_count"}]."""
    return db.list_folders(user["id"])


@api.post("/folders")
async def create_folder(request: FolderRequest, user: dict = Depends(current_user)):
    if not request.name.strip():
        raise HTTPException(400, "Samlingen behöver ett namn.")
    return db.add_folder(request.name.strip(), user["id"])


@api.patch("/folders/{folder_id}")
async def rename_folder(folder_id: str, request: FolderRequest, user: dict = Depends(current_user)):
    if not request.name.strip():
        raise HTTPException(400, "Samlingen behöver ett namn.")
    if not db.rename_folder(folder_id, user["id"], request.name.strip()):
        raise HTTPException(404, "Unknown folder")
    return db.get_folder(folder_id, user["id"])


@api.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, user: dict = Depends(current_user)):
    """The folder and its documents. Extractions already made keep their rows."""
    if not db.delete_folder(folder_id, user["id"]):
        raise HTTPException(404, "Unknown folder")
    return {"deleted": folder_id}


# --- Reading ---

# Uploading is three calls: POST /uploads for where to put the file, the upload itself (straight to Supabase
# Storage, or PUT /uploads/{sha256} locally), then POST /jobs to read it.

class UploadRequest(BaseModel):
    folder_id: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@api.post("/uploads")
async def create_upload(request: UploadRequest, user: dict = Depends(current_user)):
    """Where the browser uploads the file: {"kind": "supabase", "path", "token"} or {"kind": "local", "url"}."""
    if db.get_folder(request.folder_id, user["id"]) is None:
        raise HTTPException(404, "Unknown folder")
    return storage.upload_target(user["id"], request.sha256)


@api.put("/uploads/{sha256}")
async def local_upload(sha256: str, request: Request, user: dict = Depends(current_user)):
    """The upload when the files are on disk (local development). In production they go to Supabase Storage."""
    if os.environ.get("SUPABASE_SERVICE_KEY"):
        raise HTTPException(404, "Upload to Supabase Storage")
    if storage.save(user["id"], await request.body()) != sha256:
        raise HTTPException(400, "Filen stämmer inte med sin sha256.")
    return {"sha256": sha256}


class JobRequest(BaseModel):
    folder_id: str
    name: str
    sha256: str
    no_model: bool = False
    max_model_pages: int = 0
    model: str = DEFAULT_MODEL
    words: bool = False


@api.post("/jobs")
async def create_job(request: JobRequest, user: dict = Depends(current_user)):
    """Read an uploaded file into one of the user's folders, in the background. Returns {"job_id": ...}."""
    if db.get_folder(request.folder_id, user["id"]) is None:
        raise HTTPException(404, "Unknown folder")
    try:
        data = storage.read(user["id"], request.sha256)
    except (FileNotFoundError, httpx.HTTPStatusError):
        raise HTTPException(400, "Filen är inte uppladdad.")
    if hashlib.sha256(data).hexdigest() != request.sha256:
        raise HTTPException(400, "Filen stämmer inte med sin sha256.")
    # A new version replaces the old one: same name in the same folder. Removed after the new one is added, so
    # that the file stays when it is the same file again.
    old = [d["id"] for d in db.list_documents(user["id"], request.folder_id) if d["name"] == request.name]
    job_id = uuid4().hex
    db.add_document(job_id, request.name, request.sha256,
                    {"allow_model": not request.no_model, "max_model_pages": request.max_model_pages or None,
                     "model": request.model, "words": request.words}, request.folder_id)
    for doc_id in old:
        db.delete_document(doc_id)
    await jobs.enqueue("read", {"job_id": job_id})
    return {"job_id": job_id}


@api.get("/jobs")
async def list_jobs(folder_id: str | None = None, user: dict = Depends(current_user)):
    """The user's read documents (all, or one folder's), newest first, with a summary instead of the result:
    [{"job_id", "name", "folder_id", "status", "error", "ok", "created", "options", "summary"}]."""
    return [{"job_id": d["id"], "name": d["name"], "folder_id": d["folder_id"], "status": d["status"],
             "error": d["error"], "ok": bool(d["ok"]), "created": d["created"], "options": d["options"],
             "summary": {k: d[k] for k in ("page_count", "pages", "model_pages", "partial", "skipped")}}
            for d in db.list_documents(user["id"], folder_id)]


@api.get("/jobs/{job_id}")
async def get_job(job_id: str, user: dict = Depends(current_user)):
    """Return {"status": queued|running|done|error, "name", "error", "result", "layout"}.
    result is exactly what read_document gave. layout is each page's text in reading order (layout.py),
    the same text the AI gets."""
    doc = db.get_document(job_id, user["id"])
    if doc is None:
        raise HTTPException(404, "Unknown job")
    layout = [layout_text(p) for p in doc["result"]["pages"]] if doc["result"] else None
    return {"status": doc["status"], "name": doc["name"], "error": doc["error"], "result": doc["result"], "layout": layout}


@api.post("/jobs/{job_id}/reread")
async def reread_job(job_id: str, ai: bool = True, user: dict = Depends(current_user)):
    """Read the saved file again, with AI reading on (or off). The document is updated in place."""
    doc = db.get_document(job_id, user["id"])
    if doc is None:
        raise HTTPException(404, "Unknown job")
    db.reset_document(job_id, {**doc["options"], "allow_model": ai})
    await jobs.enqueue("read", {"job_id": job_id})
    return {"job_id": job_id}


@api.delete("/jobs/{job_id}")
async def delete_job(job_id: str, user: dict = Depends(current_user)):
    """Remove a read document. Extractions already made from it keep their rows."""
    if db.get_document(job_id, user["id"]) is None or not db.delete_document(job_id):
        raise HTTPException(404, "Unknown job")
    return {"deleted": job_id}


@api.get("/jobs/{job_id}/file")
async def get_job_file(job_id: str, user: dict = Depends(current_user)):
    """Return the original uploaded file, so the UI can show it next to the text."""
    doc = db.get_document(job_id, user["id"])
    if doc is None:
        raise HTTPException(404, "Unknown job")
    media_type = mimetypes.guess_type(doc["name"])[0] or "application/octet-stream"
    return Response(storage.read(user["id"], doc["sha256"]), media_type=media_type)


# --- Step 2: templates and extraction ---

@api.get("/templates")
async def get_templates(user: dict = Depends(current_user)):
    """The user's templates."""
    return list_templates(user["id"])


@api.get("/templates/{template_id}")
async def get_template(template_id: str, user: dict = Depends(current_user)):
    template = load_template(template_id, user["id"])
    if template is None:
        raise HTTPException(404, "Unknown template")
    return template


@api.put("/templates")
async def put_template(template: Template, user: dict = Depends(current_user)):
    """Create or update a template. Returns it with its id."""
    try:
        saved = save_template(template, user["id"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    if saved is None:
        raise HTTPException(404, "Unknown template")
    return saved


@api.delete("/templates/{template_id}")
async def remove_template(template_id: str, user: dict = Depends(current_user)):
    if not delete_template(template_id, user["id"]):
        raise HTTPException(404, "Unknown template")
    return {"deleted": template_id}


class ExtractionRequest(BaseModel):
    template_id: str
    folder_id: str | None = None
    job_ids: list[str] = []  # empty with a folder: every read document in it
    paid: bool = False


@api.post("/extractions")
async def create_extraction(request: ExtractionRequest, user: dict = Depends(current_user)):
    """Run a template over read documents (job ids from step 1), one job per document. Returns {"extraction_id"}."""
    template = load_template(request.template_id, user["id"])
    if template is None:
        raise HTTPException(404, "Unknown template")
    if request.folder_id and db.get_folder(request.folder_id, user["id"]) is None:
        raise HTTPException(404, "Unknown folder")
    job_ids = request.job_ids
    if request.folder_id and not job_ids:
        job_ids = [d["id"] for d in reversed(db.list_documents(user["id"], request.folder_id))
                   if d["status"] == "done" and d["ok"]]
    if not job_ids:
        raise HTTPException(400, "Inga lästa dokument att köra.")
    docs = [db.get_document(j, user["id"]) for j in job_ids]
    if None in docs:
        raise HTTPException(404, "Unknown job")
    extraction_id = uuid4().hex
    documents = [{"job_id": d["id"], "name": d["name"], "status": "queued", "error": None} for d in docs]
    db.add_extraction(extraction_id, template.model_dump(), documents, request.folder_id, user["id"])
    for d in docs:
        await jobs.enqueue("extract", {"extraction_id": extraction_id, "job_id": d["id"], "paid": request.paid})
    return {"extraction_id": extraction_id}


@api.get("/extractions")
async def list_extractions(user: dict = Depends(current_user)):
    """The user's earlier runs, newest first: [{"id", "template_id", "template_name", "created", "status", "documents", "row_counts"}]."""
    return db.list_extractions(user["id"])


@api.get("/extractions/{extraction_id}")
async def get_extraction(extraction_id: str, user: dict = Depends(current_user)):
    """Return {"id", "status", "template_id", "template", "created", "documents": [{job_id, name, status, error}],
    "tables": {name: rows}, "checks": [...]}. template is the template as it was when the extraction ran;
    checks are its rules counted on the rows (checks.py)."""
    extraction = db.get_extraction(extraction_id, user["id"])
    if extraction is None:
        raise HTTPException(404, "Unknown extraction")
    template = Template.model_validate(extraction["template"])
    return extraction | {"checks": run_checks(template, extraction)}


@api.delete("/extractions/{extraction_id}")
async def delete_extraction(extraction_id: str, user: dict = Depends(current_user)):
    """Remove an earlier run. Documents still running in it are skipped by their jobs."""
    if not db.delete_extraction(extraction_id, user["id"]):
        raise HTTPException(404, "Unknown extraction")
    return {"deleted": extraction_id}


@api.get("/extractions/{extraction_id}/xlsx")
async def get_extraction_xlsx(extraction_id: str, user: dict = Depends(current_user)):
    """All tables in one Excel file, one sheet per table. Columns: dokument, the template's fields, sida."""
    extraction = db.get_extraction(extraction_id, user["id"])
    if extraction is None:
        raise HTTPException(404, "Unknown extraction")
    template = Template.model_validate(extraction["template"])  # as it was at the run
    workbook = Workbook()
    workbook.remove(workbook.active)
    for table in template.tables:
        sheet = workbook.create_sheet(table.name[:31])  # Excel's limit
        columns = ["dokument", *(f.name for f in table.fields), "sida"]
        sheet.append(columns)
        for row in extraction["tables"].get(table.name, []):
            sheet.append([row.get(c) for c in columns])
    out = BytesIO()
    workbook.save(out)
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{template.id}.xlsx"'})


@api.get("/config")
async def get_config(user: dict = Depends(current_user)):
    """What the UI needs to know: {"paid": paid calls allowed, "spent": USD this month, "budget": USD per month}."""
    return {"paid": llm.paid_allowed(), "spent": round(db.Meter(user["id"]).spent(), 2), "budget": limits.MONTHLY_USD}


app.include_router(api, prefix="/api")

# The website on / and the app on /app/, built by Vite (on Vercel by the build script in pyproject.toml, which
# puts them on the CDN). The API routes always come first. Locally Vite serves them itself (npm run dev).
FRONTEND = Path(__file__).parent.parent / "frontend" / "dist"
if FRONTEND.exists():
    app.frontend("/", directory=FRONTEND)
