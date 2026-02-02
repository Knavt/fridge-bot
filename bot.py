import os
import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== CONFIG ==================
BOT_TOKEN = os.environ["BOT_TOKEN"]

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Amsterdam").strip())

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = "fridge.db"

KIND_LABEL = {"meal": "Готовые блюда", "ingredient": "Ингредиенты"}
PLACE_LABEL = {"fridge": "Холодильник", "kitchen": "Кухня", "freezer": "Морозилка"}

# ================== DATABASE ==================
PG_POOL = None
if DATABASE_URL:
    from psycopg_pool import ConnectionPool
    PG_POOL = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, timeout=10)


def db_init():
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS items (
                        id BIGSERIAL PRIMARY KEY,
                        kind TEXT,
                        place TEXT,
                        text TEXT,
                        created_at TIMESTAMPTZ
                    )
                """)
            con.commit()
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT,
                    place TEXT,
                    text TEXT,
                    created_at TEXT
                )
            """)
            con.commit()


def db_add(kind, place, text):
    now = datetime.now(tz=TZ)
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
                (kind, place, text, now.isoformat()),
            )
            con.commit()


def db_all():
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute("SELECT id, kind, place, text FROM items")
                return cur.fetchall()
    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute("SELECT id, kind, place, text FROM items")
        return cur.fetchall()


def db_delete(item_id):
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute("DELETE FROM items WHERE id=%s", (item_id,))
            con.commit()
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute("DELETE FROM items WHERE id=?", (item_id,))
            con.commit()


# ================== AI (SAFE) ==================
AI_SYSTEM_PROMPT = """
Ты помощник телеграм-бота для учета еды.

Верни ТОЛЬКО JSON.
Без пояснений.

action:
- add
- delete
- unknown

kind: meal | ingredient
place: fridge | kitchen | freezer
"""

def ai_parse_text(text: str) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"action": "unknown"}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        resp = client.chat.completions.create(
            model="gpt-5-nano",
            messages=[
                {"role": "system", "content": AI_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
        )

        return json.loads(resp.choices[0].message.content.strip())
    except Exception as e:
        print("AI error:", e)
        return {"action": "unknown"}


# ================== UI ==================
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить", callback_data="noop")],
        [InlineKeyboardButton("➖ Удалить", callback_data="noop")],
        [InlineKeyboardButton("❓ Что осталось?", callback_data="show")],
    ])


# ================== HANDLERS ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Главное меню:", reply_markup=kb_main())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    ai = ai_parse_text(text)

    if ai.get("action") == "add":
        kind = ai.get("kind", "ingredient")
        place = ai.get("place", "fridge")
        items = ai.get("items", [])

        for item in items:
            db_add(kind, place, item)

        await update.message.reply_text(
            f"🤖 Добавил {len(items)} шт.\n{KIND_LABEL[kind]} → {PLACE_LABEL[place]}"
        )
        return

    if ai.get("action") == "delete":
        names = [n.lower() for n in ai.get("items", [])]
        rows = db_all()
        deleted = 0

        for item_id, _kind, _place, text in rows:
            if text.lower() in names:
                db_delete(item_id)
                deleted += 1

        await update.message.reply_text(f"🤖 Удалил {deleted} шт.")
        return

    await update.message.reply_text("Не понял. Используй кнопки 👇", reply_markup=kb_main())


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "show":
        rows = db_all()
        if not rows:
            await q.edit_message_text("Пусто")
            return

        out = []
        for i, (_, kind, place, text) in enumerate(rows, start=1):
            out.append(f"{i}. {text} ({KIND_LABEL[kind]} / {PLACE_LABEL[place]})")

        await q.edit_message_text("\n".join(out))


# ================== MAIN ==================
def main():
    print("OPENAI_API_KEY present:", bool(os.environ.get("OPENAI_API_KEY")))
    db_init()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
