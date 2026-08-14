"""PipeWire audio capture via pw-record.

Captures raw s16le mono 16k PCM from a PipeWire source. By default it records
the SYSTEM internal audio (the monitor source of the default output sink),
so synthesized/playback audio is picked up. Pass an explicit `target`
(node id/name, e.g. the mic source) to override.

Business layer only: capture + hand raw PCM downstream. No AI here.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading

logger = logging.getLogger("meeting.recorder")

CHUNK_BYTES = 480 * 4  # 120ms of s16le mono @16k, plenty for the VAD

RECORD_ARGS = [
    "--raw",          # raw PCM to stdout, no container
    "--format", "s16",
    "--rate", "16000",
    "--channels", "1",
    "--volume", "1.0",
]


class RecorderError(RuntimeError):
    pass


def detect_system_monitor_source() -> str | None:
    """Return the monitor source name of the default output sink.

    On PipeWire/PulseAudio this is the ``<sink>.monitor`` source that carries
    the system's internal/playback audio. Returns None if it can't be found.
    """
    try:
        out = subprocess.run(["pactl", "list", "short", "sinks"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            line = (out.stdout or "").strip().splitlines()
            if line:
                sink = line[0].split("\t")[1]
                monitor = f"{sink}.monitor"
                if _monitor_exists(monitor):
                    return monitor
        out = subprocess.run(["pactl", "list", "short", "sources"],
                             capture_output=True, text=True, timeout=10)
        for row in (out.stdout or "").splitlines():
            parts = row.split("\t")
            if len(parts) >= 2 and parts[1].endswith(".monitor"):
                return parts[1]
    except Exception as exc:  # noqa: BLE001
        logger.warning("monitor source detection failed: %s", exc)
    return None


def _monitor_exists(name: str) -> bool:
    try:
        out = subprocess.run(["pactl", "list", "short", "sources"],
                             capture_output=True, text=True, timeout=10)
        return name in (out.stdout or "")
    except Exception:
        return False


def detect_default_mic_source() -> str | None:
    """Return the default input source (the microphone) name, or None."""
    try:
        out = subprocess.run(["pactl", "get-default-source"],
                             capture_output=True, text=True, timeout=10)
        name = (out.stdout or "").strip()
        if name and not name.endswith(".monitor"):
            return name
        out = subprocess.run(["pactl", "list", "short", "sources"],
                             capture_output=True, text=True, timeout=10)
        for row in (out.stdout or "").splitlines():
            parts = row.split("\t")
            if len(parts) >= 2 and not parts[1].endswith(".monitor"):
                return parts[1]
    except Exception as exc:  # noqa: BLE001
        logger.warning("mic source detection failed: %s", exc)
    return None


class PipeWireRecorder:
    """Reads a PipeWire source (system-internal audio by default)."""

    #: seconds of captured audio to discard right after start. The monitor
    #: source emits a loud clipped transient when it wakes from SUSPENDED;
    #: skipping it keeps the wav clean and avoids confusing the transcriber.
    STARTUP_SKIP_SECONDS = 0.5

    def __init__(self, on_pcm=None, target: str | None = None,
                 system_internal: bool = True, binary: str = "pw-record",
                 startup_skip_seconds: float = STARTUP_SKIP_SECONDS):
        self.on_pcm = on_pcm
        self.target = target
        self.system_internal = system_internal
        self.binary = binary
        self.startup_skip = startup_skip_seconds
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._skip_left = 0

    def start(self):
        if shutil.which(self.binary) is None:
            raise RecorderError(f"{self.binary} not found on PATH")
        target = self.target
        if not target and self.system_internal:
            target = detect_system_monitor_source()
            if target:
                logger.info("recording system internal audio from %s", target)
            else:
                logger.warning("no system monitor source found; "
                               "using default source")
        argv = [self.binary]
        if target:
            argv += ["--target", target]
        argv += RECORD_ARGS + ["-"]
        logger.info("starting %s", " ".join(argv))
        self._stop.clear()
        self._skip_left = int(self.startup_skip * 16000 * 2)  # 16k mono s16
        self._proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=CHUNK_BYTES)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        assert self._proc is not None and self._proc.stdout is not None
        while not self._stop.is_set():
            data = self._proc.stdout.read(CHUNK_BYTES)
            if not data:
                break
            if self._skip_left > 0:
                if len(data) <= self._skip_left:
                    self._skip_left -= len(data)
                    continue
                data = data[self._skip_left:]
                self._skip_left = 0
            if self.on_pcm:
                self.on_pcm(data)

    def stop(self):
        self._stop.set()
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._reader is not None:
            self._reader.join(timeout=5)
        logger.info("recorder stopped")
