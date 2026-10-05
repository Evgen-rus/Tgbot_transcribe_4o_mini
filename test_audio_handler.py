"""Offline request-contract check: python test_audio_handler.py."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Do not load real credentials for this check.
os.environ["OPENAI_API_KEY"] = "offline-test"

import audio_handler


async def check():
    create = AsyncMock(return_value=SimpleNamespace(text="transcript"))
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    with patch.object(audio_handler, "client", client):
        for model in ("gpt-transcribe", "gpt-4o-mini-transcribe"):
            with patch.object(audio_handler, "TRANSCRIPTION_MODEL", model):
                create.reset_mock()
                assert await audio_handler.transcribe_voice(b"audio", "sample.wav", "ru") == "transcript"
                kwargs = create.call_args.kwargs
                assert kwargs["model"] == model
                assert kwargs["file"] == ("sample.wav", b"audio")
                if model == "gpt-transcribe":
                    assert kwargs["extra_body"] == {"languages": ["ru"]}
                    assert "language" not in kwargs
                else:
                    assert kwargs["language"] == "ru"
                    assert "extra_body" not in kwargs

        with patch.object(audio_handler, "TRANSCRIPTION_MODEL", "gpt-transcribe"):
            create.reset_mock()
            create.side_effect = RuntimeError("invalid model ID")
            try:
                await audio_handler.transcribe_voice(b"audio")
            except RuntimeError:
                pass
            else:
                raise AssertionError("Model error must propagate")
            assert create.await_count == 1


if __name__ == "__main__":
    asyncio.run(check())
    print("OK: model, language hints, text result, no gpt-transcribe fallback")
