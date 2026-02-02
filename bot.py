import os
import json
import base64
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import List, Tuple, Dict, Any

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

VALID_KINDS = ("meal", "ingredient")
VALID_PLACES = ("fridge", "kitchen", "freezer")

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
    text = text.strip()
    if not text:
        return

    if kind not in VALID_KINDS:
        kind = "ingredient"
    if place not in VALID_PLACES:
        place = "fridge"

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


def db_list(kind: str, place: str) -> List[Tuple[int, str]]:
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT id, text FROM items WHERE kind=%s AND place=%s ORDER BY id",
                    (kind, place),
                )
                return [(int(a), str(b)) for a, b in cur.fetchall()]
    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute(
            "SELECT id, text FROM items WHERE kind=? AND place=? ORDER BY id",
            (kind, place),
        )
        return [(int(a), str(b)) for a, b in cur.fetchall()]


def db_list_all(kind: str) -> Dict[str, List[Tuple[int, str]]]:
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

    result = {p: [] for p in VALID_PLACES}
    for place, item_id, text in rows:
        p = str(place)
        if p not in result:
            continue
        result[p].append((int(item_id), str(text)))
    return result


def db_all_raw() -> List[Tuple[int, str, str, str]]:
    """Returns (id, kind, place, text)"""
    if PG_POOL:
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute("SELECT id, kind, place, text FROM items ORDER BY id")
                return [(int(a), str(b), str(c), str(d)) for a, b, c, d in cur.fetchall()]
    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute("SELECT id, kind, place, text FROM items ORDER BY id")
        return [(int(a), str(b), str(c), str(d)) for a, b, c, d in cur.fetchall()]


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


# ================= HELPERS =================
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_rows(rows: List[Tuple[int, str]]) -> str:
    if not rows:
        return "— (пусто)"
    out = []
    for i, (_id, text) in enumerate(rows, start=1):
        out.append(f"<b>{i}.</b> {esc(text)}")
    return "\n".join(out)


def parse_add_lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def parse_delete_nums(text: str) -> List[int]:
    cleaned = text.replace(",", " ").replace(";", " ")
    parts = [p.strip() for p in cleaned.split() if p.strip()]
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
    return sorted(set(nums))


def norm(s: str) -> str:
    return " ".join(s.lower().strip().split())


def find_matches(rows: List[Tuple[int, str, str, str]], query: str) -> List[Tuple[int, str]]:
    """
    rows: (id, kind, place, text)
    query: e.g. "суп"
    returns list of (id, text)
    """
    q = norm(query)
    if not q:
        return []

    exact = [(item_id, t) for (item_id, _k, _p, t) in rows if norm(t) == q]
    if exact:
        return exact

    subs = []
    for (item_id, _k, _p, t) in rows:
        tt = norm(t)
        if q in tt or tt in q:
            subs.append((item_id, t))
    return subs


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


def kb_confirm_photo():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data="photo:confirm"),
            InlineKeyboardButton("❌ Отмена", callback_data="photo:cancel"),
        ],
        [InlineKeyboardButton("🏠 Меню", callback_data="nav:main")],
    ])


# ================= AI (TEXT + PHOTO) =================
AI_TEXT_PROMPT = """
Ты помощник телеграм-бота учета еды.

Нужно понять намерение пользователя и вернуть ТОЛЬКО валидный JSON (без markdown).

Поля:
- action: "add" | "delete" | "unknown"
- kind: "meal" | "ingredient"
- place: "fridge" | "kitchen" | "freezer"
- items: массив строк

Синонимы места:
- "холодос", "холодильник" -> fridge
- "морозилка", "заморозка" -> freezer
- "кухня" -> kitchen

Если место не указано -> place="fridge"

Если есть явное действие ("добавь"/"положи"/"купили"/"закинь") -> action="add"
Если ("съели"/"удали"/"убери"/"кончилось"/"нет") -> action="delete"
Если есть явное действие — НЕ возвращай unknown.

Если неясно блюдо или ингредиент:
- суп/борщ/рагу/голубцы/плов/котлеты -> meal
- молоко/яйца/сыр/курица/масло/овощи -> ingredient
Если сомневаешься -> ingredient.
"""

AI_PHOTO_PROMPT = """
Ты смотришь на фото и определяешь, какие продукты/блюда на нём видны.

Верни ТОЛЬКО валидный JSON (без markdown).
Формат:
{
  "action": "add",
  "kind": "ingredient" | "meal",
  "place": "fridge" | "kitchen" | "freezer",
  "items": ["название1", "название2", ...]
}

Правила:
- action всегда "add"
- kind по умолчанию "ingredient", если похоже на готовое блюдо (кастрюля супа/контейнер с рагу) -> "meal"
- place по умолчанию "fridge"
- items: короткие русские названия, без брендов, без лишних слов
- если ничего не распознал уверенно -> items=[]
"""


def openai_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    from openai import OpenAI
    return OpenAI(api_key=api_key)


def ai_parse_text(text: str) -> Dict[str, Any]:
    client = openai_client()
    if client is None:
        return {"action": "unknown"}

    try:
        resp = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": AI_TEXT_PROMPT},
                {"role": "user", "content": text},
            ],
            max_output_tokens=250,
        )
        raw = (resp.output_text or "").strip()
        print("AI text raw:", raw)
        if not raw:
            return {"action": "unknown"}
        return json.loads(raw)
    except Exception as e:
        print("AI text error:", e)
        return {"action": "unknown"}


async def ai_parse_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Dict[str, Any]:
    """
    Downloads the biggest photo, sends to OpenAI vision, returns parsed JSON dict.
    """
    client = openai_client()
    if client is None:
        return {"action": "add", "kind": "ingredient", "place": "fridge", "items": []}

    try:
        if not update.message or not update.message.photo:
            return {"action": "add", "kind": "ingredient", "place": "fridge", "items": []}

        photo = update.message.photo[-1]  # highest resolution
        file = await context.bot.get_file(photo.file_id)
        data_bytes = await file.download_as_bytearray()

        b64 = base64.b64encode(bytes(data_bytes)).decode("ascii")
        data_url = f"data:image/jpeg;base64,{b64}"

        resp = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": AI_PHOTO_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Что на фото? Верни JSON."},
                        {"type": "input_image", "image_url": data_url},
                    ],
                },
            ],
            max_output_tokens=300,
        )

        raw = (resp.output_text or "").strip()
        print("AI photo raw:", raw)
        if not raw:
            return {"action": "add", "kind": "ingredient", "place": "fridge", "items": []}
        return json.loads(raw)

    except Exception as e:
        print("AI photo error:", e)
        return {"action": "add", "kind": "ingredient", "place": "fridge", "items": []}


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Главное меню:", reply_markup=kb_main())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Ок, отмена. Главное меню:", reply_markup=kb_main())


async def env_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    present = bool(os.environ.get("OPENAI_API_KEY"))
    await update.message.reply_text(f"OPENAI_API_KEY present: {present}")


async def ai_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = ai_parse_text("Добавь молоко и яйца в холодильник")
    await update.message.reply_text(f"AI_TEST: {res}")


# ================= CALLBACKS =================
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    # global nav
    if data == "nav:main":
        context.user_data.clear()
        await q.edit_message_text("Главное меню:", reply_markup=kb_main())
        return

    # photo confirm/cancel
    if data == "photo:cancel":
        context.user_data.pop("pending_photo", None)
        await q.edit_message_text("Ок, отменил. Главное меню:", reply_markup=kb_main())
        return

    if data == "photo:confirm":
        pending = context.user_data.get("pending_photo")
        if not pending:
            await q.edit_message_text("Нечего подтверждать. Главное меню:", reply_markup=kb_main())
            return

        kind = pending.get("kind", "ingredient")
        place = pending.get("place", "fridge")
        items = pending.get("items", [])
        if kind not in VALID_KINDS:
            kind = "ingredient"
        if place not in VALID_PLACES:
            place = "fridge"
        if not isinstance(items, list):
            items = []

        added = 0
        for it in items:
            if isinstance(it, str) and it.strip():
                db_add(kind, place, it.strip())
                added += 1

        context.user_data.pop("pending_photo", None)
        await q.edit_message_text(f"Добавил ✅ {added} шт. ({KIND_LABEL[kind]} → {PLACE_LABEL[place]})", reply_markup=kb_main())
        return

    # enter actions
    if data.startswith("act:"):
        act = data.split(":", 1)[1]  # add / del / show
        context.user_data.clear()
        context.user_data["act"] = act
        await q.edit_message_text("Выбери категорию:", reply_markup=kb_kind(act))
        return

    if data.endswith(":back_kind"):
        act = data.split(":")[0]
        await q.edit_message_text("Выбери категорию:", reply_markup=kb_kind(act))
        return

    # choose kind
    if ":kind:" in data:
        act, _kw, kind = data.split(":")
        context.user_data["act"] = act
        context.user_data["kind"] = kind

        if act in ("add", "del"):
            await q.edit_message_text("Выбери место:", reply_markup=kb_place(act, kind))
            return

        if act == "show":
            allp = db_list_all(kind)
            blocks = []
            for place in VALID_PLACES:
                blocks.append(f"<b>{PLACE_LABEL[place]}</b>\n{fmt_rows(allp[place])}")
            text = f"Остатки: <b>{KIND_LABEL[kind]}</b>\n\n" + "\n\n".join(blocks)
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
            return

    # choose place
    if ":place:" in data:
        act, _pkw, kind, place = data.split(":")
        context.user_data["act"] = act
        context.user_data["kind"] = kind
        context.user_data["place"] = place

        if act == "add":
            await q.edit_message_text(
                f"Добавление: <b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
                "Напиши названия одним сообщением.\n"
                "Можно несколько строк:\nСуп\nРагу\n\n"
                "Либо пришли фото (я предложу список и попрошу подтвердить).",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_main(),
            )
            return

        if act == "del":
            rows = db_list(kind, place)
            context.user_data["del_rows"] = rows
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


# ================= TEXT HANDLER =================
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text or ""
    text = raw.strip()

    # 1) ADD flow (manual) — multi-line
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

    # 2) DEL flow (manual) — numbers
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

        # refresh snapshot
        kind = context.user_data.get("kind")
        place = context.user_data.get("place")
        context.user_data["del_rows"] = db_list(kind, place)

        await update.message.reply_text(f"Удалил ✅ {len(valid)} шт.", reply_markup=kb_main())
        return

    # 3) Free-text AI
    ai = ai_parse_text(text)
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

        kind = kind if kind in VALID_KINDS else "ingredient"
        place = place if place in VALID_PLACES else "fridge"

        added = 0
        for i in items:
            if isinstance(i, str) and i.strip():
                db_add(kind, place, i.strip())
                added += 1

        await update.message.reply_text(
            f"🤖 Добавил {added} шт.\n{KIND_LABEL[kind]} → {PLACE_LABEL[place]}",
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

        queries = [str(x).strip() for x in items if str(x).strip()]
        if not queries:
            await update.message.reply_text("Не понял, что удалить. Используй кнопки 👇", reply_markup=kb_main())
            return

        rows = db_all_raw()

        # Apply optional hints (if model provided)
        place_hint = ai.get("place")
        kind_hint = ai.get("kind")

        if place_hint in VALID_PLACES:
            rows = [r for r in rows if r[2] == place_hint]
        if kind_hint in VALID_KINDS:
            rows = [r for r in rows if r[1] == kind_hint]

        deleted = 0
        ambiguous = []

        for q in queries:
            matches = find_matches(rows, q)

            if len(matches) == 1:
                db_delete(int(matches[0][0]))
                deleted += 1
            elif len(matches) > 1:
                ambiguous.append((q, matches))

        if ambiguous:
            msg = ["Часть позиций не удалил — нужно уточнить:"]
            for q, matches in ambiguous:
                msg.append(f"\n• «{esc(q)}» подходит к нескольким:")
                for i, (_id, t) in enumerate(matches[:10], start=1):
                    msg.append(f"  {i}) {esc(t)}")
            msg.append("\nНапиши точнее (например: «удали рыбный суп»).")
            await update.message.reply_text("\n".join(msg), parse_mode=ParseMode.HTML, reply_markup=kb_main())
            return

        await update.message.reply_text(f"🤖 Удалил {deleted} шт.", reply_markup=kb_main())
        return

    await update.message.reply_text("Не понял. Используй кнопки 👇", reply_markup=kb_main())


# ================= PHOTO HANDLER =================
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Photo recognition:
    - parse photo with AI
    - show a confirmation message
    - only after confirm -> add to DB
    """
    # If user is in delete-by-numbers flow, ignore photo
    if context.user_data.get("act") == "del" and "del_rows" in context.user_data:
        await update.message.reply_text("Сейчас режим удаления. Нажми /cancel или Меню, потом пришли фото.", reply_markup=kb_main())
        return

    # If user is in manual add flow (picked kind/place), we can still propose with those hints
    hint_kind = context.user_data.get("kind") if context.user_data.get("act") == "add" else None
    hint_place = context.user_data.get("place") if context.user_data.get("act") == "add" else None

    parsed = await ai_parse_photo(update, context)

    kind = parsed.get("kind", "ingredient")
    place = parsed.get("place", "fridge")
    items = parsed.get("items", [])

    if hint_kind in VALID_KINDS:
        kind = hint_kind
    if hint_place in VALID_PLACES:
        place = hint_place

    if kind not in VALID_KINDS:
        kind = "ingredient"
    if place not in VALID_PLACES:
        place = "fridge"
    if not isinstance(items, list):
        items = []

    items = [str(x).strip() for x in items if str(x).strip()]
    if not items:
        await update.message.reply_text("По фото не смог уверенно распознать продукты. Попробуй другое фото или добавь текстом/кнопками.", reply_markup=kb_main())
        return

    # Store pending action for confirmation
    context.user_data["pending_photo"] = {"kind": kind, "place": place, "items": items}

    preview = "\n".join([f"• {esc(x)}" for x in items[:30]])
    if len(items) > 30:
        preview += "\n• …"

    msg = (
        f"Я распознал на фото и предлагаю добавить:\n\n"
        f"<b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
        f"{preview}\n\n"
        f"Подтвердить?"
    )

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb_confirm_photo())


# ================= ERRORS =================
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("ERROR:", context.error)


# ================= MAIN =================
def main():
    print("OPENAI_API_KEY present:", bool(os.environ.get("OPENAI_API_KEY")))
    db_init()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("env", env_cmd))
    app.add_handler(CommandHandler("ai_test", ai_test))

    app.add_handler(CallbackQueryHandler(on_button))

    # photo handler must be before text handler so photos don't fall into text fallback
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.add_error_handler(on_error)

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
