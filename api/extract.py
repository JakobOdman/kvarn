"""
extract.py - read documents + a template -> rows in the template's tables.

One call per document. Every row gets document, page and quote.
"""
from api import llm
from api.layout import layout_text
from api.templates import Template, schema_for

ENGINE_PROMPT = """## Dokumentet

Texten är redan utläst ur dokumentet. Varje sida börjar med raden `=== Sida N ===`.
- `sida`: numret N för sidan där raden står, inte sidnumret som står tryckt på sidan.
- Skriv bara det som står. Står ett värde inte där lämnar du fältet tomt. Tomt är hellre än påhittat.
"""


def pages_as_text(result: dict) -> str:
    """The read_document result as '=== Sida N ===' followed by the text, page by page.
    Pages with word positions are laid out in reading order, see layout.py."""
    return "\n\n".join(f"=== Sida {p['page_no']} ===\n{layout_text(p)}" for p in result["pages"])


def extract_document(name: str, result: dict, template: Template, cache, client=None,
                     paid: bool = False) -> tuple[dict[str, list[dict]], dict]:
    """One document -> ({table name: rows}, usage). usage is the tokens, see llm.ask."""
    if not result["pages"]:
        raise ValueError("Dokumentet har ingen text.")
    prompt = f"{template.prompt}\n\n{ENGINE_PROMPT}\n{pages_as_text(result)}"
    answer, usage = llm.ask(prompt, schema_for(template), cache, client=client, paid=paid)
    return {table: [{"dokument": name, **row} for row in rows] for table, rows in answer.items()}, usage
