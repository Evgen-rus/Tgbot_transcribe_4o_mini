"""
Отдельный скрипт для транскрибации уже готового аудиофайла.

При запуске открывается окно выбора файла, затем файл отправляется
в OpenAI для распознавания, а результат сохраняется в .txt с датой и временем.

Дополнительно:
- Если аудио слишком длинное для одной отправки в модель, оно автоматически
  режется на безопасные куски и отправляется по частям.
"""

import asyncio
import io
import os
import subprocess
import tempfile
from datetime import datetime

from tkinter import Tk, filedialog, messagebox

import numpy as np
import soundfile as sf

from audio_handler import transcribe_voice
from config import logger

# Жёсткий лимит модели по длительности (по сообщению от OpenAI)
MODEL_MAX_SECONDS = 1400

# Безопасная длина одного куска: 15 минут (900 секунд), с запасом до лимита модели
SAFE_CHUNK_SECONDS = 900

# Небольшое перекрытие сегментов, чтобы сохранить связность на стыках (в секундах)
CHUNK_OVERLAP_SECONDS = 5


def choose_audio_file() -> str | None:
    """
    Открывает диалог выбора файла и возвращает путь к выбранному файлу
    или None, если пользователь ничего не выбрал.
    """
    # Создаём скрытое главное окно Tkinter только для диалога выбора файла
    root = Tk()
    root.withdraw()
    root.update()  # Обновляем, чтобы окно диалога корректно появилось поверх

    filetypes = (
        ("Аудиофайлы", "*.wav *.mp3 *.ogg *.m4a *.flac *.webm"),
        ("Все файлы", "*.*"),
    )

    filepath = filedialog.askopenfilename(
        title="Выберите аудиофайл для транскрибации",
        filetypes=filetypes,
    )

    root.destroy()

    # Если пользователь нажал «Отмена», вернём None
    return filepath or None


async def transcribe_file_async(
    filepath: str,
    max_segment_concurrency: int = 3,
    chunk_overlap_seconds: int = CHUNK_OVERLAP_SECONDS,
) -> str:
    """
    Асинхронно транскрибирует аудиофайл.

    Если файл по длительности больше безопасного лимита, он автоматически
    режется на части и отправляется в OpenAI по кускам. Куски могут
    обрабатываться параллельно (ограничено max_segment_concurrency), но
    в итоговом тексте порядок сохраняется.
    """
    logger.info(f"Открываю файл для транскрибации: {filepath}")

    base_name = os.path.splitext(os.path.basename(filepath))[0]

    # 1. Конвертируем исходный файл в WAV (16 кГц, моно) с помощью ffmpeg
    #    Это нужно, чтобы дальше удобно резать аудио по сэмплам через soundfile.
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        tmp_wav_path = tmp_wav.name

    ffmpeg_cmd = [
        "ffmpeg",
        "-y",  # перезаписать, если файл уже существует
        "-i",
        filepath,
        "-ac",
        "1",  # моно
        "-ar",
        "16000",  # частота дискретизации 16 кГц
        "-acodec",
        "pcm_s16le",  # 16-бит PCM
        tmp_wav_path,
    ]

    logger.info(f"Конвертирую аудио в WAV через ffmpeg: {' '.join(ffmpeg_cmd)}")
    try:
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        logger.error(f"Ошибка при конвертации аудио через ffmpeg: {e}")
        raise RuntimeError(
            "Не удалось конвертировать аудио через ffmpeg. "
            "Убедитесь, что ffmpeg установлен и доступен в PATH."
        ) from e

    try:
        # 2. Читаем сконвертированный WAV через soundfile
        data, samplerate = sf.read(tmp_wav_path, dtype="int16")
    except Exception as e:
        logger.error(f"Ошибка при чтении сконвертированного WAV: {e}")
        # В любом случае удалим временный файл
        try:
            os.remove(tmp_wav_path)
        except Exception:
            pass
        raise

    # Удаляем временный файл после чтения, он больше не нужен
    try:
        os.remove(tmp_wav_path)
    except Exception:
        # Не критично, если удалить не удалось
        pass

    # Приводим данные к numpy-массиву (на случай, если это уже не ndarray)
    data = np.asarray(data)

    total_samples = data.shape[0]
    duration_sec = total_samples / float(samplerate)
    logger.info(f"Длительность аудио после конвертации: {duration_sec:.2f} секунд")

    samples_per_chunk = SAFE_CHUNK_SECONDS * samplerate
    overlap_samples = max(0, int(chunk_overlap_seconds * samplerate))

    if duration_sec <= SAFE_CHUNK_SECONDS:
        logger.info("Аудио короче безопасного лимита, отправляю одним куском")

    texts: list[tuple[int, str]] = []

    # Считаем количество сегментов
    total_chunks = max(1, (total_samples + samples_per_chunk - 1) // samples_per_chunk)
    semaphore = asyncio.Semaphore(max(1, max_segment_concurrency))

    async def process_chunk(idx: int, start_sample: int, end_sample: int) -> None:
        chunk_data = data[start_sample:end_sample]
        if chunk_data.size == 0:
            logger.warning(f"Сегмент {idx + 1} пустой, пропускаю")
            return

        chunk_duration_sec = (end_sample - start_sample) / float(samplerate)
        start_time_sec = start_sample / float(samplerate)
        end_time_sec = end_sample / float(samplerate)

        logger.info(
            f"Готовлю сегмент {idx + 1}/{total_chunks}: "
            f"{start_time_sec:.1f}–{end_time_sec:.1f} сек "
            f"({chunk_duration_sec:.1f} сек)"
        )

        # 3. Пишем сегмент во временный WAV в память (байтовый поток)
        buffer = io.BytesIO()
        sf.write(buffer, chunk_data, samplerate, format="WAV", subtype="PCM_16")
        buffer.seek(0)
        wav_bytes = buffer.read()

        if not wav_bytes:
            logger.warning(f"Сегмент {idx + 1} пустой после записи в WAV, пропускаю")
            return

        segment_file_name = f"{base_name}_part_{idx + 1}.wav"
        logger.info(
            f"Отправляю сегмент {idx + 1}/{total_chunks} в модель: {segment_file_name}"
        )

        try:
            async with semaphore:
                segment_text = await transcribe_voice(
                    wav_bytes,
                    file_name=segment_file_name,
                    language="ru",
                )
        except Exception as e:  # noqa: BLE001 — хотим залогировать и продолжить другие сегменты
            logger.error(f"Ошибка при транскрибации сегмента {idx + 1}: {e}")
            return

        header = (
            f"[Сегмент {idx + 1}/{total_chunks} "
            f"({start_time_sec:.1f}–{end_time_sec:.1f} сек)]"
        )
        texts.append((idx, f"{header}\n{segment_text}"))

    tasks = []
    for idx in range(total_chunks):
        start_sample = max(0, idx * samples_per_chunk - overlap_samples if idx > 0 else 0)
        end_sample = min(start_sample + samples_per_chunk, total_samples)
        tasks.append(asyncio.create_task(process_chunk(idx, start_sample, end_sample)))

    # Дожидаемся всех сегментов
    if tasks:
        await asyncio.gather(*tasks)

    if not texts:
        raise ValueError("Не удалось получить текст ни из одного сегмента")

    # Сохраняем порядок согласно исходной нумерации сегментов
    texts.sort(key=lambda item: item[0])
    full_text = "\n\n".join([item[1] for item in texts])
    return full_text


def save_transcription(text: str, original_filepath: str) -> str:
    """
    Сохраняет транскрибацию в .txt-файл рядом с исходным аудио.

    Имя файла: <имя_аудио>_transcription_YYYY-MM-DD_HH-MM-SS.txt
    Возвращает путь к созданному файлу.
    """
    base_dir = os.path.dirname(original_filepath)
    base_name = os.path.splitext(os.path.basename(original_filepath))[0]

    # Дата и время в имени файла, чтобы файлы не перезаписывались
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    txt_name = f"{base_name}_transcription_{timestamp}.txt"
    txt_path = os.path.join(base_dir, txt_name)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)

    logger.info(f"Транскрипция сохранена в файл: {txt_path}")
    return txt_path


def main() -> None:
    """
    Главная функция:
    1) Показывает окно выбора файла
    2) Отправляет файл в транскрибацию
    3) Сохраняет результат в .txt
    """
    print("=== Транскрибация аудиофайла (Speech2Cursor) ===")
    print("Сейчас откроется окно выбора файла.")

    filepath = choose_audio_file()
    if not filepath:
        print("Файл не выбран. Выходим.")
        return

    print(f"Вы выбрали файл: {filepath}")

    try:
        # Запускаем асинхронную транскрибацию в синхронном скрипте
        text = asyncio.run(transcribe_file_async(filepath))
    except Exception as e:
        logger.error(f"Ошибка при транскрибации файла: {e}")
        # Покажем также всплывающее окно, чтобы было нагляднее
        try:
            messagebox.showerror("Ошибка транскрибации", str(e))
        except Exception:
            # Если Tkinter по какой-то причине не может показать сообщение,
            # просто игнорируем это и остаёмся в консоли.
            pass
        print(f"Ошибка транскрибации: {e}")
        return

    print("\nРаспознанный текст:")
    print("-" * 40)
    print(text)
    print("-" * 40)

    # Сохраняем результат в текстовый файл
    txt_path = save_transcription(text, filepath)
    print(f"\nТранскрипция сохранена в файл:\n{txt_path}")

    # Небольшое окно-подтверждение (если запущено из проводника, чтобы было видно результат)
    try:
        messagebox.showinfo("Готово", f"Текст сохранён в файл:\n{txt_path}")
    except Exception:
        pass


if __name__ == "__main__":
    main()


