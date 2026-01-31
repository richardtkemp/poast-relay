# SPEC: Audio Transcription Proxy (Poast-Relay)

## 1. Overview
A high-performance FastAPI service that bridges the gap between external bots/apps and the Clawdbot Gateway. It transcribes audio using the Groq API and injects the results into a Clawdbot session.

## 2. Architecture
- **Framework:** Python / FastAPI.
- **Transcription:** Groq SDK (Whisper-large-v3).
- **Security:** 
  - URL Obfuscation via UUID-based path.
  - Bearer Token Auth for inbound requests.
  - Bearer Token Auth for outbound Gateway requests.
- **Config:** Externalized via a JSON/YAML file mounted from the Docker host.

## 3. Configuration (`config.json`)
The service reads its settings from a file mounted to the container.
```json
{
  "inbound_path_uuid": "e2a3b...",
  "inbound_auth_token": "client-secret-token",
  "groq_api_key": "gsk_...",
  "gateway_url": "http://192.168.1.150:18790/tools/invoke",
  "gateway_token": "5a5c8372...",
  "target_session_key": "agent:main:telegram:group:-5123815922"
}
```

## 4. Workflow
1. **Request:** Receive audio via `POST /${inbound_path_uuid}/upload`.
2. **Auth:** Validate `Authorization: Bearer ${inbound_auth_token}`.
3. **STT:** Send audio chunk to Groq API; receive JSON transcription.
4. **Relay:** Format as a `sessions_send` tool call:
   ```json
   {
     "tool": "sessions_send",
     "args": {
       "sessionKey": "${target_session_key}",
       "message": "${transcription_text}"
     }
   }
   ```
5. **Invoke:** POST to `${gateway_url}` with `${gateway_token}`.

## 5. Deployment (Coolify)
- **Project:** `home-server`
- **Environment:** `dev`
- **Persistence:** Mount a host directory (e.g., `/home/rich/poast-relay/config.json`) to the container for easy hot-editing of keys/tokens.

## 6. API Definition
`POST /{inbound_path_uuid}/upload`
- **Body:** `file: UploadFile`
- **Returns:** `{ "status": "sent", "text": "..." }`
