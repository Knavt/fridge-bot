import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes


def get_bot_token() -> str:
    """
    1) В Railway токен должен быть в Variables: BOT_TOKEN
    2) Локально можно хранить в .env (не коммитить!)
    """
    token = os.environ.get("BOT_TOKEN", "").strip()
    if token:
        return token

    # Локальный режим: пробуем прочитать .env, если установлен python-dotenv
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
        token = os.environ.get("BOT_TOKEN", "").strip()
        if token:
            return token
    except Exception:
        pass

    raise RuntimeError(
        "BOT_TOKEN не найден.\n"
        "• На Railway: добавь переменную BOT_TOKEN в Variables.\n"
        "• Локально: создай файл .env с строкой BOT_TOKEN=... (и не пушь его в git)."
    )


BOT_TOKEN = get_bot_token()


def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить", callback_data="act:add")],
        [InlineKeyboardButton("➖ Удалить", callback_data="act:del")],
        [InlineKeyboardButton("❓ Что осталось?", callback_data="act:show")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Я бот учёта запасов 🧊\nВыбери действие:",
        reply_markup=kb_main(),
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "act:add":
        text = "Ок. Дальше сделаем: добавить → (готовые/ингредиенты) → (холодильник/кухня/морозилка) → ввод."
    elif data == "act:del":
        text = "Ок. Дальше сделаем: удалить по категориям и месту (со списком и номерами)."
    elif data == "act:show":
        text = "Ок. Дальше сделаем: что осталось? → вывод по местам."
    else:
        text = "Неизвестная кнопка."

    await q.edit_message_text(text=text, reply_markup=kb_main())


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_button))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
