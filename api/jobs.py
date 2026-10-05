"""
jobs.py - start background work (work.py) without waiting for it.

On Vercel (VERCEL=1, set by Vercel): a message to Vercel Queues, picked up by workers.py in a function of its own.
Locally: a thread, like FastAPI's BackgroundTasks. In the tests: right away, so they can check the result.
"""
import os
import threading

from api import work

INLINE = False  # the tests set this


async def enqueue(topic: str, payload: dict):
    if os.environ.get("VERCEL"):
        from vercel.queue import send  # only on Vercel
        await send(topic, payload)
    elif INLINE:
        work.HANDLERS[topic](payload)
    else:
        threading.Thread(target=work.HANDLERS[topic], args=(payload,), daemon=True).start()
