"""OAuth relay protocol models and result types."""

import json
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Optional


class MessageType(str, Enum):
    """Protocol message types."""

    REGISTER = "REGISTER"
    DELIVER = "DELIVER"
    ERROR = "ERROR"
    UNREGISTER = "UNREGISTER"


@dataclass
class SocketMessage:
    """Protocol message for Unix socket communication."""

    type: MessageType
    state: Optional[str] = None
    code: Optional[str] = None
    raw: Optional[dict] = None
    error: Optional[str] = None

    def to_json(self) -> str:
        """Serialize to JSON with newline terminator."""
        data = {k: v for k, v in asdict(self).items() if v is not None}
        data["type"] = self.type.value
        return json.dumps(data) + "\n"

    @classmethod
    def from_json(cls, json_str: str) -> "SocketMessage":
        """Deserialize from JSON."""
        data = json.loads(json_str.strip())
        msg_type = MessageType(data.pop("type"))
        return cls(type=msg_type, **data)


@dataclass
class RelayResult:
    """Client-facing result from OAuth callback."""

    code: Optional[str] = None  # Extracted code (if found)
    raw: Optional[dict] = None  # Full payload (if extraction failed)

    @property
    def success(self) -> bool:
        """True if code was successfully extracted."""
        return self.code is not None
