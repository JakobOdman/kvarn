"""
llm.py - send text and a prompt to the model, get JSON back.

Answers are cached (db.Cache, per owner), so running the same thing again costs nothing.
Paid calls need the server to be started with READ_DOCUMENT_PAID=1, otherwise only the cache is used.
"""
import hashlib
import json
import os

from api import limits

AZURE_ENDPOINT = "https://OdmanFoundry.services.ai.azure.com/openai/v1"
MODEL = "gpt-5.4"


class NotCached(Exception):
    """No cached answer, and a paid call was not allowed."""


class FakeClient:
    """For development and tests. Sends nothing, returns a fixed answer (default: no rows in any table)."""

    def __init__(self, answer: dict | None = None):
        self.answer = answer
        self.calls = 0

    def send(self, prompt: str, schema: dict, model: str) -> tuple[dict, int, int]:
        self.calls += 1
        answer = self.answer if self.answer is not None else {table: [] for table in schema["properties"]}
        return answer, 0, 0


class AzureClient:
    """GPT-5.4 in Azure Foundry. The key is read from AZURE_OPENAI_API_KEY on the first call."""

    def __init__(self):
        self.client = None

    def send(self, prompt: str, schema: dict, model: str) -> tuple[dict, int, int]:
        if self.client is None:
            key = os.environ.get("AZURE_OPENAI_API_KEY")
            if not key:
                raise RuntimeError("AZURE_OPENAI_API_KEY is not set.")
            from openai import OpenAI
            self.client = OpenAI(base_url=AZURE_ENDPOINT, api_key=key)
        extra = {}
        reasoning = os.environ.get("LLM_REASONING", "none")
        if reasoning:
            extra["reasoning"] = {"effort": reasoning}
        answer = self.client.responses.create(
            model=model,
            input=[{"role": "user", "content": prompt}],
            text={"format": {"type": "json_schema", "name": "svar", "schema": schema, "strict": True}},
            max_output_tokens=limits.MAX_TOKENS_OUT,
            **extra,
        )
        if answer.status == "incomplete":
            raise ValueError(f"Svaret blev längre än {limits.MAX_TOKENS_OUT:,} tokens och avbröts.".replace(",", " "))
        return json.loads(answer.output_text), answer.usage.input_tokens, answer.usage.output_tokens


def paid_allowed() -> bool:
    return os.environ.get("READ_DOCUMENT_PAID") == "1"


def cache_key(prompt: str, schema: dict, model: str) -> str:
    """sha256 over prompt (which includes the document text), schema and model."""
    h = hashlib.sha256()
    h.update(prompt.encode("utf-8"))
    h.update(json.dumps(schema, sort_keys=True).encode("utf-8"))
    h.update(model.encode("utf-8"))
    return h.hexdigest()


def ask(prompt: str, schema: dict, cache, meter=None, model: str = MODEL, client=None,
        paid: bool = False) -> tuple[dict, dict]:
    """(answer, usage) from the cache, or from the client if paid is True. NotCached if neither.
    cache has get(key) -> saved or None, and put(key, saved); saved = {"model", "tokens_in", "tokens_out", "answer"}.
    meter has remaining() -> USD left this month, and add(usd, tokens_in, tokens_out) (db.Meter).
    usage = {"tokens_in", "tokens_out", "cached"}: the tokens of the call, also when the answer came from the cache.

    A FakeClient is always allowed. A real client needs paid=True and READ_DOCUMENT_PAID=1.
    A cached answer is always free. Before a new call: TooLarge for a document over limits.MAX_TOKENS_IN, and
    QuotaExceeded if the month's budget does not cover the call's worst case (full answer length).
    """
    key = cache_key(prompt, schema, model)
    if saved := cache.get(key):
        return saved["answer"], {"tokens_in": saved["tokens_in"], "tokens_out": saved["tokens_out"], "cached": True}

    if client is None or (not isinstance(client, FakeClient) and not (paid and paid_allowed())):
        raise NotCached("No cached answer and no paid call allowed.")

    estimate = limits.estimate_tokens(prompt)
    if estimate > limits.MAX_TOKENS_IN:
        raise limits.TooLarge(f"Dokumentet är för stort för en körning: cirka {estimate:,} tokens, högst "
                              f"{limits.MAX_TOKENS_IN:,}.".replace(",", " "))
    if not isinstance(client, FakeClient):
        worst = limits.cost(model, estimate, limits.MAX_TOKENS_OUT)
        if meter is None or meter.remaining() < worst:
            raise limits.QuotaExceeded(f"Månadens AI-budget räcker inte ({limits.MONTHLY_USD:.0f} USD per månad). "
                                       "Sparade svar fungerar fortfarande.")

    answer, tokens_in, tokens_out = client.send(prompt, schema, model)
    usage = {"tokens_in": tokens_in, "tokens_out": tokens_out, "cached": False}
    if isinstance(client, FakeClient):
        return answer, usage  # fake answers are never cached

    print(f"{model}: {tokens_in} tokens in, {tokens_out} out")
    meter.add(limits.cost(model, tokens_in, tokens_out), tokens_in=tokens_in, tokens_out=tokens_out)
    cache.put(key, {"model": model, "tokens_in": tokens_in, "tokens_out": tokens_out, "answer": answer})
    return answer, usage
