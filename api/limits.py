"""
limits.py - what the AI may cost: prices, limits per document and a budget per user and month.

Change them without touching the code, with environment variables (in Vercel: Settings -> Environment Variables):
  KVARN_MONTHLY_USD       budget per user and month, in USD (default 10)
  KVARN_MAX_TOKENS_IN     largest document text for one extraction call (default 200 000)
  KVARN_MAX_TOKENS_OUT    longest answer from the extraction model (default 32 000)
  KVARN_MAX_MODEL_PAGES   most pages read by AI in one document (default 30)
"""
import os

# USD per million tokens (in, out). Azure Global Standard and Anthropic list prices, 2026-10.
PRICES = {
    "gpt-5.4": (2.50, 15.00),
    "claude-sonnet-5-5": (2.00, 10.00),
}
MOST_EXPENSIVE = max(PRICES.values(), key=lambda p: p[1])  # for a model not in the list

MONTHLY_USD = float(os.environ.get("KVARN_MONTHLY_USD", 10))
MAX_TOKENS_IN = int(os.environ.get("KVARN_MAX_TOKENS_IN", 200_000))
MAX_TOKENS_OUT = int(os.environ.get("KVARN_MAX_TOKENS_OUT", 32_000))
MAX_MODEL_PAGES = int(os.environ.get("KVARN_MAX_MODEL_PAGES", 30))

# read_document.py does not report its tokens, so a page read by AI counts as the worst case:
# an image of about 2 000 tokens in and its max_tokens of 6 000 out, with Claude Sonnet 5.5.
PAGE_USD = 2_000 * 2.00 / 1e6 + 6_000 * 10.00 / 1e6


class TooLarge(Exception):
    """The document is too large for one call."""


class QuotaExceeded(Exception):
    """This month's AI budget is used up."""


def cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = PRICES.get(model, MOST_EXPENSIVE)
    return tokens_in * price_in / 1e6 + tokens_out * price_out / 1e6


def estimate_tokens(text: str) -> int:
    """Roughly, and rather too many than too few: Swedish and English run about 3.5-4 characters per token."""
    return len(text) // 3
