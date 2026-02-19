import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.config import Settings

logger = logging.getLogger(__name__)


def create_usage_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/usage", tags=["usage"])

    base_dir = Path(settings.openclaw_base_dir).expanduser()
    agents_dir = base_dir / "config" / "agents"
    static_dir = Path(__file__).parent.parent / "static" / "usage"

    # Cache for session list
    _sessions_cache: dict = {"data": None, "expires": 0}

    def _discover_agents() -> list[str]:
        if not agents_dir.is_dir():
            return []
        return [
            d.name
            for d in agents_dir.iterdir()
            if d.is_dir() and (d / "sessions").is_dir()
        ]

    def _session_files(agent: str) -> list[Path]:
        sessions_dir = agents_dir / agent / "sessions"
        if not sessions_dir.is_dir():
            return []
        return sorted(sessions_dir.glob("*.jsonl"))

    def _parse_session_meta(path: Path, agent: str) -> Optional[dict]:
        """Read the first line of a JSONL file for session metadata."""
        try:
            with open(path, "r") as f:
                first_line = f.readline().strip()
                if not first_line:
                    return None
                entry = json.loads(first_line)
                if entry.get("type") != "session":
                    return None
                session_id = path.stem
                return {
                    "agent": agent,
                    "sessionId": session_id,
                    "timestamp": entry.get("timestamp"),
                }
        except Exception:
            return None

    def _enrich_sessions_from_index(agent: str, sessions: dict) -> None:
        """Merge data from sessions.json index if available.

        The index is a dict keyed by session key (e.g. "agent:main:main"),
        where each value has sessionId, updatedAt, modelOverride, chatType, etc.
        """
        index_path = agents_dir / agent / "sessions" / "sessions.json"
        if not index_path.is_file():
            return
        try:
            with open(index_path, "r") as f:
                index = json.load(f)
            for key, entry in index.items():
                sid = entry.get("sessionId")
                if sid and sid in sessions:
                    sessions[sid].update({
                        "sessionKey": key,
                        "kind": entry.get("chatType", ""),
                        "updatedAt": entry.get("updatedAt"),
                        "model": entry.get("modelOverride", ""),
                    })
        except Exception as e:
            logger.warning(f"Failed to read sessions index for {agent}: {e}")

    def _list_sessions() -> list[dict]:
        now = time.time()
        if _sessions_cache["data"] is not None and now < _sessions_cache["expires"]:
            return _sessions_cache["data"]

        results = []
        for agent in _discover_agents():
            # Build dict keyed by session ID from JSONL files
            sessions_by_id: dict[str, dict] = {}
            for path in _session_files(agent):
                meta = _parse_session_meta(path, agent)
                if meta:
                    sessions_by_id[meta["sessionId"]] = meta

            # Enrich with index data
            _enrich_sessions_from_index(agent, sessions_by_id)
            results.extend(sessions_by_id.values())

        # Sort by updatedAt descending. updatedAt is epoch ms (int) from
        # the index; timestamp is an ISO string from the JSONL first line.
        # Normalise to epoch ms for consistent comparison.
        def _sort_key(s):
            ua = s.get("updatedAt")
            if isinstance(ua, (int, float)):
                return ua
            ts = s.get("timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    return dt.timestamp() * 1000
                except ValueError:
                    pass
            return 0

        results.sort(key=_sort_key, reverse=True)
        _sessions_cache["data"] = results
        _sessions_cache["expires"] = now + 30
        return results

    def _parse_jsonl_usage(
        path: Path,
        since: Optional[datetime] = None,
        roles: Optional[set[str]] = None,
    ) -> list[dict]:
        """Parse a JSONL file and extract entries with usage data."""
        turns = []
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("type") != "message":
                        continue
                    msg = entry.get("message", {})
                    usage = msg.get("usage")
                    if not usage:
                        continue
                    ts_str = entry.get("timestamp", "")
                    if since and ts_str:
                        try:
                            ts = datetime.fromisoformat(
                                ts_str.replace("Z", "+00:00")
                            )
                            if ts < since:
                                continue
                        except ValueError:
                            pass
                    role = msg.get("role", "unknown")
                    if roles and role not in roles:
                        continue
                    turns.append(
                        {
                            "id": entry.get("id"),
                            "timestamp": ts_str,
                            "role": role,
                            "model": msg.get("model", ""),
                            "usage": usage,
                        }
                    )
        except Exception as e:
            logger.warning(f"Failed to parse {path}: {e}")
        return turns

    # --- Routes ---

    @router.get("/")
    async def dashboard():
        return FileResponse(
            static_dir / "index.html", media_type="text/html"
        )

    @router.get("/app.js")
    async def app_js():
        return FileResponse(
            static_dir / "app.js", media_type="application/javascript"
        )

    @router.get("/style.css")
    async def style_css():
        return FileResponse(static_dir / "style.css", media_type="text/css")

    @router.get("/api/sessions")
    async def list_sessions():
        return _list_sessions()

    @router.get("/api/sessions/{agent}/{session_id}/turns")
    async def session_turns(
        agent: str,
        session_id: str,
        since: Optional[str] = Query(None),
        role: Optional[str] = Query(None),
    ):
        path = agents_dir / agent / "sessions" / f"{session_id}.jsonl"
        if not path.is_file():
            return []
        since_dt = None
        if since:
            try:
                since_dt = datetime.fromisoformat(
                    since.replace("Z", "+00:00")
                )
            except ValueError:
                pass
        roles = set(role.split(",")) if role else None
        return _parse_jsonl_usage(path, since=since_dt, roles=roles)

    @router.get("/api/aggregate")
    async def aggregate(
        agent: Optional[str] = Query(None),
        since: Optional[str] = Query(None),
        granularity: str = Query("hour"),
    ):
        since_dt = None
        if since:
            try:
                since_dt = datetime.fromisoformat(
                    since.replace("Z", "+00:00")
                )
            except ValueError:
                pass

        agents = [agent] if agent else _discover_agents()
        buckets: dict[str, dict] = {}

        for ag in agents:
            for path in _session_files(ag):
                # Skip files not modified since the cutoff
                if since_dt:
                    mtime = path.stat().st_mtime
                    if mtime < since_dt.timestamp():
                        continue
                turns = _parse_jsonl_usage(path, since=since_dt)
                for turn in turns:
                    ts_str = turn["timestamp"]
                    try:
                        ts = datetime.fromisoformat(
                            ts_str.replace("Z", "+00:00")
                        )
                    except ValueError:
                        continue
                    if granularity == "day":
                        bucket_key = ts.strftime("%Y-%m-%d")
                    else:
                        bucket_key = ts.strftime("%Y-%m-%dT%H:00:00Z")

                    if bucket_key not in buckets:
                        buckets[bucket_key] = {
                            "bucket": bucket_key,
                            "input": 0,
                            "output": 0,
                            "cacheRead": 0,
                            "cacheWrite": 0,
                            "totalCost": 0.0,
                            "turns": 0,
                        }
                    b = buckets[bucket_key]
                    u = turn["usage"]
                    b["input"] += u.get("input", 0)
                    b["output"] += u.get("output", 0)
                    b["cacheRead"] += u.get("cacheRead", 0)
                    b["cacheWrite"] += u.get("cacheWrite", 0)
                    cost = u.get("cost", {})
                    b["totalCost"] += cost.get("total", 0.0)
                    b["turns"] += 1

        result = sorted(buckets.values(), key=lambda b: b["bucket"])
        return result

    return router
