import os
import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

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
                        kind TEXT NOT NULL,
                        place TEXT NOT NULL,
                        text TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                """)
            con.commit()
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    place TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            con.commit()


def db_add(kind: str, place: str, text: str):
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
                (kind, place, text, now.isoformat(timespec="seconds")),
            )
            con.commit()


def db_list(kind: str, place: str):
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


def db_list_all(kind: str):
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT place, id, text FROM items WHERE kind=%s ORDER BY place ASC, id ASC",
                    (kind,),
                )
                rows = cur.fetchall()
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            cur = con.execute(
                "SELECT place, id, text FROM items WHERE kind=? ORDER BY place ASC, id ASC",
                (kind,),
            )
            rows = cur.fetchall()

    result = {p: [] for p in ("fridge", "kitchen", "freezer")}
    for place, item_id, text in rows:
        result[str(place)].append((int(item_id), str(text)))
    return result


def db_all_raw():
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute("SELECT id, kind, place, text FROM items ORDER BY id")
                return cur.fetchall()
    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute("SELECT id, kind, place, text FROM items ORDER BY id")
        return cur.fetchall()


def db_delete(item_id: int):
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute("DELETE FROM items WHERE id=%s", (item_id,))
            con.commit()
    else:
        with sqlite3.connect(SQLITE_PATH) as con:
            con.execute("DELETE FROM items WHERE id=?", (item_id,))
            con.commit()


# ================= AI (Responses API, GPT-5 nano) =================
AI_PROMPT = """
Ты помощник телеграм-бота учета еды.

Верни ТОЛЬКО JSON. Без текста вне JSON.

action: add | delete | unknown
kind: meal | ingredient
place: fridge | kitchen | freezer
items: список названий (строки)

Синонимы места:
- "холодос", "холодильник" -> fridge
- "морозилка" -> freezer
- "кухня" -> kitchen

Если место не указано -> fridge

Если есть явное действие ("добавь"/"положи"/"купили"/"закинь" или "съели"/"удали"/"убери"/"кончилось") — НЕ возвращай unknown.
"""

AI_SCHEMA = {
    "name": "fridge_action",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["add", "delete", "unknown"]},
            "kind": {"type": "string", "enum": ["meal", "ingredient"]},
            "place": {"type": "string", "enum": ["fridge", "kitchen", "freezer"]},
            "items": {"type": "array", "items": {"type": "string"}}
        },
        "required": ["action"]
    }
}

def ai_parse(text: str) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"action": "unknown"}

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        resp = client.responses.create(
            model="gpt-5-nano",
            input=[
                {
                    "role": "system",
                    "content": AI_PROMPT + "\n\n"
                    "Отвечай СТРОГО валидным JSON без markdown."
                },
                {"role": "user", "content": text},
            ],
            max_output_tokens=200,
        )

        raw = (resp.output_text or "").strip()
        print("AI raw:", raw)

        if not raw:
            return {"action": "unknown"}

        return json.loads(raw)

    except Exception as e:
        print("AI error:", e)
        return {"action": "unknown"}

# ================= Helpers =================
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_rows(rows):
    if not rows:
        return "— (пусто)"
    out = []
    for i, (_id, text) in enumerate(rows, start=1):
        out.append(f"<b>{i}.</b> {esc(text)}")
    return "\n".join(out)


def parse_add_lines(text: str):
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def parse_delete_nums(text: str):
    cleaned = text.replace(",", " ").replace(";", " ")
    parts = [p.strip() for p in cleaned.split() if p.strip()]
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
    return sorted(set(nums))


# ================= UI (2 columns) =================
def kb_main():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Добавить", callback_data="act:add"),
            InlineKeyboardButton("➖ Удалить", callback_data="act:del"),
        ],
        [
            InlineKeyboardButton("❓ Что осталось?", callback_data="act:show"),
            InlineKeyboardButton("🏠 Меню", callback_data="nav:main"),
        ],
    ])


def kb_kind(action: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🍲 Готовые блюда", callback_data=f"{action}:kind:meal"),
            InlineKeyboardButton("🥕 Ингредиенты", callback_data=f"{action}:kind:ingredient"),
        ],
        [InlineKeyboardButton("🏠 Меню", callback_data="nav:main")],
    ])


def kb_place(action: str, kind: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧊 Холодильник", callback_data=f"{action}:place:{kind}:fridge"),
            InlineKeyboardButton("🏠 Кухня", callback_data=f"{action}:place:{kind}:kitchen"),
        ],
        [
            InlineKeyboardButton("❄️ Морозилка", callback_data=f"{action}:place:{kind}:freezer"),
            InlineKeyboardButton("⬅️ Назад", callback_data=f"{action}:back_kind"),
        ],
        [InlineKeyboardButton("🏠 Меню", callback_data="nav:main")],
    ])


# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Главное меню:", reply_markup=kb_main())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Ок, отмена. Главное меню:", reply_markup=kb_main())


async def env_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # не показываем ключ, только факт наличия
    present = bool(os.environ.get("OPENAI_API_KEY"))
    await update.message.reply_text(f"OPENAI_API_KEY present: {present}")


async def ai_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = ai_parse("Добавь молоко и яйца в холодильник")
    await update.message.reply_text(f"AI_TEST: {res}")


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "nav:main":
        context.user_data.clear()
        await q.edit_message_text("Главное меню:", reply_markup=kb_main())
        return

    if data.startswith("act:"):
        act = data.split(":", 1)[1]
        context.user_data.clear()
        context.user_data["act"] = act
        await q.edit_message_text("Выбери категорию:", reply_markup=kb_kind(act))
        return

    if data.endswith(":back_kind"):
        act = data.split(":")[0]
        await q.edit_message_text("Выбери категорию:", reply_markup=kb_kind(act))
        return

    if ":kind:" in data:
        act, _kw, kind = data.split(":")
        context.user_data["act"] = act
        context.user_data["kind"] = kind

        if act in ("add", "del"):
            await q.edit_message_text("Выбери место:", reply_markup=kb_place(act, kind))
        elif act == "show":
            allp = db_list_all(kind)
            blocks = []
            for place in ("fridge", "kitchen", "freezer"):
                blocks.append(f"<b>{PLACE_LABEL[place]}</b>\n{fmt_rows(allp[place])}")
            text = f"Остатки: <b>{KIND_LABEL[kind]}</b>\n\n" + "\n\n".join(blocks)
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
        return

    if ":place:" in data:
        act, _place_kw, kind, place = data.split(":")
        context.user_data["act"] = act
        context.user_data["kind"] = kind
        context.user_data["place"] = place

        if act == "add":
            await q.edit_message_text(
                f"Добавление: <b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
                "Напиши названия одним сообщением.\nМожно несколько строк:\nСуп\nРагу",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_main(),
            )
            return

        if act == "del":
            rows = db_list(kind, place)
            context.user_data["del_rows"] = rows
            context.user_data["kind"] = kind
            context.user_data["place"] = place

            msg = (
                f"Удаление: <b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
                f"{fmt_rows(rows)}\n\n"
                "Отправь номер(а) строк для удаления.\n"
                "Примеры: <b>2</b> или <b>1 4</b> или <b>1, 4</b>\n"
                "/cancel — отмена."
            )
            await q.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb_main())
            return

    await q.edit_message_text("Не понял кнопку. Главное меню:", reply_markup=kb_main())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text or ""
    text = raw.strip()

    # ADD flow
    if context.user_data.get("act") == "add" and context.user_data.get("kind") and context.user_data.get("place"):
        kind = context.user_data["kind"]
        place = context.user_data["place"]
        items = parse_add_lines(raw)
        if not items:
            await update.message.reply_text("Пусто. Напиши хотя бы одну строку или /cancel.")
            return
        for t in items:
            db_add(kind, place, t)
        context.user_data.clear()
        await update.message.reply_text(f"Добавил ✅ {len(items)} шт.", reply_markup=kb_main())
        return

    # DEL flow
    if context.user_data.get("act") == "del" and "del_rows" in context.user_data:
        nums = parse_delete_nums(text)
        rows = context.user_data.get("del_rows", [])

        if not nums:
            await update.message.reply_text(
                "Для удаления отправь номер(а) строк.\nПримеры: 2 или 1 4 или 1, 4\n/cancel — отмена.",
                reply_markup=kb_main(),
            )
            return

        valid = [n for n in nums if 1 <= n <= len(rows)]
        if not valid:
            await update.message.reply_text(f"Сейчас доступно 1..{len(rows)}. Попробуй снова.", reply_markup=kb_main())
            return

        for n in sorted(valid, reverse=True):
            item_id = rows[n - 1][0]
            db_delete(item_id)

        kind = context.user_data.get("kind")
        place = context.user_data.get("place")
        context.user_data["del_rows"] = db_list(kind, place)

        await update.message.reply_text(f"Удалил ✅ {len(valid)} шт.", reply_markup=kb_main())
        return

    # Free text -> AI
    ai = ai_parse(text)
    action = ai.get("action", "unknown")

    if action == "add":
        kind = ai.get("kind", "ingredient")
        place = ai.get("place", "fridge")
        items = ai.get("items", [])

        if isinstance(items, str):
            items = [items]
        if not isinstance(items, list) or not items:
            await update.message.reply_text("Не понял, что добавить. Используй кнопки 👇", reply_markup=kb_main())
            return

        for i in items:
            if isinstance(i, str) and i.strip():
                db_add(kind, place, i.strip())

        await update.message.reply_text(
            f"🤖 Добавил {len(items)} шт.\n{KIND_LABEL.get(kind, kind)} → {PLACE_LABEL.get(place, place)}",
            reply_markup=kb_main(),
        )
        return

    if action == "delete":
        items = ai.get("items", [])
        if isinstance(items, str):
            items = [items]
        if not isinstance(items, list) or not items:
            await update.message.reply_text("Не понял, что удалить. Используй кнопки 👇", reply_markup=kb_main())
            return

        names = [str(x).strip().lower() for x in items if str(x).strip()]
        if not names:
            await update.message.reply_text("Не понял, что удалить. Используй кнопки 👇", reply_markup=kb_main())
            return

        rows = db_all_raw()
        deleted = 0
        for item_id, _kind, _place, t in rows:
            if str(t).strip().lower() in names:
                db_delete(int(item_id))
                deleted += 1

        await update.message.reply_text(f"🤖 Удалил {deleted} шт.", reply_markup=kb_main())
        return

    await update.message.reply_text("Не понял. Используй кнопки 👇", reply_markup=kb_main())


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("ERROR:", context.error)


def main():
    print("OPENAI_API_KEY present:", bool(os.environ.get("OPENAI_API_KEY")))
    db_init()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("env", env_cmd))
    app.add_handler(CommandHandler("ai_test", ai_test))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    # важно при частых рестартах
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
