from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
from typing import Any
import uuid

class CommandAction(str, Enum):
    SET="set"
    START="start"
    STOP="stop"
    ENABLE="enable"
    DISABLE="disable"

@dataclass(frozen=True, slots=True)
class Command:
    target: str
    action: CommandAction
    value: Any=None
    issued_at: datetime = field(default_factory=datetime.utcnow)
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))
