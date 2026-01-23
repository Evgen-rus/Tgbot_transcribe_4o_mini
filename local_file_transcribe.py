"""
Локальный скрипт для транскрибации выбранного аудиофайла.

Логика транскрибации такая же, как у бота:
- файл конвертируется через ffmpeg;
- при необходимости режется на сегменты;
- результат сохраняется рядом с исходным аудио.
"""

import asyncio
from tkinter import Tk, filedialog

from config import logger
from transcribe_core import save_transcription, transcribe_file_async


def choose_audio_file() -> str | None:
    """
    Открывает диалог выбора файла и возвращает путь к выбранному файлу
    или None, если пользователь ничего не выбрал.
    """
    root = Tk()
    root.withdraw()
    root.update()

    filetypes = (
        ("Аудиофайлы", "*.wav *.mp3 *.ogg *.m4a *.flac *.webm"),
        ("Все файлы", "*.*"),
    )

    filepath = filedialog.askopenfilename(
        title="Выберите аудиофайл для транскрибации",
        filetypes=filetypes,
    )

    root.destroy()
    return filepath or None


def main() -> None:
    print("=== Локальная транскрибация аудиофайла ===")
    print("Сейчас откроется окно выбора файла.")

    filepath = choose_audio_file()
    if not filepath:
        print("Файл не выбран. Выходим.")
        return

    print(f"Вы выбрали файл: {filepath}")

    try:
        text = asyncio.run(transcribe_file_async(filepath))
    except Exception as e:
        logger.error(f"Ошибка при транскрибации файла: {e}")
        print(f"Ошибка транскрибации: {e}")
        return

    txt_path = save_transcription(text, filepath)
    print(f"Транскрипция сохранена в файл:\n{txt_path}")

    print("Готово.")


if __name__ == "__main__":
    main()
