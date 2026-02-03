"""OAuth relay coordinator - manages client registrations and callback delivery."""

import asyncio
import json
import logging
import os
import platform
from typing import Dict, Optional
from asyncio import Future, Server

from app.config import Settings
from app.oauth.models import MessageType, SocketMessage, RelayResult

logger = logging.getLogger(__name__)

# Global coordinator instance
_coordinator: Optional["OAuthCoordinator"] = None


def get_coordinator() -> Optional["OAuthCoordinator"]:
    """Get global coordinator instance."""
    return _coordinator


def set_coordinator(coordinator: Optional["OAuthCoordinator"]) -> None:
    """Set global coordinator instance."""
    global _coordinator
    _coordinator = coordinator


class OAuthCoordinator:
    """Coordinates OAuth callback delivery between clients and provider."""

    def __init__(self, settings: Settings):
        """
        Initialize coordinator.

        Args:
            settings: Application settings
        """
        self.settings = settings
        self.pending: Dict[str, Future[SocketMessage]] = {}
        self.server: Optional[Server] = None
        self.use_tcp = settings.oauth_use_tcp or platform.system() == "Windows"

    async def start(self) -> None:
        """Start the socket server (Unix or TCP)."""
        try:
            if self.use_tcp:
                # TCP server for Windows or explicit TCP mode
                self.server = await asyncio.start_server(
                    self._handle_client, "127.0.0.1", self.settings.oauth_tcp_fallback_port
                )
                addr = self.server.sockets[0].getsockname()
                logger.info(f"OAuth coordinator listening on TCP {addr[0]}:{addr[1]}")
            else:
                # Unix socket server for Linux/macOS
                socket_path = self.settings.oauth_socket_path
                # Remove existing socket file if it exists
                if os.path.exists(socket_path):
                    os.remove(socket_path)

                self.server = await asyncio.start_unix_server(
                    self._handle_client, socket_path
                )
                logger.info(f"OAuth coordinator listening on {socket_path}")

            # Serve forever (this is a background coroutine)
            await self.server.serve_forever()
        except asyncio.CancelledError:
            logger.info("OAuth coordinator cancelled")
        except Exception as e:
            logger.error(f"Failed to start OAuth coordinator: {e}")
            raise

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """
        Handle individual client connection.

        Args:
            reader: StreamReader for incoming data
            writer: StreamWriter for outgoing data
        """
        peer = writer.get_extra_info("peername")
        try:
            # Read registration message
            line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            if not line:
                logger.warning(f"Client {peer} closed connection without sending data")
                return

            msg = SocketMessage.from_json(line.decode())
            if msg.type != MessageType.REGISTER:
                logger.warning(f"Client {peer} sent non-REGISTER message first")
                writer.close()
                return

            state = msg.state or "__default__"
            logger.info(f"Client registered for state: {state!r}")

            # Create or replace future for this state
            future: Future[SocketMessage] = asyncio.Future()

            # Cancel any existing future for this state
            if state in self.pending:
                old_future = self.pending[state]
                if not old_future.done():
                    old_future.cancel()
                    logger.info(f"Cancelled previous registration for state: {state!r}")

            self.pending[state] = future

            # Wait for delivery or timeout
            try:
                result = await asyncio.wait_for(
                    future, timeout=self.settings.oauth_default_timeout
                )
                # Send result to client
                writer.write(result.to_json().encode())
                await writer.drain()
                logger.info(f"OAuth callback delivered to client for state: {state!r}")

            except asyncio.TimeoutError:
                logger.warning(f"OAuth callback timeout for state: {state!r}")
            except asyncio.CancelledError:
                logger.info(f"OAuth registration cancelled for state: {state!r}")
            finally:
                # Cleanup
                if state in self.pending and self.pending[state] is future:
                    del self.pending[state]
                writer.close()

        except Exception as e:
            logger.error(f"Error handling client {peer}: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def deliver_result(
        self, state: Optional[str], code: Optional[str], raw: Optional[dict] = None
    ) -> bool:
        """
        Deliver callback result to waiting client.

        Args:
            state: State parameter (or None for single-slot mode)
            code: Extracted code (or None if extraction failed)
            raw: Full callback payload (used if code extraction failed)

        Returns:
            True if delivered to waiting client, False if no client registered or already delivered
        """
        state_key = state or "__default__"

        # Check if client is waiting
        if state_key not in self.pending:
            if self.settings.oauth_log_unmatched:
                logger.warning(f"No client waiting for state {state_key!r} - dropping callback")
            return False

        future = self.pending[state_key]

        # Check if future is already resolved
        if future.done():
            logger.warning(f"Callback already delivered for state {state_key!r} - dropping replay")
            return False

        # Resolve the future
        msg = SocketMessage(type=MessageType.DELIVER, state=state, code=code, raw=raw)
        future.set_result(msg)

        return True

    async def stop(self) -> None:
        """Shutdown coordinator and cleanup."""
        # Cancel all pending futures
        for state, future in list(self.pending.items()):
            if not future.done():
                future.cancel()
                logger.info(f"Cancelled pending registration for state: {state!r}")

        # Stop server
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("OAuth coordinator stopped")

        # Clean up Unix socket
        if not self.use_tcp:
            socket_path = self.settings.oauth_socket_path
            try:
                if os.path.exists(socket_path):
                    os.remove(socket_path)
                    logger.info(f"Cleaned up socket {socket_path}")
            except Exception as e:
                logger.error(f"Error removing socket {socket_path}: {e}")
