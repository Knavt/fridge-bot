# app/ai.py
import os
import json
import base64
from typing import Dict, Any

from app.config import OPENAI_API_KEY, VALID_KINDS

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
- суп/борщ/рагу/голубцы/плов/котлеты/макароны -> meal
- молоко/яйца/сыр/курица/масло/овощи -> ingredient
Если сомневаешься -> ingredient.
"""

AI_PHOTO_PROMPT_MEAL = """
Ты видишь фото ЕДЫ. Твоя задача — назвать ОДНО готовое блюдо, которое лучше всего описывает фото.

Верни ТОЛЬКО валидный JSON (без markdown).
Формат:
{
  "action": "add",
  "kind": "meal",
  "place": "fridge",
  "items": ["одно название блюда"]
}

КРИТИЧЕСКИ ВАЖНО:
- items ДОЛЖЕН содержать РОВНО 1 строку
- не перечисляй ингредиенты отдельными пунктами
- пиши как блюдо целиком (например: "макароны с креветками и шпинатом")
- без брендов, без лишних слов
- если совсем не уверен: items=[]
"""

AI_PHOTO_PROMPT_ING = """
Ты видишь фото продуктов/ингредиентов. Твоя задача — перечислить продукты, которые видны.

Верни ТОЛЬКО валидный JSON (без markdown).
Формат:
{
  "action": "add",
  "kind": "ingredient",
  "place": "fridge",
  "items": ["название1", "название2", ...]
}

Правила:
- короткие русские названия
- без брендов
- если не уверен: items=[]
"""


def _client():
    if not OPENAI_API_KEY:
        return None
    from openai import OpenAI
    return OpenAI(api_key=OPENAI_API_KEY)


def ai_parse_text(text: str) -> Dict[str, Any]:
    """
    Parse free text into action JSON.
    Uses gpt-4o-mini for reliability.
    """
    client = _client()
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


async def ai_parse_photo(update, context, kind: str) -> Dict[str, Any]:
    """
    Recognize items from photo.
    - kind is pre-selected by user: 'meal' or 'ingredient'
    - returns dict {action, kind, place, items}
    """
    if kind not in VALID_KINDS:
        kind = "ingredient"

    client = _client()
    if client is None:
        return {"action": "add", "kind": kind, "place": "fridge", "items": []}

    try:
        if not update.message or not update.message.photo:
            return {"action": "add", "kind": kind, "place": "fridge", "items": []}

        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        data_bytes = await file.download_as_bytearray()

        b64 = base64.b64encode(bytes(data_bytes)).decode("ascii")
        data_url = f"data:image/jpeg;base64,{b64}"

        prompt = AI_PHOTO_PROMPT_MEAL if kind == "meal" else AI_PHOTO_PROMPT_ING

        resp = client.responses.create(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Верни JSON по правилам."},
                        {"type": "input_image", "image_url": data_url},
                    ],
                },
            ],
            max_output_tokens=300,
        )

        raw = (resp.output_text or "").strip()
        print("AI photo raw:", raw)
        if not raw:
            return {"action": "add", "kind": kind, "place": "fridge", "items": []}

        parsed = json.loads(raw)

        items = parsed.get("items", [])
        if isinstance(items, str):
            items = [items]
        if not isinstance(items, list):
            items = []
        items = [str(x).strip() for x in items if str(x).strip()]

        if kind == "meal":
            items = items[:1]  # enforce single dish

        return {"action": "add", "kind": kind, "place": "fridge", "items": items}

    except Exception as e:
        print("AI photo error:", e)
        return {"action": "add", "kind": kind, "place": "fridge", "items": []}
