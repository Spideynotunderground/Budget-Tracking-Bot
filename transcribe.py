"""Speech-to-text via Groq's hosted Whisper.

Swapping this for local faster-whisper means reimplementing `transcribe()` only —
nothing else in the bot touches the transcription backend.
"""

import logging

from groq import AsyncGroq

from config import GROQ_API_KEY, GROQ_STT_MODEL

log = logging.getLogger(__name__)

_client = AsyncGroq(api_key=GROQ_API_KEY)


async def transcribe(audio: bytes, filename: str = "voice.ogg") -> str:
    """Return the transcript of a Telegram voice note (OGG/Opus)."""
    result = await _client.audio.transcriptions.create(
        file=(filename, audio),
        model=GROQ_STT_MODEL,
        response_format="text",
    )
    # response_format="text" yields a plain string, but the SDK may wrap it.
    text = result if isinstance(result, str) else getattr(result, "text", str(result))
    text = text.strip()
    log.info("transcribed %d bytes -> %r", len(audio), text)
    return text
