from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials
from app.config import Settings

security = HTTPBearer()


def get_settings() -> Settings:
    """Get settings instance. Can be overridden for testing."""
    settings = Settings()
    settings.validate_required_fields()
    return settings


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    settings: Settings = Depends(get_settings),
) -> None:
    """
    Verify bearer token matches configured inbound auth token.

    If invalid:
    - Ghost mode ON: Return 404 Not Found (hide service existence)
    - Ghost mode OFF: Return 401 Unauthorized
    """
    if credentials.credentials != settings.inbound_auth_token:
        if settings.ghost_mode:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Not found",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token",
            )
