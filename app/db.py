# app/db.py
import sqlite3
from datetime import datetime
from typing import List, Tuple, Dict, Union

from app.config import (
    DATABASE_URL,
    SQLITE_PATH,
    TZ,
    VALID_PLACES,
)

# Optional Postgres pool
PG_POOL = None
if DATABASE_URL:
    from psycopg_pool import ConnectionPool
    PG_POOL = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, timeout=10)


def db_init() -> None:
    """Create table if not exists."""
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS items (
                        id BIGSERIAL PRIMARY KEY,
                        kind TEXT NOT NULL,
                        place TEXT NOT NULL,
                        text TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            con.commit()
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    place TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            con.commit()


def db_add(kind: str, place: str, text: str) -> None:
    now = datetime.now(tz=TZ)
    text = (text or "").strip()
    if not text:
        return

    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "INSERT INTO items(kind, place, text, created_at) VALUES (%s,%s,%s,%s)",
                    (kind, place, text, now),
                )
            con.commit()
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute(
                "INSERT INTO items(kind, place, text, created_at) VALUES (?,?,?,?)",
                (kind, place, text, now.isoformat(timespec="seconds")),
            )
            con.commit()


DbDateValue = Union[str, datetime]


def db_list(kind: str, place: str) -> List[Tuple[int, str, DbDateValue]]:
    """Rows for one (kind, place) ordered by created_at."""
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT id, text, created_at FROM items WHERE kind=%s AND place=%s "
                    "ORDER BY created_at ASC, id ASC",
                    (kind, place),
                )
                return [(int(a), str(b), c) for a, b, c in cur.fetchall()]

    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute(
            "SELECT id, text, created_at FROM items WHERE kind=? AND place=? "
            "ORDER BY created_at ASC, id ASC",
            (kind, place),
        )
        return [(int(a), str(b), str(c)) for a, b, c in cur.fetchall()]


def db_list_all(kind: str) -> Dict[str, List[Tuple[int, str, DbDateValue]]]:
    """All rows for kind grouped by place."""
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT place, id, text, created_at FROM items WHERE kind=%s "
                    "ORDER BY place ASC, created_at ASC, id ASC",
                    (kind,),
                )
                rows = cur.fetchall()
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            cur = con.execute(
                "SELECT place, id, text, created_at FROM items WHERE kind=? "
                "ORDER BY place ASC, created_at ASC, id ASC",
                (kind,),
            )
            rows = cur.fetchall()

    out: Dict[str, List[Tuple[int, str, DbDateValue]]] = {p: [] for p in VALID_PLACES}
    for place, item_id, text, created_at in rows:
        p = str(place)
        if p in out:
            out[p].append((int(item_id), str(text), created_at))
    return out


def db_all_raw() -> List[Tuple[int, str, str, str]]:
    """All rows for AI delete matching: (id, kind, place, text)."""
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute("SELECT id, kind, place, text FROM items ORDER BY id")
                return [(int(a), str(b), str(c), str(d)) for a, b, c, d in cur.fetchall()]

    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute("SELECT id, kind, place, text FROM items ORDER BY id")
        return [(int(a), str(b), str(c), str(d)) for a, b, c, d in cur.fetchall()]


def db_delete(item_id: int) -> None:
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute("DELETE FROM items WHERE id=%s", (item_id,))
            con.commit()
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute("DELETE FROM items WHERE id=?", (item_id,))
            con.commit()
