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
        # Call Groq Whisper API with file tuple (filename, contents, mime_type)
        # The Groq SDK will auto-detect the audio format from the file extension
        transcript = client.audio.transcriptions.create(
            file=(filename, audio_file),
            model="whisper-large-v3-turbo",
        )

        logger.info(f"Successfully transcribed audio file: {filename}")
        return transcript.text

    except Exception as e:
        logger.error(f"Groq transcription error for {filename}: {str(e)}")
        raise
