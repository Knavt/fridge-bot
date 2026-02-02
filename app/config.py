import os
from zoneinfo import ZoneInfo

BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = "fridge.db"

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Amsterdam").strip())

VALID_KINDS = ("meal", "ingredient")
VALID_PLACES = ("fridge", "freezer", "kitchen")

MORNING_TZ = ZoneInfo(os.environ.get("MORNING_TZ", "Europe/Moscow").strip())
MORNING_HOUR = int(os.environ.get("MORNING_HOUR", "8").strip())
MORNING_MINUTE = int(os.environ.get("MORNING_MINUTE", "0").strip())
_MORNING_CHAT_RAW = os.environ.get("MORNING_CHAT_ID", "-1003230156353").strip()
MORNING_CHAT_ID = int(_MORNING_CHAT_RAW) if _MORNING_CHAT_RAW else None
_MORNING_THREAD_RAW = os.environ.get("MORNING_THREAD_ID", "16").strip()
MORNING_THREAD_ID = int(_MORNING_THREAD_RAW) if _MORNING_THREAD_RAW else None

KIND_LABEL = {"meal": "Готовые блюда", "ingredient": "Ингредиенты"}
PLACE_LABEL = {"fridge": "Холодильник", "kitchen": "Кухня", "freezer": "Морозилка"}


