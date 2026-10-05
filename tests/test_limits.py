"""What the AI may cost: limits per document and a budget per user and month (limits.py). No real calls."""
from dataclasses import dataclass, field

import pytest

from api import db, limits, llm, work
from tests.conftest import add_read_document

SCHEMA = {"type": "object"}


class Paid:
    """Looks like a real client to llm.ask (not the fake one), so the budget applies."""

    def __init__(self, tokens_in=10_000, tokens_out=2_000):
        self.calls, self.tokens = 0, (tokens_in, tokens_out)

    def send(self, prompt, schema, model):
        self.calls += 1
        return {"ok": True}, *self.tokens


@pytest.fixture
def paid_mode(monkeypatch):
    monkeypatch.setenv("READ_DOCUMENT_PAID", "1")


def test_cost():
    assert limits.cost("gpt-5.4", 1_000_000, 0) == 2.50
    assert limits.cost("gpt-5.4", 0, 1_000_000) == 15.00
    assert limits.cost("okänd-modell", 0, 1_000_000) == 15.00  # unknown models count as the most expensive
    assert round(limits.PAGE_USD, 3) == 0.064


def test_a_paid_call_is_counted_in_the_budget(paid_mode):
    client = Paid(tokens_in=100_000, tokens_out=10_000)
    llm.ask("p", SCHEMA, db.Cache("anna"), db.Meter("anna"), client=client, paid=True)
    assert round(db.Meter("anna").spent(), 4) == round(100_000 * 2.5 / 1e6 + 10_000 * 15 / 1e6, 4)
    assert db.Meter("bertil").spent() == 0


def test_a_cached_answer_is_free_even_when_the_budget_is_used_up(paid_mode):
    db.Meter("anna").add(limits.MONTHLY_USD)
    db.Cache("anna").put(llm.cache_key("p", SCHEMA, llm.MODEL),
                         {"model": llm.MODEL, "tokens_in": 1, "tokens_out": 1, "answer": {"sparat": True}})
    assert llm.ask("p", SCHEMA, db.Cache("anna"), db.Meter("anna"), client=Paid(), paid=True)[0] == {"sparat": True}


def test_no_new_call_when_the_budget_does_not_cover_the_worst_case(paid_mode):
    db.Meter("anna").add(limits.MONTHLY_USD - 0.10)  # 10 cents left, a full answer alone costs 0.48 USD
    client = Paid()
    with pytest.raises(limits.QuotaExceeded, match="AI-budget"):
        llm.ask("p", SCHEMA, db.Cache("anna"), db.Meter("anna"), client=client, paid=True)
    assert client.calls == 0


def test_a_too_large_document_is_stopped_before_the_call(paid_mode):
    client = Paid()
    with pytest.raises(limits.TooLarge, match="för stort"):
        llm.ask("x" * (limits.MAX_TOKENS_IN * 3 + 3), SCHEMA, db.Cache("anna"), db.Meter("anna"), client=client, paid=True)
    assert client.calls == 0


def test_the_extraction_shows_why_a_document_was_stopped(anna, paid_mode, monkeypatch):
    """Through the whole chain: the document gets the budget error, the extraction carries on."""
    monkeypatch.setattr(llm, "AzureClient", Paid)
    folder = anna.post("/folders", json={"name": "F"}).json()["id"]
    add_read_document(folder)
    db.Meter(anna.user_id).add(limits.MONTHLY_USD)
    template = anna.put("/templates", json={"name": "T", "prompt": "p", "tables": [{"name": "t", "fields": [{"name": "a"}]}]}).json()
    e = anna.post("/extractions", json={"template_id": template["id"], "folder_id": folder, "paid": True}).json()
    doc = anna.get(f"/extractions/{e['extraction_id']}").json()["documents"][0]
    assert doc["status"] == "error" and "AI-budget" in doc["error"]


def test_config_shows_the_months_spending(anna):
    db.Meter(anna.user_id).add(1.234)
    assert anna.get("/config").json() == {"paid": False, "spent": 1.23, "budget": limits.MONTHLY_USD}


# --- AI reading ---

@dataclass
class Read:
    pages: list = field(default_factory=list)
    ok: bool = True
    page_count: int = 0


def reading(monkeypatch, ai_pages=5):
    """read_document replaced: records how it was called, returns ai_pages pages read by AI."""
    calls = []

    def fake(data, name, allow_model, max_model_pages, model):
        calls.append((allow_model, max_model_pages))
        n = min(ai_pages, max_model_pages or ai_pages) if allow_model else 0
        return Read(pages=[{"page_no": i, "text": "", "reader": "claude_vision"} for i in range(n)])

    monkeypatch.setattr(work, "read_document", fake)
    return calls


def queued_document(client, allow_model=True, max_model_pages=None):
    folder = client.post("/folders", json={"name": "F"}).json()["id"]
    doc = add_read_document(folder)
    with db.connect() as con:
        con.execute("UPDATE documents SET status = 'queued', options = options || %s::jsonb WHERE id = %s",
                    (f'{{"allow_model": {str(allow_model).lower()}, "max_model_pages": {max_model_pages or "null"}}}', doc))
    return doc


def test_ai_reading_needs_paid_mode(anna, monkeypatch):
    calls = reading(monkeypatch)
    work.read_job({"job_id": queued_document(anna)})
    assert calls == [(False, None)]
    assert db.Meter(anna.user_id).spent() == 0


def test_ai_reading_is_capped_and_counted(anna, paid_mode, monkeypatch):
    calls = reading(monkeypatch, ai_pages=50)
    work.read_job({"job_id": queued_document(anna)})
    assert calls == [(True, limits.MAX_MODEL_PAGES)]
    assert round(db.Meter(anna.user_id).spent(), 4) == round(limits.MAX_MODEL_PAGES * limits.PAGE_USD, 4)


def test_ai_reading_stops_at_what_the_budget_covers(anna, paid_mode, monkeypatch):
    db.Meter(anna.user_id).add(limits.MONTHLY_USD - 3 * limits.PAGE_USD - 0.001)  # room for three pages
    calls = reading(monkeypatch)
    work.read_job({"job_id": queued_document(anna)})
    assert calls == [(True, 3)]


def test_no_ai_reading_when_the_budget_is_used_up(anna, paid_mode, monkeypatch):
    db.Meter(anna.user_id).add(limits.MONTHLY_USD)
    calls = reading(monkeypatch)
    work.read_job({"job_id": queued_document(anna)})
    assert calls == [(False, None)]
