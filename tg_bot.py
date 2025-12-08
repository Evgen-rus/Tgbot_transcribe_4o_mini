"""
Telegram-бот для транскрибации аудио и голосовых сообщений.

Поддерживает:
- voice (OGG/OPUS от Telegram);
- audio/document с audio/* mime-типа (mp3, wav, m4a, ogg, webm, flac и т.д.).

Логика транскрибации использует существующие функции:
- voice байты → transcribe_voice
- файлы → transcribe_file_async (режет на части и отправляет параллельно)

Правила ответа:
- если итоговый текст <= 4096 символов — отправляем как текст;
- иначе — отправляем .txt файл с переносами строк.

Необходимые переменные окружения:
- TELEGRAM_BOT_TOKEN
- OPENAI_API_KEY (для транскрибации)
"""

import asyncio
import os
import tempfile
import textwrap
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

from audio_handler import transcribe_voice
from config import OPENAI_API_KEY, ALLOWED_CHAT_IDS, logger
from transcribe_core import transcribe_file_async

PROJECT_ROOT = Path(__file__).resolve().parent

# Лимит размера файла, который примет бот (Telegram обычно ~50 МБ для ботов)
MAX_FILE_SIZE = 50 * 1024 * 1024

# Ширина для читаемого вывода
WRAP_WIDTH = 80


def wrap_text(text: str, width: int = WRAP_WIDTH) -> str:
    """Переносит строки для читабельности, сохраняя пустые строки между абзацами."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")  # пустая строка как разделитель
            continue
        lines.append(textwrap.fill(stripped, width=width))
    return "\n".join(lines).strip()


def ensure_env() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в окружении/.env")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY не задан в окружении/.env")
    if not ALLOWED_CHAT_IDS:
        raise RuntimeError("TELEGRAM_CHAT_ID не задан или пуст — бот никого не будет обслуживать")
    return token


def is_allowed_chat(chat_id: int) -> bool:
    return chat_id in ALLOWED_CHAT_IDS


async def handle_voice(message: Message, bot: Bot) -> None:
    if not is_allowed_chat(message.chat.id):
        logger.warning(f"[tg] Доступ запрещён для чата {message.chat.id}")
        await message.answer("Этот бот недоступен в данном чате.")
        return

    voice = message.voice
    if not voice:
        await message.answer("Не удалось получить голосовое сообщение.")
        return

    if voice.file_size and voice.file_size > MAX_FILE_SIZE:
        await message.answer("Файл слишком большой. Ограничение ~50 МБ.")
        return

    file = await bot.get_file(voice.file_id)
    file_path = file.file_path

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False, dir=PROJECT_ROOT) as tmp:
        tmp_path = Path(tmp.name)

    notice = await message.answer(
        "Файл принят, начинаю транскрибацию. Если сообщение длинное, может потребоваться до пары минут."
    )

    try:
        await bot.download_file(file_path, destination=tmp_path)
        # Используем ту же логику, что и для файлов: она конвертирует через ffmpeg,
        # режет на сегменты и обрабатывает параллельно, что надёжнее для длинных voice.
        text = await transcribe_file_async(str(tmp_path))
    except Exception as e:  # noqa: BLE001
        logger.error(f"[tg] Ошибка при транскрибации voice: {e}")
        await message.answer("Произошла ошибка при транскрибации голосового сообщения.")
        return
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    await send_result(message, text, base_name="voice_transcription", progress_message=notice)


async def handle_audio_file(message: Message, bot: Bot) -> None:
    if not is_allowed_chat(message.chat.id):
        logger.warning(f"[tg] Доступ запрещён для чата {message.chat.id}")
        await message.answer("Этот бот недоступен в данном чате.")
        return

    # Поддерживаем audio и document с audio/* mime-type
    audio = message.audio
    document = message.document

    file_obj = audio or document
    if not file_obj:
        await message.answer("Отправьте аудио-файл или голосовое сообщение.")
        return

    if file_obj.file_size and file_obj.file_size > MAX_FILE_SIZE:
        await message.answer("Файл слишком большой. Ограничение ~50 МБ.")
        return

    if document and document.mime_type and not document.mime_type.startswith("audio/"):
        await message.answer("Документ не аудио. Пришлите аудио-файл.")
        return

    size_hint = file_obj.file_size or 0
    notice_text = "Файл принят, начинаю транскрибацию."
    if size_hint > 5 * 1024 * 1024:  # >5 МБ — предупредим, что может быть дольше
        notice_text += " Файл довольно большой, это может занять пару минут."
    notice = await message.answer(notice_text)

    file = await bot.get_file(file_obj.file_id)
    file_path = file.file_path

    suffix = Path(file_obj.file_name or "audio").suffix or ".audio"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=PROJECT_ROOT) as tmp:
        tmp_path = Path(tmp.name)

    try:
        await bot.download_file(file_path, destination=tmp_path)
        # Используем готовую логику разрезания и параллельной отправки
        text = await transcribe_file_async(str(tmp_path))
    except Exception as e:  # noqa: BLE001
        logger.error(f"[tg] Ошибка при транскрибации файла {tmp_path}: {e}")
        await message.answer("Произошла ошибка при транскрибации файла.")
        return
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    base_name = Path(file_obj.file_name or "audio").stem
    await send_result(message, text, base_name=base_name, progress_message=notice)


async def send_result(message: Message, text: str, base_name: str, progress_message: Message | None = None) -> None:
    """Отправляет результат: текстом, если он короткий, иначе .txt файл."""
    wrapped = wrap_text(text)
    if len(wrapped) <= 4096:
        if progress_message:
            try:
                await progress_message.edit_text("Готово. Отправляю результат:")
            except Exception:
                pass
        await message.answer(wrapped or "(пустой результат)")
        return

    with tempfile.NamedTemporaryFile(
        suffix=".txt",
        prefix=f"{base_name}_",
        delete=False,
        mode="w",
        encoding="utf-8",
        dir=PROJECT_ROOT,
    ) as tmp:
        tmp.write(wrapped)
        tmp_path = Path(tmp.name)

    try:
        if progress_message:
            try:
                await progress_message.edit_text("Готово. Результат отправлен файлом:")
            except Exception:
                pass
        await message.answer_document(FSInputFile(tmp_path, filename=f"{base_name}.txt"))
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


def setup_routes(dp: Dispatcher, bot: Bot) -> None:
    @dp.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        if not is_allowed_chat(message.chat.id):
            logger.warning(f"[tg] /start из неразрешённого чата {message.chat.id}")
            await message.answer("Этот бот недоступен в данном чате.")
            return
        await message.answer(
            "Отправь аудио или голосовое сообщение — верну транскрипцию.\n"
            "Короткие результаты — сразу текстом, длинные — файлом .txt."
        )

    @dp.message(F.voice)
    async def on_voice(message: Message) -> None:
        await handle_voice(message, bot)

    @dp.message(F.audio | F.document)
    async def on_audio_or_doc(message: Message) -> None:
        await handle_audio_file(message, bot)


async def main() -> None:
    token = ensure_env()
    bot = Bot(token=token)
    # Ограничим конкурентность обработки апдейтов бота:
    # - aiogram сам создаёт таски для хэндлеров; чтобы не плодить слишком много
    #   одновременных транскрипций, добавим лимит на уровень dp.
    #   Здесь max_tasks=5 — можно скорректировать при необходимости.
    dp = Dispatcher(max_concurrent_updates=5)
    setup_routes(dp, bot)

    logger.info("Запускаю Telegram-бота для транскрибации аудио")
    await dp.start_polling(bot, allowed_updates=["message"])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановка бота")

