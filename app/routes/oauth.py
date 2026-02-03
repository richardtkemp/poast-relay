"""OAuth relay callback endpoint."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse

from app.config import Settings
from app.oauth.coordinator import get_coordinator

logger = logging.getLogger(__name__)

# Beautiful HTML response for browser
SUCCESS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Authorization Complete</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
        }
        .container {
            text-align: center;
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            max-width: 400px;
        }
        h1 {
            color: #333;
            margin-top: 0;
            font-size: 28px;
        }
        p {
            color: #666;
            font-size: 16px;
            line-height: 1.5;
        }
        .checkmark {
            width: 60px;
            height: 60px;
            margin: 0 auto 20px;
            background: #4CAF50;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 32px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="checkmark">✓</div>
        <h1>Authorization Complete</h1>
        <p>You can safely close this tab now.</p>
    </div>
</body>
</html>"""

ERROR_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Authorization Failed</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
        }
        .container {
            text-align: center;
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            max-width: 400px;
        }
        h1 {
            color: #333;
            margin-top: 0;
            font-size: 28px;
        }
        p {
            color: #666;
            font-size: 16px;
            line-height: 1.5;
        }
        .error-icon {
            width: 60px;
            height: 60px;
            margin: 0 auto 20px;
            background: #f44336;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 32px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="error-icon">✕</div>
        <h1>Authorization Failed</h1>
        <p>No client is waiting for this authorization. Please try again.</p>
    </div>
</body>
</html>"""


def extract_code(data: Dict[str, Any], code_keys: list[str]) -> Optional[str]:
    """
    Extract authorization code using case-insensitive key matching.

    Args:
        data: Dictionary of parameters
        code_keys: List of possible code key names

    Returns:
        Extracted code string or None if not found
    """
    lower_data = {k.lower(): v for k, v in data.items()}
    for candidate in code_keys:
        candidate_lower = candidate.lower()
        if candidate_lower in lower_data:
            value = lower_data[candidate_lower]
            # Handle list values (take first element)
            if isinstance(value, list) and value:
                return str(value[0])
            return str(value) if value else None
    return None


def create_oauth_router(settings: Settings) -> APIRouter:
    """
    Create OAuth callback router.

    Args:
        settings: Application settings

    Returns:
        Configured APIRouter
    """
    router = APIRouter()

    @router.get(settings.oauth_callback_path)
    async def oauth_callback_get(request: Request):
        """Handle GET OAuth callbacks (query parameters)."""
        coordinator = get_coordinator()
        if not coordinator:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OAuth coordinator not initialized",
            )

        # Extract parameters
        data = dict(request.query_params)
        state = data.get("state")
        code = extract_code(data, settings.oauth_code_keys)

        # Deliver to waiting client or return 404
        delivered = coordinator.deliver_result(state, code, data if not code else None)

        if delivered:
            return HTMLResponse(SUCCESS_HTML, status_code=status.HTTP_200_OK)
        else:
            return HTMLResponse(ERROR_HTML, status_code=status.HTTP_404_NOT_FOUND)

    @router.post(settings.oauth_callback_path)
    async def oauth_callback_post(request: Request):
        """Handle POST OAuth callbacks (form or JSON body)."""
        coordinator = get_coordinator()
        if not coordinator:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OAuth coordinator not initialized",
            )

        # Parse body based on content type
        content_type = request.headers.get("content-type", "").lower()
        data = {}

        try:
            if "application/json" in content_type:
                data = await request.json()
            elif "application/x-www-form-urlencoded" in content_type:
                form_data = await request.form()
                data = dict(form_data)
            else:
                # Try JSON first, fall back to form
                try:
                    data = await request.json()
                except Exception:
                    form_data = await request.form()
                    data = dict(form_data)
        except Exception as e:
            logger.error(f"Error parsing OAuth callback body: {e}")
            return HTMLResponse(ERROR_HTML, status_code=status.HTTP_400_BAD_REQUEST)

        # Extract parameters
        state = data.get("state")
        code = extract_code(data, settings.oauth_code_keys)

        # Deliver to waiting client or return 404
        delivered = coordinator.deliver_result(state, code, data if not code else None)

        if delivered:
            return HTMLResponse(SUCCESS_HTML, status_code=status.HTTP_200_OK)
        else:
            return HTMLResponse(ERROR_HTML, status_code=status.HTTP_404_NOT_FOUND)

    return router
