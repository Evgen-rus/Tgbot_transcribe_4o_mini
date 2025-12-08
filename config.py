import os
from dotenv import load_dotenv
import logging

# Загрузка переменных окружения из файла .env
load_dotenv()

# Получение токенов и настроек из переменных окружения
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# Модель для транскрибации голосовых сообщений
TRANSCRIPTION_MODEL = os.getenv("TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
# Разрешённые чаты для бота (через запятую). Если пусто — доступ запрещён всем.
ALLOWED_CHAT_IDS: list[int] = [
    int(chat_id.strip())
    for chat_id in os.getenv("TELEGRAM_CHAT_ID", "").split(",")
    if chat_id.strip()
]

# Настройки логирования
LOGGING_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ENABLE_DIALOG_LOGGING = os.getenv("ENABLE_DIALOG_LOGGING", "true").lower() == "true"

# Настройка логгера
logging.basicConfig(
    level=getattr(logging, LOGGING_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)