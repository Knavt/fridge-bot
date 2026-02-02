import os
import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.environ["BOT_TOKEN"]
TZ = ZoneInfo(os.environ.get("TZ", "Europe/Amsterdam").strip())

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = "fridge.db"

KIND_LABEL = {"meal": "Готовые блюда", "ingredient": "Ингредиенты"}
PLACE_LABEL = {"fridge": "Холодильник", "kitchen": "Кухня", "freezer": "Морозилка"}

# ================= DATABASE =================
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


def db_list(kind, place):
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT id, text FROM items WHERE kind=%s AND place=%s ORDER BY id",
                    (kind, place),
                )
                return cur.fetchall()
    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute(
            "SELECT id, text FROM items WHERE kind=? AND place=? ORDER BY id",
            (kind, place),
        )
        return cur.fetchall()


def db_list_all():
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute("SELECT id, kind, place, text FROM items ORDER BY id")
                return cur.fetchall()
    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute("SELECT id, kind, place, text FROM items ORDER BY id")
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


# ================= AI =================
AI_PROMPT = """
Ты помощник телеграм-бота учета еды.

Верни ТОЛЬКО JSON.

action:
- add
- delete
- unknown

kind: meal | ingredient
place: fridge | kitchen | freezer

items: список названий

Если не уверен — action=unknown.
"""

def ai_parse(text: str) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"action": "unknown"}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        r = client.chat.completions.create(
            model="gpt-5-nano",
            messages=[
                {"role": "system", "content": AI_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
        )
        return json.loads(r.choices[0].message.content.strip())
    except Exception:
        return {"action": "unknown"}


# ================= UI =================
def kb_main():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Добавить", callback_data="add"),
            InlineKeyboardButton("➖ Удалить", callback_data="del"),
        ],
        [
            InlineKeyboardButton("❓ Что осталось?", callback_data="show"),
            InlineKeyboardButton("🏠 Меню", callback_data="menu"),
        ],
    ])


def kb_kind(action):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🍲 Готовые блюда", callback_data=f"{action}:meal"),
            InlineKeyboardButton("🥕 Ингредиенты", callback_data=f"{action}:ingredient"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="menu")],
    ])


def kb_place(action, kind):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧊 Холодильник", callback_data=f"{action}:{kind}:fridge"),
            InlineKeyboardButton("🏠 Кухня", callback_data=f"{action}:{kind}:kitchen"),
        ],
        [
            InlineKeyboardButton("❄️ Морозилка", callback_data=f"{action}:{kind}:freezer"),
            InlineKeyboardButton("⬅️ Назад", callback_data=f"{action}:back"),
        ],
    ])


# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Главное меню:", reply_markup=kb_main())


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "menu":
        context.user_data.clear()
        await q.edit_message_text("Главное меню:", reply_markup=kb_main())
        return

    if data in ("add", "del"):
        context.user_data["act"] = data
        await q.edit_message_text("Выбери категорию:", reply_markup=kb_kind(data))
        return

    if data.endswith(":back"):
        act = context.user_data.get("act")
        await q.edit_message_text("Выбери категорию:", reply_markup=kb_kind(act))
        return

    if data.count(":") == 1:
        act, kind = data.split(":")
        context.user_data["kind"] = kind
        await q.edit_message_text("Выбери место:", reply_markup=kb_place(act, kind))
        return

    if data.count(":") == 2:
        act, kind, place = data.split(":")
        context.user_data.update({"kind": kind, "place": place})

        if act == "add":
            await q.edit_message_text(
                "Напиши названия.\nМожно несколько строк.",
                reply_markup=kb_main(),
            )
            return

        if act == "del":
            rows = db_list(kind, place)
            context.user_data["rows"] = rows
            if not rows:
                await q.edit_message_text("Пусто.", reply_markup=kb_main())
                return

            msg = "\n".join([f"{i+1}. {t}" for i, (_, t) in enumerate(rows)])
            await q.edit_message_text(
                f"Отправь номер(а) для удаления:\n\n{msg}",
                reply_markup=kb_main(),
            )
            return

    if data == "show":
        rows = db_list_all()
        if not rows:
            await q.edit_message_text("Пусто.", reply_markup=kb_main())
            return

        out = []
        for i, (_, kind, place, text) in enumerate(rows, start=1):
            out.append(f"{i}. {text} ({KIND_LABEL[kind]} / {PLACE_LABEL[place]})")

        await q.edit_message_text("\n".join(out), reply_markup=kb_main())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # === DELETE BY NUMBERS ===
    if context.user_data.get("act") == "del" and text.replace(",", " ").replace(" ", "").isdigit():
        nums = sorted(set(int(n) for n in text.replace(",", " ").split()))
        rows = context.user_data.get("rows", [])
        for n in reversed(nums):
            if 1 <= n <= len(rows):
                db_delete(rows[n - 1][0])
        await update.message.reply_text("Удалил ✅", reply_markup=kb_main())
        context.user_data.clear()
        return

    # === ADD MODE ===
    if context.user_data.get("act") == "add":
        kind = context.user_data["kind"]
        place = context.user_data["place"]
        for line in text.splitlines():
            if line.strip():
                db_add(kind, place, line.strip())
        await update.message.reply_text("Добавил ✅", reply_markup=kb_main())
        context.user_data.clear()
        return

    # === AI (ONLY WHEN NOT IN MENU FLOW) ===
    ai = ai_parse(text)
    if ai.get("action") in ("add", "delete"):
        items = ai.get("items", [])
        if ai["action"] == "add":
            kind = ai.get("kind", "ingredient")
            place = ai.get("place", "fridge")
            for i in items:
                db_add(kind, place, i)
            await update.message.reply_text("🤖 Добавил по описанию", reply_markup=kb_main())
            return

        if ai["action"] == "delete":
            names = [n.lower() for n in items]
            rows = db_list_all()
            for item_id, _, _, text in rows:
                if text.lower() in names:
                    db_delete(item_id)
            await update.message.reply_text("🤖 Удалил по описанию", reply_markup=kb_main())
            return

    await update.message.reply_text("Не понял. Используй кнопки 👇", reply_markup=kb_main())


# ================= MAIN =================
def main():
    db_init()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()


if __name__ == "__main__":
    main()
