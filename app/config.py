import os
from zoneinfo import ZoneInfo

BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = "fridge.db"

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Amsterdam").strip())

VALID_KINDS = ("meal", "ingredient")
VALID_PLACES = ("fridge", "freezer", "kitchen")

KIND_LABEL = {"meal": "Готовые блюда", "ingredient": "Ингредиенты"}
PLACE_LABEL = {"fridge": "Холодильник", "kitchen": "Кухня", "freezer": "Морозилка"}

