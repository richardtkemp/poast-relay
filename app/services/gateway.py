import asyncio
import logging
import httpx
from app.config import Settings

logger = logging.getLogger(__name__)


async def send_to_gateway(text: str, settings: Settings) -> dict:
    """
    Send transcription text to Clawdbot Gateway.

    Implements retry logic with exponential backoff:
    - Retry up to GATEWAY_RETRY_ATTEMPTS times
    - Backoff: 1s, 2s, 4s between attempts
    - Only retry on network errors or 5xx responses
    - Don't retry on 4xx errors

    Args:
        text: Transcription text to send
        settings: Application configuration

    Returns:
        Gateway response as dict with status and details

    Raises:
        Exception: If all retry attempts fail
    """
    payload = {
        "tool": "sessions_send",
        "args": {
            "sessionKey": settings.target_session_key,
            "message": text,
        },
    }

    headers = {"Authorization": f"Bearer {settings.gateway_token}"}

    for attempt in range(settings.gateway_retry_attempts):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    settings.gateway_url,
                    json=payload,
                    headers=headers,
                    timeout=settings.gateway_timeout_seconds,
                )

                # Don't retry on 4xx errors (client errors)
                if 400 <= response.status_code < 500:
                    error_msg = f"Gateway client error {response.status_code}: {response.text}"
                    logger.error(error_msg)
                    return {
                        "status": "error",
                        "code": response.status_code,
                        "detail": error_msg,
                    }

                # Success
                if response.status_code < 300:
                    logger.info(f"Successfully sent transcription to gateway")
                    return {
                        "status": "sent",
                        "code": response.status_code,
                    }

                # 5xx errors - retry
                if response.status_code >= 500:
                    error_msg = f"Gateway server error {response.status_code}: {response.text}"
                    logger.warning(f"Attempt {attempt + 1}: {error_msg}")

                    if attempt < settings.gateway_retry_attempts - 1:
                        backoff = 2 ** attempt  # 1, 2, 4 seconds
                        logger.info(f"Retrying in {backoff} seconds...")
                        await asyncio.sleep(backoff)
                        continue
                    else:
                        logger.error(f"All retry attempts exhausted")
                        return {
                            "status": "error",
                            "code": response.status_code,
                            "detail": error_msg,
                        }

        except (httpx.NetworkError, httpx.TimeoutException) as e:
            error_msg = f"Gateway network error: {str(e)}"
            logger.warning(f"Attempt {attempt + 1}: {error_msg}")

            if attempt < settings.gateway_retry_attempts - 1:
                backoff = 2 ** attempt  # 1, 2, 4 seconds
                logger.info(f"Retrying in {backoff} seconds...")
                await asyncio.sleep(backoff)
                continue
            else:
                logger.error(f"All retry attempts exhausted")
                return {
                    "status": "error",
                    "detail": error_msg,
                }

    return {
        "status": "error",
        "detail": "Failed to send to gateway after all retry attempts",
    }
