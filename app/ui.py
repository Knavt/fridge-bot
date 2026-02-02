from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def kb_main():
    # 2 столбца, 3 ряда
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Добавить", callback_data="act:add"),
            InlineKeyboardButton("➖ Удалить", callback_data="act:del"),
        ],
        [
            InlineKeyboardButton("❓ Что осталось?", callback_data="act:show"),
            InlineKeyboardButton("📷 Добавить по фото", callback_data="act:photo"),
        ],
        [
            InlineKeyboardButton("🏠 Меню", callback_data="nav:main"),
            InlineKeyboardButton("✖️ Отмена", callback_data="nav:cancel"),
        ],
    ])


def kb_kind(action: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🍲 Готовые блюда", callback_data=f"{action}:kind:meal"),
            InlineKeyboardButton("🥕 Ингредиенты", callback_data=f"{action}:kind:ingredient"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="nav:main")],
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


def kb_photo_kind():
    # Выбор типа для фото-распознавания
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🍲 Готовое блюдо", callback_data="photo:kind:meal"),
            InlineKeyboardButton("🥕 Ингредиент", callback_data="photo:kind:ingredient"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="nav:main")],
    ])


def kb_photo_wait_back():
    # На шаге "пришлите фото" должна быть ОДНА кнопка "назад"
    # Возвращаем к выбору типа фото
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="act:photo")]
    ])


def kb_confirm_photo():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data="photo:confirm"),
            InlineKeyboardButton("❌ Отмена", callback_data="photo:cancel"),
        ],
        [InlineKeyboardButton("🏠 Меню", callback_data="nav:main")],
    ])
