from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration management using environment variables."""

    # Required fields
    inbound_path_uuid: str
    inbound_auth_token: str
    groq_api_key: str
    gateway_url: str
    gateway_token: str
    target_session_key: str

    # Optional fields with defaults
    ghost_mode: bool = False
    max_upload_size_mb: int = 100
    groq_timeout_seconds: int = 60
    gateway_timeout_seconds: int = 10
    gateway_retry_attempts: int = 3

    # OAuth Relay Configuration (all optional with defaults)
    oauth_enabled: bool = False
    oauth_callback_path: str = "/oauth/callback"
    oauth_code_keys: list[str] = ["code", "authorization_code"]
    oauth_socket_path: str = "/tmp/poast-relay-oauth.sock"
    oauth_tcp_fallback_port: int = 9999
    oauth_default_timeout: float = 300.0
    oauth_log_unmatched: bool = True
    oauth_use_tcp: bool = False
    oauth_tcp_bind_address: str = "127.0.0.1"
    oauth_tcp_host: str = "127.0.0.1"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    def validate_required_fields(self) -> None:
        """Validate all required fields are set on startup."""
        required_fields = [
            "inbound_path_uuid",
            "inbound_auth_token",
            "groq_api_key",
            "gateway_url",
            "gateway_token",
            "target_session_key",
        ]
        for field in required_fields:
            if not getattr(self, field, None):
                raise ValueError(f"Required configuration field '{field}' is not set")

        if self.oauth_enabled:
            import logging

            logger = logging.getLogger(__name__)
            logger.info("OAuth relay is enabled")

    @property
    def max_upload_size_bytes(self) -> int:
        """Convert max upload size from MB to bytes."""
        return self.max_upload_size_mb * 1024 * 1024
