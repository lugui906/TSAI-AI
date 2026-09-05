import subprocess
from pathlib import Path

from .models import Task

UNIT_DIR = Path("/etc/systemd/system")

CLOCKAI_BIN = "/usr/local/bin/clockai"
USER = "lugui"

SERVICE_TEMPLATE = """[Unit]
Description=ClockAI task {tid}: {prompt}
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User={user}
Group={user}
Environment=HOME=/home/{user}
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/{user}/.Xauthority
WorkingDirectory=/usr/chindows/clockai
ExecStart={bin} exec {tid}
"""

TIMER_TEMPLATE = """[Unit]
Description=ClockAI task {tid} timer ({period})

[Timer]
{on_cal}Persist=true

[Install]
WantedBy=timers.target
"""


def _service_name(task_id: str) -> str:
    return f"clockai-task-{task_id}.service"


def _timer_name(task_id: str) -> str:
    return f"clockai-task-{task_id}.timer"


def _service_path(task_id: str) -> Path:
    return UNIT_DIR / _service_name(task_id)


def _timer_path(task_id: str) -> Path:
    return UNIT_DIR / _timer_name(task_id)


def _on_calendar(task: Task) -> str:
    try:
        h, m = task.time.split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        h, m = 0, 0

    if task.period == "hourly":
        return f"OnCalendar=*:{m:02d}:00\n"
    return f"OnCalendar={h:02d}:{m:02d}:00\n"


def _timer_entries(task: Task) -> str:
    if task.period.startswith("interval:"):
        try:
            minutes = int(task.period.split(":", 1)[1])
        except (ValueError, IndexError):
            minutes = 60
        if minutes <= 0:
            minutes = 1
        return f"OnActiveSec=1min\nOnUnitActiveSec={minutes}min\n"
    return _on_calendar(task)


def build_units(task: Task) -> str:
    service = SERVICE_TEMPLATE.format(
        tid=task.id, prompt=task.prompt, user=USER, bin=CLOCKAI_BIN
    )
    timer = TIMER_TEMPLATE.format(
        tid=task.id, period=task.period, on_cal=_timer_entries(task)
    )
    return service + "\n" + timer


def _run(cmd, input_data=None):
    return subprocess.run(cmd, capture_output=True, text=True, input=input_data)


def _sudo(cmd, input_data=None):
    return _run(["sudo", *cmd], input_data=input_data)


def _sudo_write(path: Path, content: str) -> bool:
    r = _sudo(["tee", str(path)], content)
    return r.returncode == 0


def _sudo_unlink(path: Path) -> bool:
    return _sudo(["rm", "-f", str(path)]).returncode == 0


def _sudo_exists(path: Path) -> bool:
    r = _sudo(["test", "-f", str(path)])
    return r.returncode == 0


def install_task(task: Task) -> bool:
    service = SERVICE_TEMPLATE.format(
        tid=task.id, prompt=task.prompt, user=USER, bin=CLOCKAI_BIN
    )
    timer = TIMER_TEMPLATE.format(
        tid=task.id, period=task.period, on_cal=_timer_entries(task)
    )

    if not _sudo_write(_service_path(task.id), service):
        return False
    if not _sudo_write(_timer_path(task.id), timer):
        return False

    r = _sudo(["systemctl", "daemon-reload"])
    if r.returncode != 0:
        return False
    if task.enabled:
        r = _sudo(["systemctl", "enable", "--now", _timer_name(task.id)])
    else:
        r = _sudo(["systemctl", "disable", _timer_name(task.id)])
    return r.returncode == 0


def remove_task(task_id: str) -> bool:
    timer = _timer_name(task_id)
    _sudo(["systemctl", "disable", "--now", timer])
    _sudo(["systemctl", "daemon-reload"])
    _sudo_unlink(_service_path(task_id))
    _sudo_unlink(_timer_path(task_id))
    return not _sudo_exists(_service_path(task_id)) and not _sudo_exists(_timer_path(task_id))


def update_task(task: Task) -> bool:
    return install_task(task)
