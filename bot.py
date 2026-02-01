import os
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

# ---------------- Token loading (Railway env first, then local .env) ----------------
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

# ---------------- Timezone ----------------
TZ_NAME = os.environ.get("TZ", "Europe/Amsterdam").strip()
TZ = ZoneInfo(TZ_NAME)

# ---------------- Database config ----------------
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()  # set on Railway when Postgres is attached
SQLITE_PATH = os.environ.get("DB_PATH", "fridge.db")       # local fallback

# Postgres connection pool (fast!)
PG_POOL = None
if DATABASE_URL:
    from psycopg_pool import ConnectionPool  # type: ignore
    PG_POOL = ConnectionPool(conninfo=DATABASE_URL, min_size=1, max_size=5, timeout=10)

KIND_LABEL = {"meal": "Готовые блюда", "ingredient": "Ингредиенты"}
PLACE_LABEL = {"fridge": "Холодильник", "kitchen": "Кухня", "freezer": "Морозилка"}


# ---------------- DB helpers ----------------
def db_init() -> None:
    if DATABASE_URL:
        assert PG_POOL is not None
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS items (
                        id BIGSERIAL PRIMARY KEY,
                        kind TEXT NOT NULL,
                        place TEXT NOT NULL,
                        text TEXT NOT NULL,
                        created_by BIGINT,
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
                    created_by INTEGER,
                    created_at TEXT NOT NULL
                )
            """)
            con.commit()


def db_add(kind: str, place: str, text: str, user_id: Optional[int]) -> int:
    created_at = datetime.now(tz=TZ)

    if DATABASE_URL:
        assert PG_POOL is not None
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "INSERT INTO items(kind, place, text, created_by, created_at) "
                    "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                    (kind, place, text, user_id, created_at),
                )
                new_id = cur.fetchone()[0]
            con.commit()
            return int(new_id)

    created_at_s = created_at.isoformat(timespec="seconds")
    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute(
            "INSERT INTO items(kind, place, text, created_by, created_at) VALUES(?,?,?,?,?)",
            (kind, place, text, user_id, created_at_s),
        )
        con.commit()
        return int(cur.lastrowid)


def db_list(kind: str, place: str) -> list[tuple[int, str, str]]:
    """List items for one place (used for delete screen)."""
    if DATABASE_URL:
        assert PG_POOL is not None
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT id, text, created_at FROM items "
                    "WHERE kind=%s AND place=%s ORDER BY id ASC",
                    (kind, place),
                )
                rows = cur.fetchall()
        return [(int(r[0]), str(r[1]), r[2].isoformat(timespec="seconds")) for r in rows]

    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute(
            "SELECT id, text, created_at FROM items WHERE kind=? AND place=? ORDER BY id ASC",
            (kind, place),
        )
        return [(int(r[0]), str(r[1]), str(r[2])) for r in cur.fetchall()]


def db_list_all_places(kind: str) -> dict[str, list[tuple[int, str, str]]]:
    """One query for all places (fast). Returns dict: place -> rows."""
    result: dict[str, list[tuple[int, str, str]]] = {p: [] for p in ("fridge", "kitchen", "freezer")}

    if DATABASE_URL:
        assert PG_POOL is not None
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT place, id, text, created_at FROM items "
                    "WHERE kind=%s ORDER BY place ASC, id ASC",
                    (kind,),
                )
                rows = cur.fetchall()
        for place, item_id, text, created_at in rows:
            result[str(place)].append((int(item_id), str(text), created_at.isoformat(timespec="seconds")))
        return result

    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute(
            "SELECT place, id, text, created_at FROM items WHERE kind=? ORDER BY place ASC, id ASC",
            (kind,),
        )
        for place, item_id, text, created_at in cur.fetchall():
            result[str(place)].append((int(item_id), str(text), str(created_at)))
    return result


def db_delete(item_id: int) -> bool:
    if DATABASE_URL:
        assert PG_POOL is not None
        with PG_POOL.connection() as con:
            with con.cursor() as cur:
                cur.execute("DELETE FROM items WHERE id=%s", (item_id,))
                deleted = cur.rowcount > 0
            con.commit()
            return deleted

    with sqlite3.connect(SQLITE_PATH) as con:
        cur = con.execute("DELETE FROM items WHERE id=?", (item_id,))
        con.commit()
        return cur.rowcount > 0


# ---------------- UI helpers ----------------
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_rows(rows: list[tuple[int, str, str]]) -> str:
    """User-facing list WITHOUT internal DB ids."""
    if not rows:
        return "— (пусто)"
    out = []
    for idx, (_item_id, text, _created_at) in enumerate(rows, start=1):
        out.append(f"<b>{idx}.</b> {esc(text)}")
    return "\n".join(out)


def parse_lines_for_add(message_text: str) -> list[str]:
    """Split multiline message into items, trim, remove empty lines."""
    lines = []
    for line in message_text.splitlines():
        t = line.strip()
        if t:
            lines.append(t)
    return lines


def parse_numbers_for_delete(message_text: str) -> list[int]:
    """
    Accept: "1 4", "1,4", "1, 4  7" etc.
    Returns sorted unique ints.
    """
    cleaned = message_text.replace(",", " ").replace(";", " ")
    parts = [p.strip() for p in cleaned.split() if p.strip()]
    nums = []
    for p in parts:
        if p.isdigit():
            nums.append(int(p))
    # unique + stable
    return sorted(set(nums))


# ---------------- Keyboards ----------------
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить", callback_data="act:add")],
        [InlineKeyboardButton("➖ Удалить", callback_data="act:del")],
        [InlineKeyboardButton("❓ Что осталось?", callback_data="act:show")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="nav:main")],
    ])


def kb_kind(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍲 Готовые блюда", callback_data=f"{action}:kind:meal")],
        [InlineKeyboardButton("🥕 Ингредиенты", callback_data=f"{action}:kind:ingredient")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="nav:main")],
    ])


def kb_place(action: str, kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧊 Холодильник", callback_data=f"{action}:place:{kind}:fridge")],
        [InlineKeyboardButton("🏠 Кухня", callback_data=f"{action}:place:{kind}:kitchen")],
        [InlineKeyboardButton("❄️ Морозилка", callback_data=f"{action}:place:{kind}:freezer")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"{action}:back_kind")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="nav:main")],
    ])


def kb_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отмена", callback_data="nav:main")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="nav:main")],
    ])


def kb_back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Главное меню", callback_data="nav:main")]
    ])


# ---------------- Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text("Выбери действие:", reply_markup=kb_main())


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text("Ок, отменил. Выбери действие:", reply_markup=kb_main())


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data

    # Hard "go to main menu" (like /start)
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

    # Category selection
    if ":kind:" in data:
        act, _kw, kind = data.split(":")
        context.user_data["act"] = act
        context.user_data["kind"] = kind

        if act in ("add", "del"):
            await q.edit_message_text("Выбери место:", reply_markup=kb_place(act, kind))
        elif act == "show":
            allp = db_list_all_places(kind)  # ONE QUERY
            blocks = []
            for place in ("fridge", "kitchen", "freezer"):
                blocks.append(f"<b>{PLACE_LABEL[place]}</b>\n{fmt_rows(allp[place])}")
            text = f"Остатки: <b>{KIND_LABEL[kind]}</b>\n\n" + "\n\n".join(blocks)
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb_main())
        return

    # Place selection
    if ":place:" in data:
        act, _place_kw, kind, place = data.split(":")
        context.user_data["act"] = act
        context.user_data["kind"] = kind
        context.user_data["place"] = place

        if act == "add":
            await q.edit_message_text(
                f"Добавление:\n<b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
                "Напиши названия одним сообщением.\n"
                "Можно несколько строк, например:\n"
                "Суп\nРагу\n\n"
                "Если передумал — нажми ❌ Отмена.",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_cancel(),
            )
            return

        if act == "del":
            rows = db_list(kind, place)
            context.user_data["del_rows"] = rows
            msg = (
                f"Удаление:\n<b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
                f"{fmt_rows(rows)}\n\n"
                "Отправь номер(а) строк для удаления.\n"
                "Примеры: <b>2</b> или <b>1 4</b> или <b>1, 4</b>\n"
                "Команда /cancel — отмена."
            )
            await q.edit_message_text(
                msg,
                parse_mode=ParseMode.HTML,
                reply_markup=kb_back_to_menu(),
            )
            return

    await q.edit_message_text("Не понял кнопку. Вернёмся в меню.", reply_markup=kb_main())


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    raw = update.message.text

    # ADD flow: multiline add
    if context.user_data.get("act") == "add" and context.user_data.get("kind") and context.user_data.get("place"):
        kind = context.user_data["kind"]
        place = context.user_data["place"]
        uid = update.effective_user.id if update.effective_user else None

        items = parse_lines_for_add(raw)
        if not items:
            await update.message.reply_text("Пусто. Напиши хотя бы одну строку или /cancel.")
            return

        for t in items:
            db_add(kind, place, t, uid)

        context.user_data.clear()

        added_preview = "\n".join([f"• {esc(t)}" for t in items[:10]])
        more = ""
        if len(items) > 10:
            more = f"\n…и ещё {len(items) - 10} строк(и)"

        await update.message.reply_text(
            f"Добавил ✅ <b>{len(items)}</b> шт.\n"
            f"<b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
            f"{added_preview}{more}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_main(),
        )
        return

    # DEL flow: delete multiple indices
    if context.user_data.get("act") == "del" and "del_rows" in context.user_data:
        rows: list[tuple[int, str, str]] = context.user_data.get("del_rows", [])
        nums = parse_numbers_for_delete(raw)

        if not nums:
            await update.message.reply_text(
                "Для удаления отправь номер(а) строк.\n"
                "Примеры: 2 или 1 4 или 1, 4\n"
                "Или /cancel чтобы отменить."
            )
            return

        # Validate ranges
        valid = [n for n in nums if 1 <= n <= len(rows)]
        invalid = [n for n in nums if n < 1 or n > len(rows)]

        if not valid:
            await update.message.reply_text(
                f"Номера вне диапазона. Сейчас доступно 1..{len(rows)}.\n"
                "Попробуй ещё раз или /cancel."
            )
            return

        # Delete by internal ids (use snapshot order)
        # Delete in descending index order (not strictly necessary, but cleaner)
        deleted_count = 0
        for n in sorted(valid, reverse=True):
            item_id = rows[n - 1][0]
            if db_delete(item_id):
                deleted_count += 1

        kind = context.user_data.get("kind")
        place = context.user_data.get("place")
        new_rows = db_list(kind, place)
        context.user_data["del_rows"] = new_rows

        msg = (
            f"Удалил ✅ <b>{deleted_count}</b> шт.\n"
            f"<b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
            f"{fmt_rows(new_rows)}"
        )
        if invalid:
            msg += f"\n\n<i>Игнорировал вне диапазона: {', '.join(map(str, invalid))}</i>"

        await update.message.reply_text(
            msg,
            parse_mode=ParseMode.HTML,
            reply_markup=kb_back_to_menu() if new_rows else kb_main(),
        )
        return

    # Default fallback
    await update.message.reply_text("Выбери действие:", reply_markup=kb_main())


def main() -> None:
    db_init()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
