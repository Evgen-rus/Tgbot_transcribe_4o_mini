# Speech2Cursor — транскрибация аудио и Telegram-бот

Коротко
- Транскрибирует аудио/voice через OpenAI; длинные файлы режет на сегменты с overlap и склеивает в порядке.
- Режимы: одиночный (`file_transcribe.py`), пакетный (`file_transcribe_batch.py`), Telegram-бот (`tg_bot.py`).
- Ответы: текст (до 4096 символов) или `.txt` при больших объёмах.

Требования
- Python 3.10+
- ffmpeg в PATH
- Учётки/ключи: `OPENAI_API_KEY`, модель `TRANSCRIPTION_MODEL` (по умолчанию `gpt-4o-mini-transcribe`), для бота `TELEGRAM_BOT_TOKEN`.

Установка
```
python -m venv venv
venv\Scripts\activate   # Windows
pip install -r requirements.txt

# Linux/macOS
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Настройка окружения
Создайте `.env` (можно по образцу `.env.example`):
```
OPENAI_API_KEY=...
TRANSCRIPTION_MODEL=gpt-4o-mini-transcribe
LOG_LEVEL=INFO
ENABLE_DIALOG_LOGGING=true
TELEGRAM_BOT_TOKEN=...   # нужно только для tg_bot.py
```

Запуск
- Одиночный файл (GUI выбор, сохраняет txt рядом):
```
python file_transcribe.py
```
- Batch (GUI выбор нескольких файлов, отдельные txt + общий сводный):
```
python file_transcribe_batch.py
```
- Telegram-бот (polling):
```
python tg_bot.py
```
Бот: отправьте voice или аудио (audio/document с `audio/*`), в ответ получите текст (<=4096 симв) либо `.txt`. Для крупных файлов покажет, что может занять пару минут.

Примечания
- Лимит Telegram на файл ~50 МБ.
- Нужен установленный ffmpeg; иначе конвертация упадёт.
- Лицензия: MIT (текст лицензии не включён; используйте стандартный MIT при необходимости).

