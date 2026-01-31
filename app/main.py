import logging
from fastapi import FastAPI, HTTPException, status
from app.config import Settings
from app.routes.upload import create_upload_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize settings
settings = Settings()
settings.validate_required_fields()

# Create FastAPI app
app = FastAPI(
    title="Poast-Relay",
    description="Audio transcription proxy using Groq Whisper API and Clawdbot Gateway",
    version="1.0.0",
)

# Register upload router
upload_router = create_upload_router(settings)
app.include_router(upload_router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "Poast-Relay",
        "version": "1.0.0",
        "description": "Audio transcription proxy",
        "status": "running",
    }


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Log unhandled exceptions."""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal server error",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
