import subprocess
import sys
import time
import logging
import threading
from datetime import datetime
from typing import List

from .models import Task
from . import storage

logger = logging.getLogger("clockai")


def _run_and_save(task: Task) -> None:
    result = execute_task(task)
    task.last_result = result
    storage.update_task(task)


def execute_task(task: Task) -> str:
    logger.info(f"Executing task {task.id}: {task.prompt[:60]}...")
    try:
        result = subprocess.run(
            ["aim", "newrun", task.prompt],
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if result.returncode == 0:
            output = (result.stdout or "").strip()[:500]
            logger.info(f"Task {task.id} completed: {output[:200]}")
            return output
        else:
            msg = (result.stderr or "").strip()[:500]
            logger.error(f"Task {task.id} failed (code {result.returncode}): {msg[:200]}")
            return f"失败: {msg}"
    except FileNotFoundError:
        msg = "Command 'aim' not found"
        logger.error(msg)
        return msg
    except subprocess.TimeoutExpired:
        msg = "Task timed out after 300s"
        logger.error(f"Task {task.id} {msg}")
        return msg
    except Exception as e:
        msg = str(e)
        logger.error(f"Task {task.id} error: {msg}")
        return f"错误: {msg}"


def run_scheduler(daemon: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("ClockAI scheduler started (checking every 30s)")
    logger.info("Press Ctrl+C to stop")

    try:
        while True:
            now = datetime.now().replace(second=0, microsecond=0)
            tasks = storage.load_tasks()

            for task in tasks:
                if task.should_run(now):
                    logger.info(f"Triggering task {task.id}: {task.prompt[:40]}")
                    task.last_run = now.isoformat()
                    storage.update_task(task)
                    threading.Thread(target=_run_and_save, args=(task,), daemon=True).start()

            if not daemon:
                break

            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")


def run_once() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    now = datetime.now().replace(second=0, microsecond=0)
    tasks = storage.load_tasks()
    triggered = 0

    for task in tasks:
        if task.should_run(now):
            logger.info(f"Triggering task {task.id}")
            result = execute_task(task)
            task.last_run = now.isoformat()
            task.last_result = result
            storage.update_task(task)
            triggered += 1

    if triggered == 0:
        logger.info("No tasks due right now")
