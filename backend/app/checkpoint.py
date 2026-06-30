"""Checkpointer factory: durable Postgres when DATABASE_URL is set, else in-memory.

The Postgres saver MUST be owned by a long-lived connection pool created on the
serving event loop (FastAPI lifespan) — never per-request `async with` (that closes
the connection). The in-memory fallback keeps a cold clone runnable with no Postgres.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from langgraph.checkpoint.memory import InMemorySaver


def memory_checkpointer() -> InMemorySaver:
    return InMemorySaver()


@asynccontextmanager
async def postgres_checkpointer(db_uri: str):
    """Async-context-managed AsyncPostgresSaver backed by a connection pool.

    Usage (in FastAPI lifespan):
        async with postgres_checkpointer(uri) as saver:
            graph = build_graph(..., checkpointer=saver)
            yield
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        conninfo=db_uri,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()  # creates checkpoint tables once (needs autocommit)
        yield saver
    finally:
        await pool.close()
