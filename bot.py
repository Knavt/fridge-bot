import os
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

# ---- Token loading (Railway env first, then local .env if exists) ----
def get_bot_token() -> str:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if token:
        return token
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
        token = os.environ.get("BOT_TOKEN", "").strip()
        if token:
            return token
    except Exception:
        pass
    raise RuntimeError("BOT_TOKEN not found in env (Railway Variables) or local .env")

BOT_TOKEN = get_bot_token()

DB_PATH = os.environ.get("DB_PATH", "fridge.db")
TZ_NAME = os.environ.get("TZ", "Europe/Amsterdam")
TZ = ZoneInfo(TZ_NAME)

KIND_LABEL = {"meal": "Готовые блюда", "ingredient": "Ингредиенты"}
PLACE_LABEL = {"fridge": "Холодильник", "kitchen": "Кухня", "freezer": "Морозилка"}


# ---------------- DB ----------------
def db_init() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                place TEXT NOT NULL,
                text TEXT NOT NULL,
                created_by INTEGER,
                created_at TEXT NOT NULL
            )
        """)
        con.commit()


def db_add(kind: str, place: str, text: str, user_id: int | None) -> int:
    created_at = datetime.now(tz=TZ).isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "INSERT INTO items(kind, place, text, created_by, created_at) VALUES(?,?,?,?,?)",
            (kind, place, text, user_id, created_at),
        )
        con.commit()
        return cur.lastrowid


def db_list(kind: str, place: str) -> list[tuple[int, str, str]]:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "SELECT id, text, created_at FROM items WHERE kind=? AND place=? ORDER BY id ASC",
            (kind, place),
        )
        return cur.fetchall()


def db_delete(item_id: int) -> bool:
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute("DELETE FROM items WHERE id=?", (item_id,))
        con.commit()
        return cur.rowcount > 0


# -------------- UI helpers --------------
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_rows(rows: list[tuple[int, str, str]]) -> str:
    if not rows:
        return "— (пусто)"
    out = []
    for idx, (item_id, text, _created_at) in enumerate(rows, start=1):
        out.append(f"<b>{idx}.</b> {esc(text)}  <i>(id:{item_id})</i>")
    return "\n".join(out)


def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить", callback_data="act:add")],
        [InlineKeyboardButton("➖ Удалить", callback_data="act:del")],
        [InlineKeyboardButton("❓ Что осталось?", callback_data="act:show")],
    ])


def kb_kind(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍲 Готовые блюда", callback_data=f"{action}:kind:meal")],
        [InlineKeyboardButton("🥕 Ингредиенты", callback_data=f"{action}:kind:ingredient")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="nav:main")],
    ])


def kb_place(action: str, kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧊 Холодильник", callback_data=f"{action}:place:{kind}:fridge")],
        [InlineKeyboardButton("🏠 Кухня", callback_data=f"{action}:place:{kind}:kitchen")],
        [InlineKeyboardButton("❄️ Морозилка", callback_data=f"{action}:place:{kind}:freezer")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"{action}:back_kind")],
    ])


def kb_del_buttons(rows: list[tuple[int, str, str]], kind: str, place: str) -> InlineKeyboardMarkup:
    kb = []
    for idx, (item_id, _text, _created_at) in enumerate(rows, start=1):
        kb.append([InlineKeyboardButton(f"Удалить {idx}", callback_data=f"del:do:{kind}:{place}:{item_id}")])
    kb.append([InlineKeyboardButton("⬅️ Назад", callback_data="nav:main")])
    return InlineKeyboardMarkup(kb)


# ---------------- Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text("Выбери действие:", reply_markup=kb_main())


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "nav:main":
        context.user_data.clear()
        await q.edit_message_text("Выбери действие:", reply_markup=kb_main())
        return

    if data.startswith("act:"):
        act = data.split(":", 1)[1]  # add/del/show
        context.user_data.clear()
        context.user_data["act"] = act
        await q.edit_message_text("Выбери категорию:", reply_markup=kb_kind(act))
        return

    if data.endswith(":back_kind"):
        act = data.split(":")[0]
        await q.edit_message_text("Выбери категорию:", reply_markup=kb_kind(act))
        return

    # category selection
    if ":kind:" in data:
        act, _kw, kind = data.split(":")  # add:kind:meal
        context.user_data["act"] = act
        context.user_data["kind"] = kind

        if act in ("add", "del"):
            await q.edit_message_text("Выбери место:", reply_markup=kb_place(act, kind))
        elif act == "show":
            # show all places for this kind
            blocks = []
            for place in ("fridge", "kitchen", "freezer"):
                rows = db_list(kind, place)
                blocks.append(f"<b>{PLACE_LABEL[place]}</b>\n{fmt_rows(rows)}")
            text = f"Остатки: <b>{KIND_LABEL[kind]}</b>\n\n" + "\n\n".join(blocks)
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
        return

    # place selection
    if ":place:" in data:
        act, _place_kw, kind, place = data.split(":")  # add:place:meal:fridge
        context.user_data["act"] = act
        context.user_data["kind"] = kind
        context.user_data["place"] = place

        if act == "add":
            await q.edit_message_text(
                f"Добавление:\n<b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
                "Теперь напиши название одним сообщением (например: Рыбный суп).",
                parse_mode=ParseMode.HTML,
            )
            return

        if act == "del":
            rows = db_list(kind, place)
            context.user_data["del_rows"] = rows
            msg = (
                f"Удаление:\n<b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
                f"{fmt_rows(rows)}\n\n"
                "Нажми кнопку удаления или отправь номер строкой (например: 2)."
            )
            await q.edit_message_text(
                msg,
                parse_mode=ParseMode.HTML,
                reply_markup=kb_del_buttons(rows, kind, place) if rows else kb_main(),
            )
            return

    # delete by button
    if data.startswith("del:do:"):
        _del, _do, kind, place, item_id_s = data.split(":")
        item_id = int(item_id_s)
        db_delete(item_id)

        rows = db_list(kind, place)
        context.user_data["del_rows"] = rows

        msg = (
            f"Ок.\n<b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
            f"{fmt_rows(rows)}\n\n"
            "Можно продолжать удалять."
        )
        await q.edit_message_text(
            msg,
            parse_mode=ParseMode.HTML,
            reply_markup=kb_del_buttons(rows, kind, place) if rows else kb_main(),
        )
        return

    await q.edit_message_text("Не понял кнопку. Вернёмся в меню.", reply_markup=kb_main())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    # ADD flow: waiting for text after picking kind+place
    if context.user_data.get("act") == "add" and context.user_data.get("kind") and context.user_data.get("place"):
        kind = context.user_data["kind"]
        place = context.user_data["place"]
        uid = update.effective_user.id if update.effective_user else None

        item_id = db_add(kind, place, text, uid)
        context.user_data.clear()

        await update.message.reply_text(
            f"Добавил ✅\n<b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n<i>id:{item_id}</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_main(),
        )
        return

    # DEL flow: allow deleting by numeric index
    if context.user_data.get("act") == "del" and "del_rows" in context.user_data:
        if text.isdigit():
            n = int(text)
            rows = context.user_data.get("del_rows", [])
            if 1 <= n <= len(rows):
                item_id = rows[n - 1][0]
                db_delete(item_id)

                kind = context.user_data.get("kind")
                place = context.user_data.get("place")
                new_rows = db_list(kind, place)
                context.user_data["del_rows"] = new_rows

                await update.message.reply_text(
                    f"Удалил ✅\n<b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n{fmt_rows(new_rows)}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb_del_buttons(new_rows, kind, place) if new_rows else kb_main(),
                )
                return

        await update.message.reply_text("Для удаления отправь номер строки (например: 2) или используй кнопки.")
        return

    await update.message.reply_text("Выбери действие:", reply_markup=kb_main())


def main() -> None:
    db_init()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
