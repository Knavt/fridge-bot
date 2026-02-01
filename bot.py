import os
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не найден. Проверь файл .env")


# ----- Кнопки -----
def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить", callback_data="act:add")],
        [InlineKeyboardButton("➖ Удалить", callback_data="act:del")],
        [InlineKeyboardButton("❓ Что осталось?", callback_data="act:show")],
    ])


def kb_kind(action: str) -> InlineKeyboardMarkup:
    # action: add/del/show
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🍲 Готовые блюда", callback_data=f"{action}:kind:meal")],
        [InlineKeyboardButton("🥕 Ингредиенты", callback_data=f"{action}:kind:ingredient")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="nav:main")],
    ])


def kb_place(action: str, kind: str) -> InlineKeyboardMarkup:
    # kind: meal/ingredient
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧊 Холодильник", callback_data=f"{action}:place:{kind}:fridge")],
        [InlineKeyboardButton("🏠 Кухня", callback_data=f"{action}:place:{kind}:kitchen")],
        [InlineKeyboardButton("❄️ Морозилка", callback_data=f"{action}:place:{kind}:freezer")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"{action}:back_kind")],
    ])


KIND_LABEL = {"meal": "Готовые блюда", "ingredient": "Ингредиенты"}
PLACE_LABEL = {"fridge": "Холодильник", "kitchen": "Кухня", "freezer": "Морозилка"}


# ----- Хендлеры -----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text("Выбери действие:", reply_markup=kb_main())


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data

    # Назад в главное меню
    if data == "nav:main":
        context.user_data.clear()
        await q.edit_message_text("Выбери действие:", reply_markup=kb_main())
        return

    # Выбор действия
    if data.startswith("act:"):
        act = data.split(":", 1)[1]  # add/del/show
        context.user_data.clear()
        context.user_data["act"] = act
        await q.edit_message_text("Выбери категорию:", reply_markup=kb_kind(act))
        return

    # Назад от выбора места к выбору категории
    if data.endswith(":back_kind"):
        act = data.split(":")[0]  # add/del/show
        await q.edit_message_text("Выбери категорию:", reply_markup=kb_kind(act))
        return

    # Выбор категории
    if ":kind:" in data:
        act, _kw, kind = data.split(":")  # add:kind:meal
        context.user_data["act"] = act
        context.user_data["kind"] = kind

        if act in ("add", "del"):
            await q.edit_message_text("Выбери место:", reply_markup=kb_place(act, kind))
        elif act == "show":
            # Пока заглушка
            await q.edit_message_text(
                f"Ок, покажу остатки: {KIND_LABEL[kind]} (позже вывод по местам).",
                reply_markup=kb_main(),
            )
        return

    # Выбор места
    if ":place:" in data:
        parts = data.split(":")  # add:place:meal:fridge
        act = parts[0]
        kind = parts[2]
        place = parts[3]

        context.user_data["act"] = act
        context.user_data["kind"] = kind
        context.user_data["place"] = place

        if act == "add":
            await q.edit_message_text(
                f"Добавление:\n{KIND_LABEL[kind]} → {PLACE_LABEL[place]}\n\n"
                f"Теперь просто напиши, что добавить (например: яйца).",
                reply_markup=None,
            )
        elif act == "del":
            await q.edit_message_text(
                f"Удаление:\n{KIND_LABEL[kind]} → {PLACE_LABEL[place]}\n\n"
                f"Позже тут будет список и удаление по номеру.",
                reply_markup=kb_main(),
            )
        else:
            await q.edit_message_text("Неизвестное действие.", reply_markup=kb_main())
        return

    # Если дошли сюда — что-то неизвестное
    await q.edit_message_text("Не понял кнопку. Вернёмся в меню.", reply_markup=kb_main())


# В этом шаге текстовые сообщения пока не обрабатываем (добавим на следующем)
def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))
    app.run_polling()


if __name__ == "__main__":
    main()
