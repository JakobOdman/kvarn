"""
read_document.py - read any document into page text.

Two steps:
  1. Decide what the file IS from its bytes (magic numbers), not from its name.
  2. Read it the cheapest way that works: text layers first (local, free, exact,
     with word boxes), the model only for scanned pages, picture pages and photos.

Install:
  pip install pymupdf pillow pillow-heif "markitdown[docx,xlsx,pptx]" anthropic

Usage:
  python read_document.py faktura.pdf                 # read, model for scans
  python read_document.py avtal.pdf --no-model        # text layers only
  python read_document.py arkiv.pdf --max-model-pages 5
  python read_document.py kvitto.heic --words         # include word boxes in output

Env:
  ANTHROPIC_API_KEY   required for scans and photos
  READER_MODEL        model id for transcription (default below)
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal, Optional

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

SCANNED_PAGE_MAX_CHARS = 16        # fewer non-space chars than this = scanned page
IMAGE_PAGE_MAX_CHARS = 400         # page with an image and less text = picture page (a pasted table)
MODEL_PAGE_CONCURRENCY = 3         # pages the model reads at once
IMAGE_MAX_DIMENSION = 2000         # px, longest side sent to the model
IMAGE_DOWNSCALE_THRESHOLD = int(3.5 * 1024 * 1024)  # base64 is 4/3 of the file; API limit is 5 MB
DEFAULT_MODEL = os.environ.get("READER_MODEL", "claude-sonnet-5-5")

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
ODT = "application/vnd.oasis.opendocument.text"
ODS = "application/vnd.oasis.opendocument.spreadsheet"
ODP = "application/vnd.oasis.opendocument.presentation"
DOC, XLS, PPT = "application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint"

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif"}
OFFICE_TYPES = {DOCX, XLSX, PPTX, ODT, ODS, ODP, DOC, XLS, PPT, "application/rtf"}
STRUCTURED_TYPES = {"application/xml", "text/xml", "application/json"}  # the file IS the record

EXTENSION_TYPES = {
    "pdf": PDF, "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp",
    "gif": "image/gif", "heic": "image/heic", "heif": "image/heif",
    "docx": DOCX, "xlsx": XLSX, "pptx": PPTX, "odt": ODT, "ods": ODS, "odp": ODP,
    "doc": DOC, "xls": XLS, "ppt": PPT, "rtf": "application/rtf", "csv": "text/csv",
    "txt": "text/plain", "html": "text/html", "htm": "text/html", "xml": "application/xml",
    "json": "application/json",
}
TYPE_EXTENSIONS = {v: k for k, v in reversed(list(EXTENSION_TYPES.items()))}

HEIC_BRANDS = {"heic", "heix", "heim", "heis", "hevc", "hevx", "hevm", "hevs"}
HEIF_BRANDS = {"mif1", "msf1"}

# --------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------

Reader = Literal["pdf_text", "office", "claude_vision", "text", "html"]


@dataclass
class WordBox:
    t: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class ReadPage:
    page_no: int
    text: str
    reader: Reader
    has_text_layer: bool
    words: Optional[list[WordBox]] = None
    page_width: Optional[float] = None
    page_height: Optional[float] = None


@dataclass
class ReadOutcome:
    ok: bool
    mime_type: Optional[str] = None
    pages: list[ReadPage] = field(default_factory=list)
    reader: Optional[Reader] = None
    page_count: int = 0
    partial: Optional[str] = None   # 'ai_gated' | 'budget' | 'ai_unconfigured'
    skipped: Optional[str] = None   # 'structured' | 'unsupported_mime' | 'empty' | ...


# --------------------------------------------------------------------------
# Step 1: what is this file? (magic bytes, then a few text heuristics)
# --------------------------------------------------------------------------

def _zip_office_type(data: bytes) -> Optional[str]:
    """A ZIP is only an Office file if its own manifest says so."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if "mimetype" in names:  # OpenDocument names its type in an uncompressed entry
                odf = z.read("mimetype").decode("ascii", "ignore").strip()
                return odf if odf in {ODT, ODS, ODP} else None
            if "[Content_Types].xml" in names:
                tops = {n.split("/", 1)[0] for n in names}
                if "word" in tops:
                    return DOCX
                if "xl" in tops:
                    return XLSX
                if "ppt" in tops:
                    return PPTX
    except zipfile.BadZipFile:
        return None
    return None


def _looks_like_csv(head: str) -> bool:
    lines = [l for l in head.splitlines()[:5] if l.strip()]
    if len(lines) < 2:
        return False
    for sep in (";", ",", "\t"):
        counts = {l.count(sep) for l in lines}
        if len(counts) == 1 and counts.pop() > 0:
            return True
    return False


def detect_mime(data: bytes, file_name: Optional[str] = None) -> Optional[str]:
    """The type the bytes prove. The extension is only a hint where the bytes are ambiguous."""
    ext = Path(file_name).suffix.lower().lstrip(".") if file_name else ""
    hinted = EXTENSION_TYPES.get(ext)
    if len(data) < 4:
        return None
    b = data

    if b[:4] == b"\x89PNG":
        return "image/png"
    if b[:4] == b"PK\x03\x04":
        return _zip_office_type(b)
    if b[:4] == b"\xd0\xcf\x11\xe0":  # OLE: legacy .doc/.xls/.ppt, the container does not say which
        return hinted if hinted in {DOC, XLS, PPT} else DOC
    if b[:5] == b"{\\rtf":
        return "application/rtf"
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(b) >= 12 and b[4:8] == b"ftyp":
        brand = b[8:12].decode("ascii", "ignore")
        if brand in HEIC_BRANDS:
            return "image/heic"
        if brand in HEIF_BRANDS:
            return "image/heif"
    # PDFs sometimes carry junk before the marker: look in the first KB.
    if b"%PDF-" in b[:1029]:
        return PDF

    # No binary signature: is it text at all?
    head_bytes = b[:8192]
    if b"\x00" in head_bytes:
        return None
    try:
        head = head_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            head = head_bytes.decode("cp1252")  # Swedish exports from older systems
        except UnicodeDecodeError:
            return None
    stripped = head.lstrip()
    low = stripped[:256].lower()
    if low.startswith("<!doctype html") or low.startswith("<html"):
        return "text/html"
    if low.startswith("<?xml"):
        return "text/html" if "<html" in low else "application/xml"
    if stripped[:1] in ("{", "["):
        try:
            json.loads(b.decode("utf-8-sig"))
            return "application/json"
        except (ValueError, UnicodeDecodeError):
            pass
    if hinted == "text/csv" or _looks_like_csv(head):
        return "text/csv"
    return "text/plain"


def reader_for_mime(mime: Optional[str]) -> Optional[str]:
    if not mime:
        return None
    if mime == PDF:
        return "pdf_text"
    if mime in IMAGE_TYPES:
        return "claude_vision"
    if mime in OFFICE_TYPES:
        return "office"
    if mime in ("text/html", "application/xhtml+xml"):
        return "html"
    if mime in ("text/plain", "text/csv"):  # CSV is text: keep the separators as they are
        return "text"
    if mime in STRUCTURED_TYPES:
        return "structured"
    return None


# --------------------------------------------------------------------------
# The model: transcribe, never interpret
# --------------------------------------------------------------------------

NO_TEXT = "NO_TEXT"
TRANSCRIBE_SYSTEM = (
    "You transcribe documents. Return the complete text of the page "
    "exactly as printed, in reading order, one line per printed line, tables as rows with cells "
    'separated by " | ". Keep numbers, dates, names and identifiers exactly. Do not summarise, '
    "translate, describe, or add anything that is not on the page. If the page has no printed text to "
    "transcribe (blank, unreadable, a photo of an object or a person, a QR code or barcode alone), "
    f"answer with exactly {NO_TEXT} and nothing else."
)

# The model talking ABOUT the page instead of transcribing it: never store that as document text.
_COMMENTARY_RE = re.compile(
    r"^\s*(i'm not able|i am not able|i'm unable|i am unable|i cannot|i can't|i do not see|i don't see|"
    r"(the|this) (page|image|document|photo|picture) (appears|seems|is|contains|does|shows)|"
    r"there is no (readable |visible |legible )?text|no (readable |visible |legible )?text|"
    r"unable to (transcribe|read)|jag kan inte|sidan (verkar|är) (vara )?tom|bilden (verkar|innehåller|visar))",
    re.IGNORECASE,
)


def is_reader_commentary(text: str) -> bool:
    t = text.strip()
    return t in ("", NO_TEXT) or (len(t) < 400 and bool(_COMMENTARY_RE.match(t)))


class ModelUnavailable(Exception):
    pass


_client = None


def _anthropic():
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ModelUnavailable("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic
        except ImportError as e:
            raise ModelUnavailable("pip install anthropic") from e
        _client = anthropic.Anthropic()
    return _client


def transcribe(block: dict, model: str = DEFAULT_MODEL) -> str:
    """block is an Anthropic content block (document or image). Returns '' for no text."""
    resp = _anthropic().messages.create(
        model=model,
        max_tokens=6000,
        system=TRANSCRIBE_SYSTEM,
        messages=[{"role": "user", "content": [block, {"type": "text", "text": "Transcribe this page."}]}],
    )
    text = "".join(getattr(c, "text", "") for c in resp.content).strip()
    return "" if is_reader_commentary(text) else text


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode("ascii")


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Storable text: control chars out (tabs/newlines kept), runs of spaces folded."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def read_pdf(data: bytes, allow_model: bool, max_model_pages: Optional[int], model: str) -> ReadOutcome:
    import pymupdf  # PyMuPDF

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages: dict[int, ReadPage] = {}
    needs_vision: list[int] = []
    picture_pages: list[int] = []

    for i, page in enumerate(doc):
        page_no = i + 1
        text = _clean_text(page.get_text("text"))
        chars = len(re.sub(r"\s", "", text))
        if chars < SCANNED_PAGE_MAX_CHARS:
            needs_vision.append(page_no)
            continue
        if chars < IMAGE_PAGE_MAX_CHARS and page.get_image_info():  # images actually painted on the page
            picture_pages.append(page_no)
        words = [
            WordBox(t=w[4], x0=round(w[0], 1), y0=round(w[1], 1), x1=round(w[2], 1), y1=round(w[3], 1))
            for w in page.get_text("words")  # top-left origin already
        ]
        pages[page_no] = ReadPage(
            page_no=page_no, text=text, reader="pdf_text", has_text_layer=True,
            words=words or None, page_width=round(page.rect.width, 1), page_height=round(page.rect.height, 1),
        )

    # Scanned pages first, then picture pages: a budget takes them in that order.
    candidates = [(p, False) for p in needs_vision] + [(p, True) for p in picture_pages]
    partial = None
    if candidates and not allow_model:
        partial, candidates = "ai_gated", []
    elif max_model_pages is not None and len(candidates) > max_model_pages:
        partial, candidates = "budget", candidates[:max_model_pages]

    def single_page(page_no: int) -> bytes:
        out = pymupdf.open()
        out.insert_pdf(doc, from_page=page_no - 1, to_page=page_no - 1)
        return out.tobytes()

    def read_one(c: tuple[int, bool]):
        page_no, picture = c
        block = {"type": "document", "source": {"type": "base64", "media_type": PDF, "data": _b64(single_page(page_no))}}
        try:
            return page_no, picture, transcribe(block, model)
        except ModelUnavailable:
            return page_no, picture, None

    if candidates:
        with ThreadPoolExecutor(MODEL_PAGE_CONCURRENCY) as pool:
            for page_no, picture, text in pool.map(read_one, candidates):
                if text is None:
                    partial = "ai_unconfigured"
                    continue
                if not text:
                    continue
                if picture:  # the model read the whole page; it replaces the thin text layer, boxes stay
                    p = pages[page_no]
                    p.text, p.reader = text, "claude_vision"
                else:
                    pages[page_no] = ReadPage(page_no=page_no, text=text, reader="claude_vision", has_text_layer=False)

    page_count = doc.page_count
    doc.close()
    ordered = [pages[k] for k in sorted(pages)]
    if not ordered:
        return ReadOutcome(ok=False, mime_type=PDF, skipped=partial or "empty")
    has_local = any(p.has_text_layer for p in ordered)
    return ReadOutcome(ok=True, mime_type=PDF, pages=ordered, reader="pdf_text" if has_local else "claude_vision",
                       page_count=page_count, partial=partial)


def fit_image_for_model(data: bytes, mime: str) -> Optional[tuple[bytes, str]]:
    """EXIF-rotate, fit inside 2000 px, JPEG 80 - only when needed. HEIC is always decoded."""
    is_heic = mime in ("image/heic", "image/heif")
    if not is_heic and mime != "image/gif" and len(data) <= IMAGE_DOWNSCALE_THRESHOLD:
        return data, mime
    try:
        from PIL import Image, ImageOps
        if is_heic:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        img.thumbnail((IMAGE_MAX_DIMENSION, IMAGE_MAX_DIMENSION))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=80)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:  # noqa: BLE001
        print(f"warning: image not fitted ({e})", file=sys.stderr)
        return None if is_heic else (data, mime)


def read_image(data: bytes, mime: str, allow_model: bool, model: str) -> ReadOutcome:
    if not allow_model:
        return ReadOutcome(ok=False, mime_type=mime, skipped="ai_gated")
    fitted = fit_image_for_model(data, mime)
    if not fitted:
        return ReadOutcome(ok=False, mime_type=mime, skipped="unsupported_mime")
    img, media_type = fitted
    try:
        text = transcribe({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": _b64(img)}}, model)
    except ModelUnavailable:
        return ReadOutcome(ok=False, mime_type=mime, skipped="ai_unconfigured")
    if not text:
        return ReadOutcome(ok=False, mime_type=mime, skipped="empty")
    return ReadOutcome(ok=True, mime_type=mime, reader="claude_vision", page_count=1,
                       pages=[ReadPage(page_no=1, text=text, reader="claude_vision", has_text_layer=False)])


def _legacy_office_to_pdf(data: bytes, mime: str) -> Optional[bytes]:
    """.doc/.xls/.ppt: markitdown does not read OLE files; LibreOffice converts them if it is installed."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in.{TYPE_EXTENSIONS.get(mime, 'doc')}"
        src.write_bytes(data)
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)],
                       check=False, capture_output=True, timeout=120)
        out = Path(tmp) / "in.pdf"
        return out.read_bytes() if out.exists() else None


def read_office(data: bytes, mime: str, allow_model: bool, max_model_pages: Optional[int], model: str) -> ReadOutcome:
    if mime in (DOC, XLS, PPT):
        pdf = _legacy_office_to_pdf(data, mime)
        if pdf is None:
            return ReadOutcome(ok=False, mime_type=mime, skipped="unsupported_mime")
        out = read_pdf(pdf, allow_model, max_model_pages, model)
        out.mime_type = mime
        return out
    from markitdown import MarkItDown
    ext = "." + TYPE_EXTENSIONS.get(mime, "docx")
    md = MarkItDown().convert_stream(io.BytesIO(data), file_extension=ext).text_content
    md = _clean_text(md or "")
    if not md:
        return ReadOutcome(ok=False, mime_type=mime, skipped="empty")
    return ReadOutcome(ok=True, mime_type=mime, reader="office", page_count=1,
                       pages=[ReadPage(page_no=1, text=md, reader="office", has_text_layer=True)])


class _HtmlText(HTMLParser):
    BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section", "article", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def read_text(data: bytes, mime: str) -> ReadOutcome:
    try:
        raw = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raw = data.decode("cp1252", errors="replace")
    reader: Reader = "html" if mime in ("text/html", "application/xhtml+xml") else "text"
    if reader == "html":
        p = _HtmlText()
        p.feed(raw)
        raw = "".join(p.parts)
    text = _clean_text(raw)
    if not text:
        return ReadOutcome(ok=False, mime_type=mime, skipped="empty")
    return ReadOutcome(ok=True, mime_type=mime, reader=reader, page_count=1,
                       pages=[ReadPage(page_no=1, text=text, reader=reader, has_text_layer=True)])


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------

def read_document(data: bytes, file_name: Optional[str] = None, *, allow_model: bool = True,
                  max_model_pages: Optional[int] = None, model: str = DEFAULT_MODEL) -> ReadOutcome:
    """Text layers first (local, free, with word boxes), the model only for scans and photos."""
    if not data:
        return ReadOutcome(ok=False, skipped="empty")
    mime = detect_mime(data, file_name)
    reader = reader_for_mime(mime)
    if reader is None:
        return ReadOutcome(ok=False, mime_type=mime, skipped="unsupported_mime")
    if reader == "structured":
        return ReadOutcome(ok=False, mime_type=mime, skipped="structured")
    if reader == "pdf_text":
        return read_pdf(data, allow_model, max_model_pages, model)
    if reader == "claude_vision":
        return read_image(data, mime, allow_model, model)
    if reader == "office":
        return read_office(data, mime, allow_model, max_model_pages, model)
    return read_text(data, mime)


def main() -> None:
    ap = argparse.ArgumentParser(description="Read a document into page text.")
    ap.add_argument("path")
    ap.add_argument("--no-model", action="store_true", help="text layers only, never call the model")
    ap.add_argument("--max-model-pages", type=int, default=None, help="cap on pages the model reads")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--words", action="store_true", help="include word boxes in the output")
    args = ap.parse_args()

    path = Path(args.path)
    out = read_document(path.read_bytes(), path.name, allow_model=not args.no_model,
                        max_model_pages=args.max_model_pages, model=args.model)
    result = asdict(out)
    if not args.words:
        for p in result["pages"]:
            p.pop("words", None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
