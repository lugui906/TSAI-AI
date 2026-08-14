"""Thin wrapper around the AIM CLI (`aim newrun` / `aim run`).

Session lifecycle is owned by AIM. This layer only:
  - assembles the payload passed on the command line
  - runs the subprocess with a generous timeout (AIM may queue)
  - surfaces the returned text (Markdown) to the caller
  - tracks a lightweight session handle for bookkeeping/reuse
The session id is only saved/reused if AIM returns one; otherwise the
conversation is implicit (aim run continues the last newrun).
"""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger("aim_client")

# AIM inference can be slow / queued; use a long default timeout.
DEFAULT_TIMEOUT_SECONDS = 1800
NEWRUN_CMD = "newrun"
RUN_CMD = "run"


class AIMError(RuntimeError):
    """Raised when the AIM CLI fails to produce a result."""


class AIMClient:
    """Subprocess client for the AIM middleware."""

    def __init__(self, binary: str = "aim", timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.binary = binary
        self.timeout = timeout
        self.session_id: str | None = None

    @staticmethod
    def _check_binary() -> None:
        if shutil.which("aim") is None:
            raise AIMError("aim binary not found on PATH")

    def _run(self, command: str, payload: str) -> str:
        self._check_binary()
        argv = [self.binary, command, payload]
        logger.info("AIM call: %s argv=%s", self.binary, command)
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise AIMError(f"aim {command} timed out after {self.timeout}s") from exc

        combined = (proc.stdout or "").strip()
        if proc.returncode != 0:
            err = (proc.stderr or combined).strip()
            raise AIMError(f"aim {command} exited {proc.returncode}: {err}")
        if not combined:
            raise AIMError(f"aim {command} returned empty output")
        return combined

    def newrun(self, payload: str) -> str:
        """Start a new conversation with AIM. Returns the reply markdown."""
        result = self._run(NEWRUN_CMD, payload)
        self.session_id = None  # fresh conversation; session managed by AIM
        return result

    def run(self, payload: str) -> str:
        """Continue the current conversation. Returns the incremental reply."""
        return self._run(RUN_CMD, payload)