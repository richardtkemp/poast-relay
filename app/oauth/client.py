"""Public OAuth relay client API."""

import asyncio
import logging
import platform
from typing import Optional

from app.config import Settings
from app.oauth.models import MessageType, RelayResult, SocketMessage

logger = logging.getLogger(__name__)


class OAuthRelayError(Exception):
    """Base exception for OAuth relay errors."""

    pass


class OAuthTimeoutError(OAuthRelayError):
    """Timeout waiting for OAuth callback."""

    pass


class OAuthConnectionError(OAuthRelayError):
    """Failed to connect to OAuth relay coordinator."""

    pass


async def wait_for_code(
    state: Optional[str] = None,
    timeout: Optional[float] = None,
    settings: Optional[Settings] = None,
) -> RelayResult:
    """
    Wait for OAuth authorization code from relay server.

    This function connects to the local OAuth coordinator, registers for a callback,
    and blocks until the callback is delivered or timeout expires.

    Args:
        state: State parameter for multi-flow support (or None for single-slot mode)
        timeout: Maximum time to wait in seconds (uses settings.oauth_default_timeout if None)
        settings: Application settings object with oauth_* fields. If None, creates minimal
                 settings from OAUTH_* environment variables or sensible defaults.

    Returns:
        RelayResult with extracted code or raw payload

    Raises:
        OAuthTimeoutError: Timeout expired before callback arrived
        OAuthConnectionError: Failed to connect to relay coordinator
    """
    # Load settings if not provided (OAuth client only needs oauth_* fields, not full config)
    if settings is None:
        from types import SimpleNamespace
        import os

        # Create minimal settings from environment or defaults (no required field validation)
        settings = SimpleNamespace(
            oauth_socket_path=os.getenv("OAUTH_SOCKET_PATH", "/tmp/poast-relay-oauth.sock"),
            oauth_tcp_fallback_port=int(os.getenv("OAUTH_TCP_FALLBACK_PORT", "9999")),
            oauth_default_timeout=float(os.getenv("OAUTH_DEFAULT_TIMEOUT", "300.0")),
            oauth_use_tcp=os.getenv("OAUTH_USE_TCP", "false").lower() in ("true", "1", "yes"),
        )

    # Use provided timeout or settings default
    wait_timeout = timeout if timeout is not None else settings.oauth_default_timeout

    # Determine connection mode
    use_tcp = settings.oauth_use_tcp or platform.system() == "Windows"

    try:
        if use_tcp:
            # TCP connection
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", settings.oauth_tcp_fallback_port),
                timeout=10.0,
            )
        else:
            # Unix socket connection
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(settings.oauth_socket_path),
                timeout=10.0,
            )

    except asyncio.TimeoutError:
        raise OAuthConnectionError(
            f"Timeout connecting to OAuth coordinator (is the relay server running?)"
        )
    except ConnectionRefusedError:
        raise OAuthConnectionError(
            f"Cannot connect to OAuth coordinator on {settings.oauth_socket_path}"
        )
    except FileNotFoundError:
        raise OAuthConnectionError(
            f"OAuth coordinator socket not found at {settings.oauth_socket_path}"
        )
    except Exception as e:
        raise OAuthConnectionError(f"Failed to connect to OAuth coordinator: {e}")

    try:
        # Send registration message
        msg = SocketMessage(type=MessageType.REGISTER, state=state)
        writer.write(msg.to_json().encode())
        await writer.drain()

        logger.debug(f"Sent REGISTER message for state: {state!r}")

        # Wait for delivery message
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=wait_timeout)
        except asyncio.TimeoutError:
            raise OAuthTimeoutError(f"Timeout waiting for OAuth callback after {wait_timeout}s")

        if not line:
            raise OAuthRelayError("Coordinator closed connection without sending result")

        # Parse result message
        result_msg = SocketMessage.from_json(line.decode())

        if result_msg.type != MessageType.DELIVER:
            raise OAuthRelayError(f"Unexpected message type: {result_msg.type}")

        # Return result
        return RelayResult(code=result_msg.code, raw=result_msg.raw)

    finally:
        # Cleanup connection
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
