"""Speech-to-Text service using OpenAI Whisper."""

import os
import tempfile
import aiohttp

from src.config import get_settings
from src.utils.logger import logger


async def transcribe_voice(file_path: str) -> str:
    """Transcribe voice message using OpenAI Whisper API."""
    settings = get_settings()

    async with aiohttp.ClientSession() as session:
        with open(file_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field(
                "file", f, filename="voice.ogg", content_type="audio/ogg"
            )
            data.add_field("model", "whisper-1")
            data.add_field("language", "ru")

            async with session.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                data=data,
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Whisper API error: {resp.status} - {error_text}")
                    raise Exception(f"Whisper API error: {resp.status}")

                result = await resp.json()
                return result["text"]


async def download_and_transcribe(bot, file_id: str) -> str:
    """Download voice from Telegram and transcribe it."""
    # Download file from Telegram
    file = await bot.get_file(file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await file.download_to_drive(tmp_path)
        transcript = await transcribe_voice(tmp_path)
        return transcript
    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
