"""
workers.py - Vercel Queues subscribers: one function per message, one document per message (work.py).

Listed in pyproject.toml under [[tool.vercel.subscribers]]; Vercel makes private queue-triggered functions of them.
Each has the function's time limit (300 s on Hobby) for its one document.
"""
import asyncio

from vercel.queue import Message, subscribe

from api import work


@subscribe(topic="read", max_attempts=work.MAX_ATTEMPTS + 1, retry_after=30)
async def read(message: Message[dict[str, object]]) -> None:
    await asyncio.to_thread(work.read_job, message.payload, message.metadata.delivery_count)


@subscribe(topic="extract", max_attempts=work.MAX_ATTEMPTS + 1, retry_after=30)
async def extract(message: Message[dict[str, object]]) -> None:
    await asyncio.to_thread(work.extract_job, message.payload, message.metadata.delivery_count)
