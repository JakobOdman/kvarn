"""The background jobs, one document each. Queues may deliver a job twice or after a crash; that must not matter."""
import asyncio
import queue
from dataclasses import dataclass, field

import pytest
import vercel.queue

from api import db, jobs, llm, work
from tests.conftest import TEMPLATE, add_read_document


class ByName(llm.FakeClient):
    """One row per document, named after the text."""

    def send(self, prompt, schema, model):
        self.calls += 1
        return {"innehav": [{"bolag": prompt.rsplit("\n", 1)[-1], "varde": "1", "sida": 1}]}, 10, 1


@pytest.fixture
def extraction(anna, monkeypatch):
    """An extraction of three documents, not yet started: the jobs are run by hand in the tests."""
    monkeypatch.setattr(llm, "FakeClient", ByName)
    folder = anna.post("/folders", json={"name": "F"}).json()["id"]
    docs = [add_read_document(folder, f"{n}.pdf", f"Bolag {n}") for n in ("a", "b", "c")]
    template = anna.put("/templates", json=TEMPLATE).json()
    db.add_extraction("e1", template, [{"job_id": d, "name": db.get_document(d)["name"], "status": "queued",
                                        "error": None} for d in docs], folder, anna.user_id)
    return docs


def run(job_id, attempt=1):
    work.extract_job({"extraction_id": "e1", "job_id": job_id, "paid": False}, attempt)


def test_rows_keep_the_order_of_the_documents_whichever_finishes_first(extraction):
    for job_id in reversed(extraction):
        run(job_id)
        assert db.get_extraction("e1")["status"] == ("done" if job_id == extraction[0] else "running")
    rows = db.get_extraction("e1")["tables"]["innehav"]
    assert [r["dokument"] for r in rows] == ["a.pdf", "b.pdf", "c.pdf"]


def test_a_job_delivered_twice_adds_its_rows_once(extraction):
    run(extraction[0])
    run(extraction[0])
    assert len(db.get_extraction("e1")["tables"]["innehav"]) == 1


def test_after_too_many_attempts_the_document_gets_an_error(extraction):
    run(extraction[0], attempt=work.MAX_ATTEMPTS + 1)
    doc = db.get_extraction("e1")["documents"][0]
    assert (doc["status"], doc["error"]) == ("error", "Tog för lång tid.")
    run(extraction[0])  # a late delivery changes nothing
    assert db.get_extraction("e1")["tables"]["innehav"] == []


@dataclass
class Read:
    ok: bool = True
    page_count: int = 1
    pages: list = field(default_factory=lambda: [{"page_no": 1, "text": "Hej", "reader": "pdf_text", "words": [1]}])


def test_reading_takes_the_file_from_the_owners_storage(anna, monkeypatch):
    seen = []
    monkeypatch.setattr(work, "read_document", lambda data, name, **kw: seen.append(data) or Read())
    folder = anna.post("/folders", json={"name": "F"}).json()["id"]
    doc = add_read_document(folder, text="Filens innehåll")
    db.update_document(doc, "queued")
    work.read_job({"job_id": doc})
    work.read_job({"job_id": doc})  # twice: read once
    assert seen == ["Filens innehåll".encode()]
    assert db.get_document(doc)["result"]["pages"][0] == {"page_no": 1, "text": "Hej", "reader": "pdf_text"}  # no words


def test_reading_too_many_times_is_an_error(anna):
    folder = anna.post("/folders", json={"name": "F"}).json()["id"]
    doc = add_read_document(folder)
    db.update_document(doc, "running")
    work.read_job({"job_id": doc}, attempt=work.MAX_ATTEMPTS + 1)
    assert db.get_document(doc)["error"] == "Läsningen tog för lång tid."


def test_on_vercel_the_jobs_go_to_vercel_queues(monkeypatch):
    sent = []

    async def send(topic, payload):
        sent.append((topic, payload))

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(vercel.queue, "send", send)
    asyncio.run(jobs.enqueue("extract", {"extraction_id": "e1", "job_id": "d1", "paid": False}))
    assert sent == [("extract", {"extraction_id": "e1", "job_id": "d1", "paid": False})]


def test_a_message_on_each_topic_reaches_its_worker(monkeypatch):
    """Through the SDK's own queue service in this process: send, delivery to workers.py, acknowledge."""
    import api.workers  # noqa: F401 - registers the subscribers
    from vercel.queue.embedded import embedded_queue_service

    done = queue.Queue()  # the workers run the jobs in threads
    for topic, name in [("read", "read_job"), ("extract", "extract_job")]:
        monkeypatch.setattr(work, name, lambda payload, attempt, topic=topic: done.put((topic, payload, attempt)))

    async def send_both():
        async with embedded_queue_service() as service:
            client = service.get_async_client()
            await client.send("read", {"job_id": "d1"})
            await client.send("extract", {"extraction_id": "e1", "job_id": "d1", "paid": False})
            return sorted([await asyncio.to_thread(done.get, timeout=10) for _ in range(2)], key=lambda r: r[0])

    assert asyncio.run(send_both()) == [("extract", {"extraction_id": "e1", "job_id": "d1", "paid": False}, 1),
                                        ("read", {"job_id": "d1"}, 1)]
