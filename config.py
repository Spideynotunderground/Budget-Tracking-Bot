import os

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


TELEGRAM_TOKEN = _required("TELEGRAM_TOKEN")
GROQ_API_KEY = _required("GROQ_API_KEY")
DATABASE_URL = _required("DATABASE_URL")

GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile")

DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "USD")
BOT_TIMEZONE = os.getenv("BOT_TIMEZONE", "UTC")

_allowed = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USER_IDS = {int(x) for x in _allowed.split(",") if x.strip()} if _allowed else set()

CATEGORIES = [
    "groceries",
    "food",
    "transport",
    "shopping",
    "entertainment",
    "health",
    "bills",
    "travel",
    "other",
]

CATEGORY_EMOJI = {
    "groceries": "🛒",
    "food": "🍔",
    "transport": "🚕",
    "shopping": "🛍️",
    "entertainment": "🎬",
    "health": "💊",
    "bills": "🧾",
    "travel": "✈️",
    "other": "📦",
}
