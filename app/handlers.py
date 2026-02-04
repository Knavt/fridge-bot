from datetime import datetime, time
import random
from typing import List, Tuple, Union

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from app.config import (
    BOT_TOKEN,
    OPENAI_API_KEY,
    VALID_KINDS,
    VALID_PLACES,
    KIND_LABEL,
    PLACE_LABEL,
    TZ,
    MORNING_CHAT_ID,
    MORNING_THREAD_ID,
    MORNING_TZ,
    MORNING_HOUR,
    MORNING_MINUTE,
    EVENING_CHAT_ID,
    EVENING_THREAD_ID,
    EVENING_HOUR,
    EVENING_MINUTE,
    ADMIN_IDS,
)
from app.ui import (
    kb_main,
    kb_kind,
    kb_place,
    kb_photo_kind,
    kb_photo_wait_back,
    kb_confirm_photo,
    kb_edit_field,
    kb_move_dest,
    kb_back,
)
from app.utils import (
    esc,
    parse_add_lines,
    parse_delete_nums,
    norm,
)
from app.db import (
    db_init,
    db_add,
    db_list,
    db_list_all,
    db_list_place,
    db_all_raw,
    db_all_raw_with_date,
    db_delete,
    db_update_text,
    db_update_created_at,
    db_update_place_and_date,
)
from app.ai import (
    ai_parse_text,
    ai_parse_photo,
)
from app.welcome import WELCOME_TEXT


DbDateValue = Union[str, datetime]


def _fmt_date(value: DbDateValue) -> str:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return ""
    else:
        return ""
    return dt.strftime("%d.%m.%Y")


def fmt_rows(rows: List[Tuple[int, str, DbDateValue]]) -> str:
    if not rows:
        return "— (пусто)"
    out = []
    for i, (_id, text, created_at) in enumerate(rows, start=1):
        date_str = _fmt_date(created_at)
        if date_str:
            out.append(f"<b>{i}.</b> {esc(text)} — {date_str}")
        else:
            out.append(f"<b>{i}.</b> {esc(text)}")
    return "\n".join(out)


def _coerce_dt(value: DbDateValue) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MORNING_TZ)
    return dt.astimezone(MORNING_TZ)


def _build_morning_message(items: List[Tuple[str, str, DbDateValue]]) -> str:
    now = datetime.now(tz=MORNING_TZ)
    entries: List[Tuple[int, str, str]] = []
    for kind, text, created_at in items:
        if kind != "meal":
            continue
        dt = _coerce_dt(created_at)
        if not dt:
            continue
        days = (now.date() - dt.date()).days
        entries.append((days, kind, text))

    entries.sort(key=lambda x: (-x[0], x[2].lower()))

    greetings = [
        "Доброе утро! ☀️ Пора зарядиться вкусным",
        "Подъем! 🧠 Берем с собой что-нибудь классное",
        "Утро доброе, холодильник бодр! 😄 Что прихватить",
        "С добрым утром! 🎒 В рюкзак что-нибудь вкусное",
        "Утренний чек-лист еды на работу 🧾",
        "Доброе утро! Вот гастро-идеи на сегодня 😋",
        "Проснулся — и еда уже готова. Берем 🍽️",
        "Вкусного утра! Что берем с собой 🤗",
        "Зарядись вкусом: выбор на утро ⚡",
        "Ланч зовет. Что из холодильника взять 🥡",
    ]

    if not entries:
        return random.choice(greetings) + ":"

    take_items = entries[:3]
    lines = [random.choice(greetings) + ":"]
    for _days, _k, t in take_items:
        suffix = " (лежит >3х дней ⏳)" if _days >= 3 else ""
        lines.append(f"• {t}{suffix}")
    return "\n".join(lines)


async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    if not MORNING_CHAT_ID:
        return
    items = db_list_place("fridge")
    msg = _build_morning_message(items)
    await context.bot.send_message(
        chat_id=MORNING_CHAT_ID,
        text=msg,
        message_thread_id=MORNING_THREAD_ID,
    )


async def evening_job(context: ContextTypes.DEFAULT_TYPE):
    if not EVENING_CHAT_ID:
        return
    items = db_list_place("fridge")
    msg = _build_evening_message(items)
    await context.bot.send_message(
        chat_id=EVENING_CHAT_ID,
        text=msg,
        message_thread_id=EVENING_THREAD_ID,
    )


def _build_evening_message(items: List[Tuple[str, str, DbDateValue]]) -> str:
    now = datetime.now(tz=MORNING_TZ)
    entries: List[Tuple[int, str, str]] = []
    for kind, text, created_at in items:
        if kind != "meal":
            continue
        dt = _coerce_dt(created_at)
        if not dt:
            continue
        days = (now.date() - dt.date()).days
        entries.append((days, kind, text))

    entries.sort(key=lambda x: (-x[0], x[2].lower()))

    greetings = [
        "Добрый вечер! 🌙 Что скушаем на ужин",
        "Время ужина! 🍲 Предлагаю выбрать",
        "Ужин зовет. Вот вкусные варианты 😋",
        "Вечер вкусный начинается здесь ✨",
        "Что на ужин? Есть идеи 🤔",
        "Гастро-вечер: выбираем ужин 🍽️",
        "Пора ужинать! Что берем 😄",
        "Вечерний список вкусностей 🧺",
        "Ужин-тайм! Есть несколько вариантов 🕒",
        "Вкусного вечера! Что предпочитаешь 😊",
    ]

    if not entries:
        return random.choice(greetings) + ":"

    take_items = entries[:3]
    lines = [random.choice(greetings) + ":"]
    for _days, _k, t in take_items:
        suffix = " (лежит >3х дней ⏳)" if _days >= 3 else ""
        lines.append(f"• {t}{suffix}")
    return "\n".join(lines)


def _is_admin(update: Update) -> bool:
    user = update.effective_user
    if not user:
        return False
    if not ADMIN_IDS:
        return True
    return user.id in ADMIN_IDS


def _is_private(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type == "private")


def _main_kb(update: Update):
    return kb_main(_is_admin(update))


def _parse_ddmmyyyy(value: str) -> datetime | None:
    try:
        dt = datetime.strptime(value.strip(), "%d.%m.%Y")
    except ValueError:
        return None
    return dt.replace(tzinfo=TZ)

def find_matches(rows: List[Tuple[int, str, str, str]], query: str):
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


def _extract_query(text: str) -> str:
    raw = (text or "").lower().strip()
    if not raw:
        return ""

    prefixes = [
        "есть ли у нас",
        "осталась ли у нас",
        "осталось ли у нас",
        "у нас есть ли",
        "у нас осталась ли",
        "у нас осталось ли",
        "есть ли",
        "осталась ли",
        "осталось ли",
    ]
    for p in prefixes:
        if raw.startswith(p):
            return raw[len(p):].strip(" ?!.,")

    for p in ("есть ли", "осталась ли", "осталось ли"):
        if p in raw:
            return raw.split(p, 1)[1].strip(" ?!.,")

    if raw.endswith("?"):
        return raw.strip(" ?!.,")

    return ""


def _find_query_matches(rows: List[Tuple[int, str, str, str, DbDateValue]], query: str):
    q = norm(query)
    if not q:
        return []

    exact = [r for r in rows if norm(r[3]) == q]
    if exact:
        return exact

    subs = []
    for r in rows:
        tt = norm(r[3])
        if q in tt or tt in q:
            subs.append(r)
    return subs


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(WELCOME_TEXT, reply_markup=_main_kb(update))


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(WELCOME_TEXT, reply_markup=_main_kb(update))


async def env_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    present = bool(OPENAI_API_KEY)
    await update.message.reply_text(f"OPENAI_API_KEY present: {present}")


async def ai_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    res = ai_parse_text("Добавь молоко и яйца в холодильник")
    await update.message.reply_text(f"AI_TEST: {res}")


async def edit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_private(update):
        await update.message.reply_text("Редактирование доступно только в личке.")
        return
    if not _is_admin(update):
        await update.message.reply_text("Недостаточно прав.")
        return
    context.user_data.clear()
    context.user_data["act"] = "edit"
    await update.message.reply_text("Выбери категорию:", reply_markup=kb_kind("edit"))


async def morning_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not MORNING_CHAT_ID:
        await update.message.reply_text("MORNING_CHAT_ID не задан.")
        return
    items = db_list_place("fridge")
    msg = _build_morning_message(items)
    try:
        await context.bot.send_message(
            chat_id=MORNING_CHAT_ID,
            text=msg,
            message_thread_id=MORNING_THREAD_ID,
        )
    except Exception as exc:
        await update.message.reply_text(f"Ошибка отправки: {exc!r}")
        return
    await update.message.reply_text("Отправил тестовое утреннее сообщение.")


async def evening_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not EVENING_CHAT_ID:
        await update.message.reply_text("EVENING_CHAT_ID не задан.")
        return
    items = db_list_place("fridge")
    msg = _build_evening_message(items)
    try:
        await context.bot.send_message(
            chat_id=EVENING_CHAT_ID,
            text=msg,
            message_thread_id=EVENING_THREAD_ID,
        )
    except Exception as exc:
        await update.message.reply_text(f"Ошибка отправки: {exc!r}")
        return
    await update.message.reply_text("Отправил тестовое вечернее сообщение.")


async def whereami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = msg.chat_id if msg else None
    thread_id = msg.message_thread_id if msg else None
    await update.message.reply_text(
        f"chat_id={chat_id}\nmessage_thread_id={thread_id}"
    )


# ================= CALLBACKS =================
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data.startswith("act:edit") or data.startswith("edit:"):
        if not _is_private(update):
            await q.edit_message_text("Редактирование доступно только в личке.", reply_markup=_main_kb(update))
            return
        if not _is_admin(update):
            await q.edit_message_text("Недостаточно прав.", reply_markup=_main_kb(update))
            return

    # ---- Global nav
    if data == "nav:main":
        context.user_data.clear()
        await q.edit_message_text(WELCOME_TEXT, reply_markup=_main_kb(update))
        return

    if data == "nav:cancel":
        context.user_data.clear()
        await q.edit_message_text(WELCOME_TEXT, reply_markup=_main_kb(update))
        return

    # ---- Photo flow entry
    if data == "act:photo":
        # Если мы были в ожидании фото — тоже возвращаемся сюда
        context.user_data.clear()
        context.user_data["photo_mode"] = "choose_kind"
        await q.edit_message_text("Фото-распознавание: выбери тип:", reply_markup=kb_photo_kind())
        return

    # ---- Photo kind selected
    if data.startswith("photo:kind:"):
        _, _, kind = data.split(":")
        if kind not in VALID_KINDS:
            kind = "ingredient"
        context.user_data.clear()
        context.user_data["photo_mode"] = "wait_photo"
        context.user_data["photo_kind"] = kind

        # ВАЖНО: здесь показываем ТОЛЬКО "Назад"
        await q.edit_message_text(
            f"Ок. Тип: <b>{KIND_LABEL[kind]}</b>\n\n"
            f"Теперь пришли <b>фото</b> одним сообщением.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_photo_wait_back(),
        )
        return

    # ---- Photo confirm/cancel
    if data == "photo:cancel":
        # отмена подтверждения -> возвращаемся в меню
        context.user_data.clear()
        await q.edit_message_text(WELCOME_TEXT, reply_markup=_main_kb(update))
        return

    if data == "photo:confirm":
        pending = context.user_data.get("pending_photo")
        if not pending:
            context.user_data.clear()
            await q.edit_message_text(WELCOME_TEXT, reply_markup=_main_kb(update))
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

        context.user_data.clear()
        await q.edit_message_text(
            f"Добавил ✅ {added} шт. ({KIND_LABEL[kind]} → {PLACE_LABEL[place]})",
            reply_markup=_main_kb(update),
        )
        return

    # ---- Standard flows
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

    if data in ("add:back_place", "del:back_place"):
        act = data.split(":")[0]
        kind = context.user_data.get("kind", "ingredient")
        await q.edit_message_text("Выбери место:", reply_markup=kb_place(act, kind))
        return

    if data == "move:back_place":
        kind = context.user_data.get("kind", "ingredient")
        await q.edit_message_text("Выбери место:", reply_markup=kb_place("move", kind))
        return

    if data.startswith("move:dest:"):
        _, _kw, kind, from_place, to_place = data.split(":")
        context.user_data["act"] = "move"
        context.user_data["kind"] = kind
        context.user_data["move_from"] = from_place
        context.user_data["move_to"] = to_place

        rows = db_list(kind, from_place)
        context.user_data["move_rows"] = rows
        msg = (
            f"Переложить: <b>{KIND_LABEL[kind]}</b> → "
            f"<b>{PLACE_LABEL[from_place]}</b> → <b>{PLACE_LABEL[to_place]}</b>\n\n"
            f"{fmt_rows(rows)}\n\n"
            "Отправь номер(а) строк для переноса.\n"
            "Примеры: <b>2</b> или <b>1 4</b> или <b>1, 4</b>\n"
            "/cancel — отмена."
        )
        await q.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=_main_kb(update))
        return

    if data == "edit:back_place":
        kind = context.user_data.get("kind", "ingredient")
        await q.edit_message_text("Выбери место:", reply_markup=kb_place("edit", kind))
        return

    if data.startswith("edit:field:"):
        field = data.split(":")[-1]
        context.user_data["edit_field"] = field
        if field == "text":
            await q.edit_message_text(
                "Отправь: номер и новое название.\nПример: <b>2 Паста карбонара</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_back("edit:back_place"),
            )
            return
        if field == "date":
            await q.edit_message_text(
                "Отправь: номер и новую дату в формате <b>дд.мм.гггг</b>.\nПример: <b>2 04.02.2026</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_back("edit:back_place"),
            )
            return

    if ":kind:" in data:
        act, _kw, kind = data.split(":")
        context.user_data["act"] = act
        context.user_data["kind"] = kind

        if act in ("add", "del", "edit", "move"):
            await q.edit_message_text("Выбери место:", reply_markup=kb_place(act, kind))
            return

        if act == "show":
            allp = db_list_all(kind)
            blocks = []
            for place in VALID_PLACES:
                blocks.append(f"<b>{PLACE_LABEL[place]}</b>\n{fmt_rows(allp[place])}")
            text = f"Остатки: <b>{KIND_LABEL[kind]}</b>\n\n" + "\n\n".join(blocks)
            await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=_main_kb(update))
            return

    if ":place:" in data:
        act, _pkw, kind, place = data.split(":")
        context.user_data["act"] = act
        context.user_data["kind"] = kind
        context.user_data["place"] = place

        if act == "add":
            await q.edit_message_text(
                f"Добавление: <b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
                "Напиши названия одним сообщением.\n"
                "Можно несколько строк:\nСуп\nРагу",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_back("add:back_place"),
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
            await q.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb_back("del:back_place"))
            return

        if act == "move":
            await q.edit_message_text(
                "Куда переложить?",
                reply_markup=kb_move_dest(kind, place),
            )
            return

        if act == "edit":
            rows = db_list(kind, place)
            context.user_data["edit_rows"] = rows
            msg = (
                f"Редактирование: <b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL[place]}</b>\n\n"
                f"{fmt_rows(rows)}\n\n"
                "Что редактируем?"
            )
            await q.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb_edit_field())
            return

    await q.edit_message_text(WELCOME_TEXT, reply_markup=_main_kb(update))


# ================= TEXT HANDLER =================
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text or ""
    text = raw.strip()

    if context.user_data.get("act") == "edit":
        if not _is_private(update):
            await update.message.reply_text("Редактирование доступно только в личке.", reply_markup=kb_back("edit:back_place"))
            return
        if not _is_admin(update):
            await update.message.reply_text("Недостаточно прав.", reply_markup=kb_back("edit:back_place"))
            return
        field = context.user_data.get("edit_field")
        rows = context.user_data.get("edit_rows", [])
        if field and rows:
            parts = text.split()
            if len(parts) < 2 or not parts[0].isdigit():
                await update.message.reply_text(
                    "Нужен номер и значение. Пример: <b>2 Новое название</b> или <b>2 04.02.2026</b>.",
                    parse_mode=ParseMode.HTML,
                )
                return
            idx = int(parts[0])
            if idx < 1 or idx > len(rows):
                await update.message.reply_text(
                    f"Сейчас доступно 1..{len(rows)}. Попробуй снова.",
                    reply_markup=kb_back("edit:back_place"),
                )
                return
            item_id = rows[idx - 1][0]
            if field == "text":
                new_text = " ".join(parts[1:]).strip()
                if not new_text:
                    await update.message.reply_text("Новое название пустое.", reply_markup=kb_back("edit:back_place"))
                    return
                db_update_text(item_id, new_text)
            elif field == "date":
                new_date = " ".join(parts[1:]).strip()
                dt = _parse_ddmmyyyy(new_date)
                if not dt:
                    await update.message.reply_text(
                        "Неверная дата. Формат: <b>дд.мм.гггг</b>.",
                        parse_mode=ParseMode.HTML,
                    )
                    return
                db_update_created_at(item_id, dt)
            else:
                await update.message.reply_text("Сначала выбери, что редактировать.", reply_markup=kb_back("edit:back_place"))
                return

            kind = context.user_data.get("kind")
            place = context.user_data.get("place")
            if kind and place:
                context.user_data["edit_rows"] = db_list(kind, place)
            await update.message.reply_text("Готово. Можно редактировать дальше.", reply_markup=kb_back("edit:back_place"))
            return

    # Строго: если ждём фото — текст не принимаем, и показываем только "Назад"
    if context.user_data.get("photo_mode") == "wait_photo":
        kind = context.user_data.get("photo_kind", "ingredient")
        await update.message.reply_text(
            f"Сейчас жду <b>фото</b> для: <b>{KIND_LABEL.get(kind, kind)}</b>.\n"
            f"Пришли фото одним сообщением.",
            parse_mode=ParseMode.HTML,
            reply_markup=kb_photo_wait_back(),
        )
        return

    # Move items
    if context.user_data.get("act") == "move" and "move_rows" in context.user_data:
        rows = context.user_data.get("move_rows", [])
        nums = parse_delete_nums(text)
        if not nums:
            await update.message.reply_text(
                "Отправь номер(а) строк для переноса. Примеры: 2 или 1 4 или 1, 4",
                reply_markup=_main_kb(update),
            )
            return
        valid = [n for n in nums if 1 <= n <= len(rows)]
        if not valid:
            await update.message.reply_text(
                f"Сейчас доступно 1..{len(rows)}. Попробуй снова.",
                reply_markup=_main_kb(update),
            )
            return

        to_place = context.user_data.get("move_to")
        if to_place not in VALID_PLACES:
            await update.message.reply_text("Не выбрано место назначения.", reply_markup=_main_kb(update))
            return

        now = datetime.now(tz=TZ)
        moved = 0
        for n in sorted(valid, reverse=True):
            item_id = rows[n - 1][0]
            db_update_place_and_date(item_id, to_place, now)
            moved += 1

        kind = context.user_data.get("kind")
        from_place = context.user_data.get("move_from")
        if kind and from_place:
            context.user_data["move_rows"] = db_list(kind, from_place)

        await update.message.reply_text(
            f"Переложил ✅ {moved} шт. (дата обновлена)",
            reply_markup=_main_kb(update),
        )
        return

    # Manual ADD
    if context.user_data.get("act") == "add" and context.user_data.get("kind") and context.user_data.get("place"):
        kind = context.user_data["kind"]
        place = context.user_data["place"]
        items = parse_add_lines(raw)
        if not items:
            await update.message.reply_text(
                "Пусто. Напиши хотя бы одну строку или /cancel.",
                reply_markup=kb_back("add:back_place"),
            )
            return
        for t in items:
            db_add(kind, place, t)
        context.user_data.clear()
        await update.message.reply_text(f"Добавил ✅ {len(items)} шт.", reply_markup=_main_kb(update))
        return

    # Manual DEL
    if context.user_data.get("act") == "del" and "del_rows" in context.user_data:
        nums = parse_delete_nums(text)
        rows = context.user_data.get("del_rows", [])

        if not nums:
            await update.message.reply_text(
                "Для удаления отправь номер(а) строк.\nПримеры: 2 или 1 4 или 1, 4\n/cancel — отмена.",
                reply_markup=kb_back("del:back_place"),
            )
            return

        valid = [n for n in nums if 1 <= n <= len(rows)]
        if not valid:
            await update.message.reply_text(
                f"Сейчас доступно 1..{len(rows)}. Попробуй снова.",
                reply_markup=kb_back("del:back_place"),
            )
            return

        for n in sorted(valid, reverse=True):
            item_id = rows[n - 1][0]
            db_delete(item_id)

        kind = context.user_data.get("kind")
        place = context.user_data.get("place")
        context.user_data["del_rows"] = db_list(kind, place)

        await update.message.reply_text(
            f"Удалил ✅ {len(valid)} шт.",
            reply_markup=kb_back("del:back_place"),
        )
        return

    # Query: "есть ли ..."
    query = _extract_query(text)
    if query:
        rows = db_all_raw_with_date()
        matches = _find_query_matches(rows, query)
        if not matches:
            await update.message.reply_text("Похоже, этого нет в списке.", reply_markup=_main_kb(update))
            return

        lines = ["Нашёл:"]
        for _id, kind, place, item_text, created_at in matches[:20]:
            date_str = _fmt_date(created_at)
            extra = f" — {date_str}" if date_str else ""
            lines.append(
                f"• {esc(item_text)} — {PLACE_LABEL.get(place, place)} — {KIND_LABEL.get(kind, kind)}{extra}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=_main_kb(update))
        return

    # AI free-text
    ai = ai_parse_text(text)
    action = ai.get("action", "unknown")

    if action == "add":
        kind = ai.get("kind", "ingredient")
        place = ai.get("place", "fridge")
        items = ai.get("items", [])

        if isinstance(items, str):
            items = [items]
        if not isinstance(items, list) or not items:
            await update.message.reply_text("Не понял, что добавить. Используй кнопки 👇", reply_markup=_main_kb(update))
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
            reply_markup=_main_kb(update),
        )
        return

    if action == "delete":
        items = ai.get("items", [])
        if isinstance(items, str):
            items = [items]
        if not isinstance(items, list) or not items:
            await update.message.reply_text("Не понял, что удалить. Используй кнопки 👇", reply_markup=_main_kb(update))
            return

        queries = [str(x).strip() for x in items if str(x).strip()]
        if not queries:
            await update.message.reply_text("Не понял, что удалить. Используй кнопки 👇", reply_markup=_main_kb(update))
            return

        rows = db_all_raw()

        place_hint = ai.get("place")
        kind_hint = ai.get("kind")
        if place_hint in VALID_PLACES:
            rows = [r for r in rows if r[2] == place_hint]
        if kind_hint in VALID_KINDS:
            rows = [r for r in rows if r[1] == kind_hint]

        deleted = 0
        ambiguous = []

        for qtxt in queries:
            matches = find_matches(rows, qtxt)
            if len(matches) == 1:
                db_delete(int(matches[0][0]))
                deleted += 1
            elif len(matches) > 1:
                ambiguous.append((qtxt, matches))

        if ambiguous:
            msg = ["Часть позиций не удалил — нужно уточнить:"]
            for qtxt, matches in ambiguous:
                msg.append(f"\n• «{esc(qtxt)}» подходит к нескольким:")
                for i, (_id, t) in enumerate(matches[:10], start=1):
                    msg.append(f"  {i}) {esc(t)}")
            msg.append("\nНапиши точнее (например: «удали рыбный суп»).")
            await update.message.reply_text("\n".join(msg), parse_mode=ParseMode.HTML, reply_markup=_main_kb(update))
            return

        await update.message.reply_text(f"🤖 Удалил {deleted} шт.", reply_markup=_main_kb(update))
        return

    await update.message.reply_text("Не понял. Используй кнопки 👇", reply_markup=_main_kb(update))


# ================= PHOTO HANDLER =================
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Строго: фото принимаем только когда бот просил
    if context.user_data.get("photo_mode") != "wait_photo":
        await update.message.reply_text(
            "Фото сейчас не принимаю.\nНажми «📷 Добавить по фото» и следуй шагам.",
            reply_markup=_main_kb(update),
        )
        return

    kind = context.user_data.get("photo_kind", "ingredient")
    if kind not in VALID_KINDS:
        kind = "ingredient"

    parsed = await ai_parse_photo(update, context, kind)

    items = parsed.get("items", [])
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, list):
        items = []
    items = [str(x).strip() for x in items if str(x).strip()]

    # meal -> single dish
    if kind == "meal":
        items = items[:1]

    if not items:
        await update.message.reply_text(
            "По фото не смог уверенно распознать.\nПопробуй другое фото.",
            reply_markup=kb_photo_wait_back(),  # только назад
        )
        return

    context.user_data["pending_photo"] = {
        "kind": kind,
        "place": "fridge",
        "items": items,
    }

    preview = "\n".join([f"• {esc(x)}" for x in items[:30]])
    msg = (
        f"Я предлагаю добавить:\n\n"
        f"<b>{KIND_LABEL[kind]}</b> → <b>{PLACE_LABEL['fridge']}</b>\n\n"
        f"{preview}\n\n"
        f"Подтвердить?"
    )

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=kb_confirm_photo())


# ================= ERROR HANDLER =================
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print("ERROR:", context.error)


# ================= APP BUILDER =================
def build_app() -> Application:
    print("OPENAI_API_KEY present:", bool(OPENAI_API_KEY))
    db_init()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("env", env_cmd))
    app.add_handler(CommandHandler("ai_test", ai_test))
    app.add_handler(CommandHandler("edit", edit_cmd))
    app.add_handler(CommandHandler("morning_test", morning_test))
    app.add_handler(CommandHandler("evening_test", evening_test))
    app.add_handler(CommandHandler("evening_post", evening_test))
    app.add_handler(CommandHandler("whereami", whereami))

    app.add_handler(CallbackQueryHandler(on_button))

    # photo handler before text handler
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    if MORNING_CHAT_ID:
        if app.job_queue is None:
            print("JobQueue not available: install python-telegram-bot[job-queue]")
        else:
            app.job_queue.run_daily(
                morning_job,
                time=time(hour=MORNING_HOUR, minute=MORNING_MINUTE, tzinfo=MORNING_TZ),
                name="morning_reminder",
            )

    if EVENING_CHAT_ID:
        if app.job_queue is None:
            print("JobQueue not available: install python-telegram-bot[job-queue]")
        else:
            app.job_queue.run_daily(
                evening_job,
                time=time(hour=EVENING_HOUR, minute=EVENING_MINUTE, tzinfo=MORNING_TZ),
                name="evening_reminder",
            )

    app.add_error_handler(on_error)

    return app




