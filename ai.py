import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SYSTEM_PROMPT = """
Ты помощник телеграм-бота для учета еды.

Твоя задача:
— понять, что хочет сделать пользователь
— вернуть ТОЛЬКО JSON
— не писать пояснений
— если не уверен, верни action = "unknown"

Возможные action:
- add
- delete
- unknown

kind:
- meal
- ingredient

place:
- fridge
- kitchen
- freezer

Примеры:

Ввод:
"Купили курицу и молоко, положили в холодильник"

Ответ:
{
  "action": "add",
  "kind": "ingredient",
  "place": "fridge",
  "items": ["курица", "молоко"]
}

Ввод:
"Съели суп и рагу"

Ответ:
{
  "action": "delete",
  "items": ["суп", "рагу"]
}
"""

def parse_text_command(text: str) -> dict:
    resp = client.chat.completions.create(
        model="gpt-5-nano",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0,
    )

    content = resp.choices[0].message.content.strip()

    try:
        return json.loads(content)
    except Exception:
        return {"action": "unknown"}
