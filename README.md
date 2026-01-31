# Poast-Relay

Audio transcription proxy that receives audio files, transcribes them using Groq's Whisper API, and relays the transcription to a Clawdbot Gateway session.

## Features

- **Audio Transcription**: Uses Groq's Whisper-large-v3 model for accurate transcription
- **Gateway Integration**: Automatically sends transcriptions to a Clawdbot Gateway session
- **Security**: Bearer token authentication with optional ghost mode
- **Retry Logic**: Exponential backoff for gateway communication
- **Docker Ready**: Container definition included for easy deployment
- **Validation**: File format, size, and MIME type validation

## Prerequisites

- Docker and Docker Compose, OR
- Python 3.11+
- Groq API key (get at https://console.groq.com)
- Access to Clawdbot Gateway instance

## Configuration

### Environment Variables

Create a `.env` file based on `.env.example`:

**Required:**
- `INBOUND_PATH_UUID`: Unique UUID for this service endpoint (e.g., `d8a1b2c3-4e5f-6a7b-8c9d-0e1f2a3b4c5d`)
- `INBOUND_AUTH_TOKEN`: Bearer token for incoming upload requests
- `GROQ_API_KEY`: Your Groq API key
- `GATEWAY_URL`: Clawdbot Gateway endpoint (default: `http://192.168.1.150:18790/tools/invoke`)
- `GATEWAY_TOKEN`: Bearer token for gateway authentication
- `TARGET_SESSION_KEY`: Session key to receive transcriptions

**Optional (with defaults):**
- `GHOST_MODE`: Return 404 instead of 401 for invalid auth (default: `false`)
- `MAX_UPLOAD_SIZE_MB`: Maximum audio file size (default: `100`)
- `GROQ_TIMEOUT_SECONDS`: Groq API timeout (default: `60`)
- `GATEWAY_TIMEOUT_SECONDS`: Gateway request timeout (default: `10`)
- `GATEWAY_RETRY_ATTEMPTS`: Retry attempts for gateway (default: `3`)

### Example Configuration

```bash
INBOUND_PATH_UUID=secret-uuid-12345
INBOUND_AUTH_TOKEN=secret-inbound-token
GROQ_API_KEY=gsk_xxxxx
GATEWAY_URL=http://192.168.1.150:18790/tools/invoke
GATEWAY_TOKEN=secret-gateway-token
TARGET_SESSION_KEY=my-session-123
```

## Local Development

1. **Clone the repository**:
   ```bash
   git clone <repo-url>
   cd poast-relay
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

5. **Run the application**:
   ```bash
   uvicorn app.main:app --reload
   ```

   The service will be available at `http://localhost:8000`

## Docker Build and Run

### Build the image:
```bash
docker build -t poast-relay:latest .
```

### Run the container:
```bash
docker run \
  --env-file .env \
  -p 8000:8000 \
  --name poast-relay \
  poast-relay:latest
```

### Using Docker Compose:
```yaml
version: '3'
services:
  poast-relay:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

## API Usage

### Health Check
```bash
curl http://localhost:8000/health
```

Response:
```json
{"status": "ok"}
```

### Upload and Transcribe Audio

Replace `{path_uuid}` with your configured `INBOUND_PATH_UUID` and `{token}` with your `INBOUND_AUTH_TOKEN`.

```bash
curl -X POST \
  http://localhost:8000/{path_uuid}/upload \
  -H "Authorization: Bearer {token}" \
  -F "file=@/path/to/audio.mp3"
```

**Success Response (200)**:
```json
{
  "status": "sent",
  "text": "Transcribed text from the audio file"
}
```

**Invalid Token (401 or 404)**:
```json
{"detail": "Invalid authentication token"}
```

**File Too Large (413)**:
```json
{"detail": "File too large. Maximum size is 100MB"}
```

**Invalid Format (400)**:
```json
{"detail": "Unsupported file format '.txt'. Supported formats: .flac, .m4a, .mp3, .mp4, .mpeg, .mpga, .ogg, .wav, .webm"}
```

**Transcription Error (502)**:
```json
{"detail": "Error processing request: <error details>"}
```

### Supported Audio Formats

- `.flac` - FLAC audio
- `.mp3` - MP3 audio
- `.mp4` - MP4 audio container
- `.mpeg` - MPEG audio
- `.mpga` - MPEG audio (alternative extension)
- `.m4a` - MPEG-4 audio
- `.ogg` - OGG audio
- `.wav` - WAV audio
- `.webm` - WebM audio

### Example using Python

```python
import requests

url = "http://localhost:8000/{path_uuid}/upload"
headers = {"Authorization": "Bearer {token}"}

with open("audio.mp3", "rb") as f:
    files = {"file": f}
    response = requests.post(url, headers=headers, files=files)

print(response.json())
```

## Coolify Deployment

1. **Create a new service** in Coolify:
   - Project: `home-server`
   - Environment: `dev`
   - Source: Docker image from this repository

2. **Set environment variables** in Coolify dashboard:
   - `INBOUND_PATH_UUID`
   - `INBOUND_AUTH_TOKEN`
   - `GROQ_API_KEY`
   - `GATEWAY_URL`
   - `GATEWAY_TOKEN`
   - `TARGET_SESSION_KEY`
   - Optionally: `GHOST_MODE`, `MAX_UPLOAD_SIZE_MB`, `GROQ_TIMEOUT_SECONDS`, `GATEWAY_TIMEOUT_SECONDS`, `GATEWAY_RETRY_ATTEMPTS`

3. **Port mapping**: Map host port to container port 8000

4. **Health check**: Set to `GET /health`

5. **Restart policy**: `unless-stopped`

## Gateway Proxy

When deploying poast-relay in Docker (especially with Traefik network), the Clawdbot Gateway running on `localhost:18789` is not accessible from inside containers. The `gateway-proxy.example.js` script solves this by exposing the gateway on all interfaces (0.0.0.0:18790).

### Setup

1. **Create local proxy script**:
   ```bash
   cp gateway-proxy.example.js gateway-proxy.local.js
   chmod +x gateway-proxy.local.js
   ```

2. **Customize if needed** (or use environment variables):
   - Edit `gateway-proxy.local.js` to set ports/host, OR
   - Set `GATEWAY_HOST`, `GATEWAY_PORT`, `PROXY_PORT` environment variables

3. **Create systemd service**:
   ```bash
   cp gateway-proxy.service.example gateway-proxy.local.service
   # Edit gateway-proxy.local.service and update the ExecStart path
   # Then:
   cp gateway-proxy.local.service ~/.config/systemd/user/gateway-proxy.service
   systemctl --user daemon-reload
   systemctl --user enable gateway-proxy.service
   systemctl --user start gateway-proxy.service
   ```

4. **Check status**:
   ```bash
   systemctl --user status gateway-proxy.service
   ```

5. **View logs**:
   ```bash
   journalctl --user -u gateway-proxy.service -f
   ```

### Configuration

The proxy forwards requests from `0.0.0.0:18790` → `127.0.0.1:18789` (by default).

For Docker containers on the `traefik` network, use the Docker bridge gateway IP:
```bash
GATEWAY_URL=http://10.0.5.1:18790/tools/invoke
```

You can find your Docker network gateway with:
```bash
docker network inspect traefik | jq -r '.[0].IPAM.Config[0].Gateway'
```

### Why This Is Needed

- Clawdbot Gateway binds to `127.0.0.1` (localhost only) by default
- Docker containers can't reach `127.0.0.1` on the host
- The proxy exposes the gateway on all interfaces so containers can connect via the Docker bridge gateway IP
- Alternative: use `host.docker.internal` (Docker Desktop only) or configure gateway to bind directly to LAN (less secure)

## Architecture Overview

```
Upload Request
    ↓
[Authentication Middleware]
    ↓
[File Validation]
    ├─ File size
    ├─ MIME type
    └─ Extension
    ↓
[Groq Transcription Service]
    ↓
[Clawdbot Gateway Client]
    ├─ Retry logic (exponential backoff)
    └─ Timeout handling
    ↓
Response to Client
```

## Error Handling

### Authentication Errors
- **Ghost mode OFF** (default): Invalid token returns `401 Unauthorized`
- **Ghost mode ON**: Invalid token returns `404 Not Found` (hides service existence)

### Validation Errors
- Missing file: `400 Bad Request`
- Unsupported format: `400 Bad Request` with list of supported formats
- File too large: `413 Payload Too Large`
- Empty file: `400 Bad Request`

### Processing Errors
- Groq API timeout: `502 Bad Gateway` (after timeout)
- Gateway communication failure: `502 Bad Gateway` (after all retries exhausted)

## Troubleshooting

### Service won't start
- Check all required environment variables are set
- Verify Groq API key is valid
- Check gateway URL and token are correct

### Transcription fails
- Verify audio file is supported format
- Check file is not corrupted
- Review logs for Groq API errors
- Verify Groq API key has usage available

### Gateway relay fails
- Check gateway URL is accessible
- Verify gateway token is correct
- Confirm target session key exists
- Check gateway logs for issues
- Review retry logs (should show backoff attempts)

### Service returns 404
- Check path UUID matches configuration
- Verify authentication token is correct
- If ghost mode is enabled, invalid auth returns 404 (check token)

## Logging

The service logs all operations including:
- File uploads and validation
- Transcription attempts
- Gateway relay attempts and retries
- Errors and exceptions

Check logs with:
```bash
docker logs poast-relay
```

## Security Considerations

- **Path Obfuscation**: UUID-based path makes endpoint hard to guess
- **Authentication**: Bearer token required for all uploads
- **Ghost Mode**: Optionally hide service existence from authentication scanners
- **No Secrets in Code**: All credentials managed via environment variables
- **File Validation**: Strict file format and size validation
- **Timeout Protection**: Configurable timeouts prevent hanging requests

## Development

### Project Structure
```
poast-relay/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration management
│   ├── auth.py              # Authentication middleware
│   ├── routes/
│   │   ├── __init__.py
│   │   └── upload.py        # Upload endpoint
│   └── services/
│       ├── __init__.py
│       ├── transcription.py # Groq integration
│       └── gateway.py       # Gateway client
├── requirements.txt
├── Dockerfile
├── .env.example
└── README.md
```

### Adding New Features

1. Add configuration to `app/config.py`
2. Create service in `app/services/`
3. Create route in `app/routes/`
4. Include router in `app/main.py`
5. Test with `pytest` or manual requests

## Support

For issues or questions:
- Check logs: `docker logs poast-relay`
- Review configuration: `.env` file
- Verify gateway connectivity
- Check Groq API status and quota

## License

See LICENSE file for details.
