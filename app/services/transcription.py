import logging
from groq import Groq
from app.config import Settings

logger = logging.getLogger(__name__)


async def transcribe_audio(
    audio_file: bytes, filename: str, settings: Settings
) -> str:
    """
    Transcribe audio file using Groq's Whisper API.

    Args:
        audio_file: Raw audio file bytes
        filename: Name of the audio file
        settings: Application configuration

    Returns:
        Transcription text

    Raises:
        Exception: If Groq API call fails
    """
    client = Groq(api_key=settings.groq_api_key)

    try:
        # Determine MIME type from filename extension
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "ogg"
        mime_types = {
            "flac": "audio/flac",
            "mp3": "audio/mpeg",
            "mp4": "audio/mp4",
            "mpeg": "audio/mpeg",
            "mpga": "audio/mpga",
            "m4a": "audio/m4a",
            "ogg": "audio/ogg",
            "wav": "audio/wav",
            "webm": "audio/webm",
        }
        mime_type = mime_types.get(ext, "audio/ogg")

        # Call Groq Whisper API with file tuple (filename, contents, mime_type)
        transcript = client.audio.transcriptions.create(
            file=(filename, audio_file, mime_type),
            model="whisper-large-v3-turbo",
            timeout=settings.groq_timeout_seconds,
        )

        logger.info(f"Successfully transcribed audio file: {filename}")
        return transcript.text

    except Exception as e:
        logger.error(f"Groq transcription error for {filename}: {str(e)}")
        raise
