from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
import uuid


@dataclass
class Task:
    id: str
    prompt: str
    time: str
    period: str
    enabled: bool = True
    last_run: Optional[str] = None
    last_result: Optional[str] = None

    @classmethod
    def create(cls, prompt: str, time: str, period: str) -> "Task":
        return cls(
            id=uuid.uuid4().hex[:12],
            prompt=prompt,
            time=time,
            period=period,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(**data)

    def should_run(self, now: datetime) -> bool:
        if not self.enabled:
            return False

        try:
            h, m = self.time.split(":")
            target_hour, target_min = int(h), int(m)
        except (ValueError, AttributeError):
            return False

        today = now.date()

        if self.period == "daily":
            target = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
            if target > now:
                return False
            if self.last_run:
                last = datetime.fromisoformat(self.last_run)
                if last.date() == today and last >= target:
                    return False
            return (now - target).total_seconds() < 60

        if self.period == "hourly":
            target = now.replace(minute=target_min, second=0, microsecond=0)
            if target > now:
                return False
            if self.last_run:
                last = datetime.fromisoformat(self.last_run)
                if last >= target:
                    return False
            return (now - target).total_seconds() < 60

        if self.period.startswith("interval:"):
            try:
                minutes = int(self.period.split(":", 1)[1])
            except (ValueError, IndexError):
                return False
            if minutes <= 0:
                return False
            if self.last_run:
                last = datetime.fromisoformat(self.last_run)
                return (now - last).total_seconds() >= minutes * 60
            target = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
            if target > now:
                return False
            return True

        return False
