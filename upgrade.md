# OAuth Relay Spec

## Overview
A two-component system enabling headless OAuth flows. A relay server (FastAPI endpoint) receives the OAuth provider's callback via a Cloudflare tunnel, extracts the auth code if possible, and forwards it to a waiting client library running on the same machine. Communication between relay and client is over a local Unix socket or TCP loopback.

---

## Component 1: Relay Server (FastAPI integration)

### Endpoint
Mounts a single endpoint on the existing FastAPI app. The path should be configurable (default /oauth/callback).

### Receiving
Must handle both GET (query params) and POST (form body or JSON body) from the OAuth provider. Should not assume which.

### Extraction
Attempts to extract the auth code from the received data using a configurable list of candidate keys (default: ["code", "authorization_code"]). Search should be case-insensitive on keys. Extraction applies regardless of whether the data arrived as query params, form body, or JSON. If extraction succeeds, forwards only the code string to the waiting client. If extraction fails, forwards the entire received payload as a dict to the waiting client. Client must be able to distinguish between these two cases (see Component 2).

### Response
Returns a simple HTML response to the browser regardless of extraction outcome. Something like "Auth complete, you can close this tab." Should not block or fail based on whether a client is waiting.

### State matching
Supports an optional state parameter for matching callbacks to in-flight flows. If state is present in the received data, it is used to route the payload to the correct waiting client. If absent, falls back to a single-slot model.

---

## Component 2: Client Library

### Interface
Exposes a single async function. Something like:
```python
result = await oauth_relay.wait_for_code(state: str | None = None)
```

### Result type
Returns a typed result that makes it unambiguous whether extraction succeeded or not. Something like:
```python
@dataclass
class RelayResult:
    code: str | None  # The extracted code, if found
    raw: dict | None  # The full payload, if extraction failed
    
    @property
    def success(self) -> bool:
        return self.code is not None
```
Client calls `result.code` if `result.success`, otherwise inspects `result.raw`.

### Timeout
`wait_for_code` should accept an optional timeout (default something sane like 300s). Raises on timeout rather than hanging forever.

### Lifecycle
Client registers intent to receive a code (optionally with state), then blocks on the await. Relay delivers when the callback fires. No polling.

---

## Component 3: Coordination Layer

### Transport
Unix socket preferred (no port conflicts, no network stack overhead, stays local). Falls back to TCP loopback if Unix sockets aren't available (i.e. Windows, though that's probably not your case).

### Protocol
Minimal. Two message types:
- **Register**: client tells relay "I'm waiting, here's my state (if any)"
- **Deliver**: relay tells client "here's your result"

Both should be JSON over the socket. Could be as simple as newline-delimited JSON if you don't want to pull in a framing library.

### Concurrency
Relay holds a dict of pending futures keyed on state. If state is None, uses a single reserved key (e.g. `__default__`). If a callback arrives and no matching future exists, the payload is logged and dropped (don't silently swallow it — this is a debugging pain point).

---

## Configurable
- Callback path
- Candidate keys for code extraction
- Socket path (or TCP port as fallback)
- Timeout default
- Whether to log unmatched callbacks

---

## Out of scope
- Token exchange (client's responsibility once it has the code)
- Multiple simultaneous flows without state (undefined behaviour, single slot wins)
