"""
Скрипт для массовой транскрибации уже готовых аудиофайлов.

Работает так:
- Показывает окно выбора файлов (можно выбрать сразу несколько аудио);
- Каждый файл по очереди отправляется в OpenAI для распознавания;
- Результат каждого файла сохраняется в отдельный .txt рядом с исходным аудио
  (как в одиночном скрипте file_transcribe.py).

Для транскрибации используется уже готовая асинхронная функция
`transcribe_file_async` из `file_transcribe.py`, чтобы не дублировать логику.
"""

import asyncio
import os
from datetime import datetime

from tkinter import Tk, filedialog, messagebox

from config import logger
from file_transcribe import transcribe_file_async, save_transcription


def choose_audio_files() -> list[str]:
    """
    Открывает диалог выбора нескольких файлов и возвращает список путей.

    Если пользователь ничего не выбрал — возвращает пустой список.
    """
    root = Tk()
    root.withdraw()
    root.update()  # Обновляем, чтобы окно диалога корректно появилось поверх

    filetypes = (
        ("Аудиофайлы", "*.wav *.mp3 *.ogg *.m4a *.flac *.webm"),
        ("Все файлы", "*.*"),
    )

    filepaths = filedialog.askopenfilenames(
        title="Выберите аудиофайлы для массовой транскрибации",
        filetypes=filetypes,
    )

    root.destroy()

    # `askopenfilenames` всегда возвращает кортеж, даже если ничего не выбрано.
    # Приводим к списку.
    return list(filepaths)


def remove_segment_headers(text: str) -> str:
    """
    Убирает строки вида "[Сегмент 1/1 (0.0–15.7 сек)]" из текста.
    Это нужно, чтобы в массовом режиме эти служебные заголовки не попадали
    ни в отдельные файлы, ни в общий итоговый файл.
    """
    lines = text.splitlines()
    cleaned_lines: list[str] = []
    for line in lines:
        # Простая эвристика: заголовки сегментов всегда начинаются с "[Сегмент"
        if line.startswith("[Сегмент") and line.endswith("]"):
            continue
        cleaned_lines.append(line)

    # Убираем ведущие и хвостовые пустые строки
    return "\n".join(cleaned_lines).strip()


async def transcribe_files_concurrent(filepaths: list[str], max_concurrency: int = 3) -> None:
    """
    Параллельно транскрибирует файлы с ограничением по количеству одновременных задач.
    
    Порядок в итоговом общем файле сохраняется в соответствии с порядком выбора.
    """
    total = len(filepaths)
    success_count = 0
    error_count = 0
    combined_entries: list[tuple[int, str, str]] = []
    semaphore = asyncio.Semaphore(max_concurrency)

    async def process_file(idx: int, filepath: str) -> None:
        nonlocal success_count, error_count

        print(f"\n=== Файл {idx}/{total} ===")
        print(f"Транскрибирую: {filepath}")
        logger.info(f"[batch] Начинаю транскрибацию файла {idx}/{total}: {filepath}")

        try:
            async with semaphore:
                raw_text = await transcribe_file_async(filepath)
            text = remove_segment_headers(raw_text)
        except Exception as e:  # noqa: BLE001 — хотим поймать любую ошибку, чтобы не падать
            error_count += 1
            logger.error(f"[batch] Ошибка при транскрибации файла {filepath}: {e}")
            print(f"Ошибка при транскрибации этого файла: {e}")
            return

        combined_entries.append((idx, filepath, text))

        print("Распознанный текст (начало):")
        print("-" * 40)
        preview = text[:1000]
        print(preview)
        if len(text) > len(preview):
            print("... (остальной текст сохранён в файл)")
        print("-" * 40)

        txt_path = save_transcription(text, filepath)
        success_count += 1
        print(f"Транскрипция сохранена в файл:\n{txt_path}")

    tasks = [
        asyncio.create_task(process_file(idx, filepath))
        for idx, filepath in enumerate(filepaths, start=1)
    ]
    await asyncio.gather(*tasks)

    combined_entries.sort(key=lambda item: item[0])

    combined_path: str | None = None
    if combined_entries:
        first_dir = os.path.dirname(combined_entries[0][1]) or "."
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        combined_name = f"batch_transcription_{timestamp}.txt"
        combined_path = os.path.join(first_dir, combined_name)

        with open(combined_path, "w", encoding="utf-8") as f:
            for entry_idx, (_, file_path, text) in enumerate(combined_entries):
                base_name = os.path.basename(file_path)
                f.write(base_name + "\n\n")
                f.write(text.strip() + "\n")
                if entry_idx != len(combined_entries) - 1:
                    f.write("\n")

    summary_lines = [
        f"Обработано файлов: {total}",
        f"Успешно: {success_count}",
        f"С ошибками: {error_count}",
    ]
    if combined_path is not None:
        summary_lines.append(f"Общий файл со всеми транскрипциями:\n{combined_path}")

    summary = "\n".join(summary_lines)

    print("\n=== Массовая транскрибация завершена ===")
    print(summary)

    try:
        messagebox.showinfo("Массовая транскрибация завершена", summary)
    except Exception:
        pass


def main() -> None:
    """
    Главная функция массовой транскрибации:
    1) Показывает окно выбора нескольких файлов;
    2) Параллельно (с ограничением) транскрибирует каждый файл;
    3) Сохраняет результат каждого файла в отдельный .txt.
    """
    print("=== Массовая транскрибация аудиофайлов (Speech2Cursor) ===")
    print("Сейчас откроется окно выбора ОДНОГО или НЕСКОЛЬКИХ файлов.")

    filepaths = choose_audio_files()
    if not filepaths:
        print("Файлы не выбраны. Выходим.")
        return

    print("\nВы выбрали следующие файлы для транскрибации:")
    for path in filepaths:
        print(f"- {path}")

    asyncio.run(transcribe_files_concurrent(filepaths))


if __name__ == "__main__":
    main()


