from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def kb_main(is_admin: bool = False):
    # 2 столбца, 3 ряда (без админ-кнопки)
    rows = [
        [
            InlineKeyboardButton("➕ Добавить", callback_data="act:add"),
            InlineKeyboardButton("➖ Удалить", callback_data="act:del"),
        ],
        [
            InlineKeyboardButton("❓ Что осталось?", callback_data="act:show"),
            InlineKeyboardButton("📷 Добавить по фото", callback_data="act:photo"),
        ],
        [InlineKeyboardButton("📦 Переложить", callback_data="act:move")],
    ]
    if is_admin:
        rows.append(
            [
                InlineKeyboardButton("✏️ Редактировать", callback_data="act:edit"),
                InlineKeyboardButton("🏠 Меню", callback_data="nav:main"),
            ]
        )
    else:
        rows.append([InlineKeyboardButton("🏠 Меню", callback_data="nav:main")])
    rows.append([InlineKeyboardButton("✖️ Отмена", callback_data="nav:cancel")])
    return InlineKeyboardMarkup(rows)


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
            InlineKeyboardButton("🥶 Холодильник", callback_data=f"{action}:place:{kind}:fridge"),
            InlineKeyboardButton("❄️ Морозилка", callback_data=f"{action}:place:{kind}:freezer"),
        ],
        [
            InlineKeyboardButton("🏠 Кухня", callback_data=f"{action}:place:{kind}:kitchen"),
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
    # На шаге "пришлите фото" должна быть одна кнопка "назад"
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


def kb_edit_field():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Название", callback_data="edit:field:text"),
            InlineKeyboardButton("📅 Дата", callback_data="edit:field:date"),
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="edit:back_place")],
        [InlineKeyboardButton("🏠 Меню", callback_data="nav:main")],
    ])


def kb_move_dest(kind: str, from_place: str):
    buttons = []
    if from_place != "fridge":
        buttons.append(InlineKeyboardButton("🥶 Холодильник", callback_data=f"move:dest:{kind}:{from_place}:fridge"))
    if from_place != "freezer":
        buttons.append(InlineKeyboardButton("❄️ Морозилка", callback_data=f"move:dest:{kind}:{from_place}:freezer"))
    if from_place != "kitchen":
        buttons.append(InlineKeyboardButton("🏠 Кухня", callback_data=f"move:dest:{kind}:{from_place}:kitchen"))

    rows = []
    if len(buttons) >= 2:
        rows.append([buttons[0], buttons[1]])
        if len(buttons) == 3:
            rows.append([buttons[2]])
    elif buttons:
        rows.append([buttons[0]])

    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="move:back_place")])
    rows.append([InlineKeyboardButton("🏠 Меню", callback_data="nav:main")])
    return InlineKeyboardMarkup(rows)
