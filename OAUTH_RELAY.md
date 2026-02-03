# OAuth Relay Feature

The OAuth relay is an independent feature that enables headless OAuth flows for applications that cannot open a browser or need to handle authorization programmatically. It works by receiving OAuth callbacks from providers and delivering authorization codes to waiting client applications via Unix socket (or TCP on Windows).

## Architecture

The OAuth relay consists of three components:

1. **Relay Server**: A FastAPI endpoint that receives OAuth callbacks from providers
2. **Socket Coordinator**: A Unix socket (or TCP) server that manages client registrations and callback delivery
3. **Client Library**: A public async API (`wait_for_code()`) that client applications use to wait for codes

```
OAuth Provider → FastAPI Endpoint → Unix Socket Coordinator → Client Application
                     (HTTP)           (async futures)         (wait_for_code)
```

## Configuration

All OAuth relay settings are optional and can be configured via environment variables or `.env` file:

```bash
# Enable/disable OAuth relay (default: false)
OAUTH_ENABLED=true

# FastAPI endpoint path for OAuth callbacks (default: /oauth/callback)
OAUTH_CALLBACK_PATH=/oauth/callback

# Possible code key names (case-insensitive, default: code,authorization_code)
OAUTH_CODE_KEYS=code,authorization_code

# Unix socket path for local communication (default: /tmp/poast-relay-oauth.sock)
OAUTH_SOCKET_PATH=/tmp/poast-relay-oauth.sock

# TCP port for fallback (Windows or when OAUTH_USE_TCP=true, default: 9999)
OAUTH_TCP_FALLBACK_PORT=9999

# Default timeout for waiting clients in seconds (default: 300.0)
OAUTH_DEFAULT_TIMEOUT=300.0

# Log unmatched callbacks (default: true)
OAUTH_LOG_UNMATCHED=true

# Force TCP mode instead of Unix socket (default: false, auto-enabled on Windows)
OAUTH_USE_TCP=false
```

## Usage

### Basic Flow

```python
import asyncio
import secrets
from app.oauth.client import wait_for_code, OAuthTimeoutError

async def headless_oauth():
    # Generate cryptographically secure state parameter
    state = secrets.token_urlsafe(32)

    # Build OAuth authorization URL
    auth_url = (
        f"https://oauth.example.com/authorize"
        f"?client_id=YOUR_CLIENT_ID"
        f"&redirect_uri=https://poast.example.com/oauth/callback"
        f"&response_type=code"
        f"&scope=openid+profile+email"
        f"&state={state}"
    )

    print(f"Open this URL to authorize: {auth_url}")

    # Wait for OAuth callback
    try:
        result = await wait_for_code(state=state, timeout=600)

        if result.success:
            code = result.code
            print(f"Got authorization code: {code}")

            # Exchange code for tokens
            tokens = await exchange_code_for_tokens(code)
            print(f"Got tokens: {tokens}")
        else:
            print(f"Error callback received: {result.raw}")

    except OAuthTimeoutError:
        print("Timeout: User didn't complete authorization")
    except OAuthConnectionError:
        print("Cannot connect to OAuth relay - is the server running?")

asyncio.run(headless_oauth())
```

### Single-Slot Mode (No State)

For simple cases with only one concurrent flow, you can omit the state parameter:

```python
# Client 1: Wait for any callback
result = await wait_for_code()

# Provider sends callback without state
# Client receives result immediately
```

**Warning**: Single-slot mode only works for one client at a time. If multiple clients call `wait_for_code()` without state, the last registration wins and previous ones are cancelled.

### Multi-Flow Mode (With State)

Use state parameters to support multiple concurrent authorization flows:

```python
# Multiple concurrent flows
results = await asyncio.gather(
    wait_for_code(state="user1-auth"),
    wait_for_code(state="user2-auth"),
    wait_for_code(state="user3-auth"),
)
```

Each flow is independent and won't interfere with others.

### Custom Settings

Pass custom settings to `wait_for_code()`:

```python
from app.config import Settings

settings = Settings(
    inbound_path_uuid="...",  # Required
    inbound_auth_token="...",  # Required
    groq_api_key="...",  # Required
    gateway_url="...",  # Required
    gateway_token="...",  # Required
    target_session_key="...",  # Required
    oauth_enabled=True,
    oauth_socket_path="/custom/socket/path.sock",
    oauth_default_timeout=600.0,
)

result = await wait_for_code(state="myflow", settings=settings)
```

## HTTP Callback Handling

The relay supports both GET and POST callbacks:

### GET Callback

```
GET /oauth/callback?code=AUTH_CODE_XYZ&state=myflow&other_param=value
```

- Code and state extracted from query parameters
- Any additional parameters preserved in raw payload if extraction fails

### POST with JSON

```
POST /oauth/callback
Content-Type: application/json

{
  "code": "AUTH_CODE_XYZ",
  "state": "myflow",
  "other": "data"
}
```

### POST with Form Data

```
POST /oauth/callback
Content-Type: application/x-www-form-urlencoded

code=AUTH_CODE_XYZ&state=myflow&other=data
```

## Responses

### Success (200 OK)

When a client is waiting for the state and receives the callback:

```
HTTP/1.1 200 OK
Content-Type: text/html

[Beautiful HTML page saying "Authorization Complete"]
```

### Not Found (404)

When:
- No client is registered for the state parameter
- The code has already been delivered (replay protection)

```
HTTP/1.1 404 Not Found
Content-Type: text/html

[HTML page saying "Authorization Failed - No client waiting"]
```

## Error Handling

### OAuthTimeoutError

Raised when the client times out waiting for callback:

```python
try:
    result = await wait_for_code(state=state, timeout=300)
except OAuthTimeoutError:
    print("User didn't authorize within 5 minutes")
```

### OAuthConnectionError

Raised when unable to connect to the relay coordinator:

```python
try:
    result = await wait_for_code(state=state)
except OAuthConnectionError as e:
    print(f"Relay coordinator not available: {e}")
    # Coordinator might be down or socket path misconfigured
```

### OAuthRelayError

Base exception for all OAuth relay errors:

```python
from app.oauth.client import OAuthRelayError

try:
    result = await wait_for_code(state=state)
except OAuthRelayError as e:
    print(f"OAuth error: {e}")
```

## Callback Extraction

The relay extracts authorization codes using case-insensitive key matching. By default, it looks for `code` or `authorization_code` keys.

Custom keys can be configured:

```bash
OAUTH_CODE_KEYS=code,auth_code,access_code
```

Examples:

- Query: `?code=VALUE` → Extracted
- Query: `?CODE=VALUE` → Extracted (case-insensitive)
- Query: `?authorization_code=VALUE` → Extracted (alternative key)
- JSON: `{"code": "VALUE"}` → Extracted
- Form: `code=VALUE` → Extracted

If no code is found, the full payload is returned in `result.raw`:

```python
result = await wait_for_code(state=state)
if result.success:
    code = result.code
else:
    # Code extraction failed, full payload available
    error_info = result.raw  # e.g., {"error": "access_denied"}
```

## Security Considerations

### State Parameter (Client Responsibility)

The state parameter must be cryptographically random. Use `secrets.token_urlsafe()`:

```python
import secrets

state = secrets.token_urlsafe(32)  # 32 bytes = 256 bits of entropy
```

The relay uses state to route callbacks to the correct client but does NOT validate it. The OAuth provider validates state to prevent CSRF attacks.

### Local-Only Communication

- **Unix socket** (Linux/macOS): Only accessible to processes on the same machine
- **TCP loopback** (Windows/fallback): Only accessible from `127.0.0.1`

The coordinator is never exposed to the network.

### No Authentication on Callback

OAuth providers authenticate callbacks using the state parameter - the same mechanism that protects the standard OAuth flow. The relay doesn't add additional authentication.

### Replay Protection

Already-delivered codes return 404, preventing accidental reuse:

```
1. Client waits with state=X
2. Provider sends callback with code=C1, state=X
3. Client receives C1 (future resolved)
4. Provider mistakenly resends same callback
5. Client gets 404 (future already resolved, no longer waiting)
```

### Timeout Protection

Default 5-minute timeout prevents indefinite blocking:

```python
result = await wait_for_code(state=state)  # Max 300 seconds
```

### Unmatched Callback Logging

By default, callbacks with no waiting client are logged:

```python
OAUTH_LOG_UNMATCHED=true  # Log unmatched callbacks (security monitoring)
OAUTH_LOG_UNMATCHED=false # Silent (useful for testing)
```

## Troubleshooting

### "Cannot connect to OAuth relay"

The relay coordinator is not running or socket path is incorrect.

```bash
# Check if relay is running
curl http://localhost:8000/health

# Check socket exists (Unix socket mode)
ls -la /tmp/poast-relay-oauth.sock

# Check logs for startup errors
```

### "Timeout waiting for OAuth callback"

The client is waiting but the callback never arrives.

Possible causes:
- User didn't complete authorization
- Redirect URI configured in OAuth provider doesn't match relay endpoint
- Firewall blocking callback
- State parameter mismatch (provider vs client)

```python
# Increase timeout if needed
result = await wait_for_code(state=state, timeout=600)  # 10 minutes
```

### "Authorization Failed - No client waiting"

Callback arrived but no client registered for that state.

Possible causes:
- Callback arrived before client called `wait_for_code()`
- Client timed out before callback arrived
- State parameter doesn't match between callback and client registration

Solutions:
- Ensure client registers first before opening browser
- Increase timeout
- Verify state parameter is exactly the same (case-sensitive)

### Authorization endpoint returns 404

The OAuth callback endpoint is not registered or is disabled.

```bash
# Verify OAuth is enabled
grep OAUTH_ENABLED .env

# Check endpoint in logs
curl http://localhost:8000/oauth/callback?code=test  # Should return 404 or 200
```

## Performance

- **Latency**: Sub-millisecond between callback arrival and client reception (Unix socket)
- **Memory**: Minimal - only stores pending Future objects
- **Polling**: None - future-based delivery is instant
- **Async**: Fully non-blocking I/O throughout

## Platform Support

- **Linux/macOS**: Unix socket (default, optimal performance)
- **Windows**: TCP loopback (127.0.0.1:9999, automatic)
- **Docker**: Set `OAUTH_USE_TCP=true` and use Docker network DNS

### Docker Example

```yaml
services:
  relay:
    image: poast-relay:latest
    environment:
      OAUTH_ENABLED: "true"
      OAUTH_USE_TCP: "true"
      OAUTH_TCP_FALLBACK_PORT: "9999"
    ports:
      - "9999:9999"
```

Client code (in another container):

```python
settings = Settings(
    ...,
    oauth_enabled=True,
    oauth_use_tcp=True,
    oauth_tcp_fallback_port=9999,
)
```

## Feature Independence

The OAuth relay is completely independent from the audio transcription feature:

- Master switch: `OAUTH_ENABLED=false` disables it completely
- No shared code or dependencies
- Can run simultaneously with transcription
- Separate configuration, routes, services
- No impact when disabled

To disable OAuth relay without modifying configuration:

```bash
OAUTH_ENABLED=false uvicorn app.main:app
```

## Examples

### With Popular OAuth Providers

#### Google OAuth

```python
async def google_oauth():
    state = secrets.token_urlsafe(32)

    auth_url = (
        "https://accounts.google.com/o/oauth2/v2/auth?"
        "client_id=YOUR_CLIENT_ID&"
        "redirect_uri=https://your-domain.com/oauth/callback&"
        "response_type=code&"
        "scope=openid%20profile%20email&"
        f"state={state}"
    )

    print(f"Authorize: {auth_url}")

    result = await wait_for_code(state=state, timeout=300)

    if result.success:
        # Exchange for tokens using google.auth.transport.requests
        tokens = await exchange_code(result.code)
```

#### GitHub OAuth

```python
async def github_oauth():
    state = secrets.token_urlsafe(32)

    auth_url = (
        "https://github.com/login/oauth/authorize?"
        "client_id=YOUR_CLIENT_ID&"
        "redirect_uri=https://your-domain.com/oauth/callback&"
        f"state={state}&"
        "scope=repo,user"
    )

    result = await wait_for_code(state=state)

    if result.success:
        # Exchange using requests or httpx
        tokens = await exchange_code(result.code)
```

### Batch Authorization

```python
async def authorize_multiple_users(user_ids: list[str]):
    tasks = []

    for user_id in user_ids:
        state = f"user-{user_id}"
        auth_url = build_auth_url(user_id, state)
        print(f"[{user_id}] Open: {auth_url}")

        task = wait_for_code(state=state, timeout=600)
        tasks.append((user_id, task))

    # Wait for all authorizations
    for user_id, task in tasks:
        try:
            result = await task
            if result.success:
                print(f"[{user_id}] Authorized: {result.code}")
            else:
                print(f"[{user_id}] Error: {result.raw}")
        except OAuthTimeoutError:
            print(f"[{user_id}] Timeout")
```

## Testing

Run the test suite:

```bash
pytest tests/test_oauth_relay.py -v
```

Test categories:
- Core flow (with/without state)
- Error cases (timeout, no client, already delivered)
- Extraction (case-insensitive, list values, fallback)
- Protocol (registration, delivery, cleanup)
- Edge cases (multiple clients, connection errors)

## Logging

OAuth relay operations are logged at INFO level:

```
INFO - OAuth relay enabled
INFO - OAuth coordinator starting
INFO - OAuth coordinator listening on /tmp/poast-relay-oauth.sock
INFO - Client registered for state: 'myflow'
INFO - OAuth callback delivered to client for state: 'myflow'
INFO - No client waiting for state 'unmatched' - dropping callback
INFO - OAuth callback timeout for state: 'myflow'
INFO - OAuth coordinator stopped
```

Enable debug logging for detailed protocol information:

```python
import logging

logging.getLogger("app.oauth").setLevel(logging.DEBUG)
```
