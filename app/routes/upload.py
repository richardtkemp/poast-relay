import asyncio
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from app.config import Settings
from app.auth import verify_token, get_settings
from app.services.transcription import transcribe_audio
from app.services.gateway import send_to_gateway

logger = logging.getLogger(__name__)

# Valid audio file extensions and MIME types
VALID_EXTENSIONS = {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"}
VALID_MIME_TYPES = {
    "audio/flac",
    "audio/mpeg",
    "audio/mp4",
    "audio/mpga",
    "audio/m4a",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
}


def create_upload_router(settings: Settings) -> APIRouter:
    """Create upload router with dynamic path based on config."""
    router = APIRouter()

    @router.post("/{path_uuid}/upload")
    async def upload_audio(
        path_uuid: str,
        file: UploadFile = File(...),
        _: None = Depends(verify_token),
    ):
        """
        Upload and transcribe audio file.

        Args:
            path_uuid: Path UUID from URL (validated against config)
            file: Audio file to transcribe
            _: Authentication dependency (verify_token)

        Returns:
            JSON response with transcription status and text

        Raises:
            404: Invalid path UUID or (ghost mode + invalid token)
            400: Invalid file or format
            413: File too large
            502: Transcription or gateway error
        """
        # Validate path UUID
        if path_uuid != settings.inbound_path_uuid:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found",
            )

        # Validate file is present
        if not file or not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided",
            )

        # Get file extension
        filename_parts = file.filename.rsplit(".", 1)
        if len(filename_parts) != 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid filename. Supported formats: {', '.join(sorted(VALID_EXTENSIONS))}",
            )

        file_ext = f".{filename_parts[1].lower()}"

        # Validate file extension
        if file_ext not in VALID_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file format '{file_ext}'. Supported formats: {', '.join(sorted(VALID_EXTENSIONS))}",
            )

        # Validate MIME type
        if file.content_type and file.content_type not in VALID_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid MIME type '{file.content_type}'. Supported types: {', '.join(sorted(VALID_MIME_TYPES))}",
            )

        # Read file bytes
        try:
            audio_bytes = await file.read()
        except Exception as e:
            logger.error(f"Error reading file: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to read file",
            )

        # Validate file size
        if len(audio_bytes) > settings.max_upload_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {settings.max_upload_size_mb}MB",
            )

        # Validate file is not empty
        if len(audio_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File is empty",
            )

        # Process transcription and gateway send in background
        async def _process_audio(audio_data: bytes, filename: str, app_settings: Settings):
            try:
                logger.info(f"Transcribing file: {filename}")
                transcription = await transcribe_audio(audio_data, filename, app_settings)
                logger.info(f"Sending transcription to gateway")
                gateway_response = await send_to_gateway(transcription, app_settings)
                if gateway_response.get("status") != "sent":
                    logger.error(f"Gateway error: {gateway_response}")
                else:
                    logger.info(f"Successfully processed and relayed: {filename}")
            except Exception as e:
                logger.error(f"Background processing failed for {filename}: {str(e)}")

        asyncio.create_task(_process_audio(audio_bytes, file.filename, settings))

        return {"status": "accepted"}

    return router
