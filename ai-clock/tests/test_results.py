from unittest.mock import patch, MagicMock
from datetime import datetime

from clockai.models import Task
from clockai.scheduler import execute_task, _run_and_save, run_once
from clockai import storage


def make_task(time="08:00", period="daily", last_run=None, enabled=True):
    return Task(
        id="test-id",
        prompt="test prompt",
        time=time,
        period=period,
        last_run=last_run,
        enabled=enabled,
    )


class TestExecuteTask:
    def test_success_stores_stdout_as_result(self):
        mock_run = MagicMock()
        mock_run.returncode = 0
        mock_run.stdout = "success output\n"
        mock_run.stderr = ""

        with patch("subprocess.run", return_value=mock_run):
            result = execute_task(make_task())

        assert result == "success output"

    def test_failure_stores_stderr_as_result(self):
        mock_run = MagicMock()
        mock_run.returncode = 1
        mock_run.stdout = ""
        mock_run.stderr = "error message\n"

        with patch("subprocess.run", return_value=mock_run):
            result = execute_task(make_task())

        assert "失败" in result
        assert "error message" in result

    def test_timeout_stores_timeout_message(self):
        from subprocess import TimeoutExpired

        with patch("subprocess.run", side_effect=TimeoutExpired("aim", 300)):
            result = execute_task(make_task())

        assert "timed out" in result

    def test_command_not_found_stores_error(self):
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = execute_task(make_task())

        assert "not found" in result


class TestRunAndSave:
    def test_saves_result_to_task_and_storage(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "tasks.json")

        task = make_task()
        storage.add_task(task)

        mock_run = MagicMock()
        mock_run.returncode = 0
        mock_run.stdout = "stored result"
        mock_run.stderr = ""

        with patch("subprocess.run", return_value=mock_run):
            _run_and_save(task)

        loaded = storage.find_task(task.id)
        assert loaded is not None
        assert loaded.last_result == "stored result"


class TestRunOnce:
    def test_records_last_result_on_execution(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
        monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "tasks.json")

        now = datetime(2026, 7, 19, 8, 0)
        task = make_task(time="08:00", period="daily")
        storage.add_task(task)

        mock_run = MagicMock()
        mock_run.returncode = 0
        mock_run.stdout = "run once result"
        mock_run.stderr = ""

        with patch("subprocess.run", return_value=mock_run):
            with patch("clockai.scheduler.datetime") as mock_dt:
                mock_dt.now.return_value = now
                run_once()

        loaded = storage.find_task(task.id)
        assert loaded is not None
        assert loaded.last_result == "run once result"
        assert loaded.last_run == now.isoformat()
