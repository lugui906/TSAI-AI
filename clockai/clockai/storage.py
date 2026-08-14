import json
import os
from pathlib import Path
from typing import List, Optional

from .models import Task


DATA_DIR = Path.home() / ".config" / "clockai"
DATA_FILE = DATA_DIR / "tasks.json"


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_tasks() -> List[Task]:
    _ensure_dir()
    if not DATA_FILE.exists():
        return []
    try:
        raw = DATA_FILE.read_text()
        data = json.loads(raw)
        return [Task.from_dict(t) for t in data]
    except (json.JSONDecodeError, KeyError):
        return []


def save_tasks(tasks: List[Task]) -> None:
    _ensure_dir()
    data = [t.to_dict() for t in tasks]
    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def add_task(task: Task) -> None:
    tasks = load_tasks()
    tasks.append(task)
    save_tasks(tasks)


def delete_task(task_id: str) -> bool:
    tasks = load_tasks()
    filtered = [t for t in tasks if t.id != task_id]
    if len(filtered) == len(tasks):
        return False
    save_tasks(filtered)
    return True


def find_task(task_id: str) -> Optional[Task]:
    tasks = load_tasks()
    for t in tasks:
        if t.id == task_id:
            return t
    return None


def update_task(task: Task) -> None:
    tasks = load_tasks()
    for i, t in enumerate(tasks):
        if t.id == task.id:
            tasks[i] = task
            break
    save_tasks(tasks)
