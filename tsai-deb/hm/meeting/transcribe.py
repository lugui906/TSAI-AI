"""Speech-to-text using pywhispercpp with a local offline whisper.cpp model.

AI reasoning stays delegated to AIM; the only local model used here is ASR
(raw audio -> plain text, which AIM can read). Uses the model already present
on this machine:
    /usr/local/share/ai-subtitle/models/ggml-base.bin
so no network access or downloads are required.
"""

from __future__ import annotations

import logging
import os
import threading
import wave

import numpy as np

logger = logging.getLogger("meeting.transcribe")

_THREADS = 4

# Model paths tried in order of preference (better accuracy first). The first
# existing file is used. Falls back to the base model if no larger one exists.
MODEL_CANDIDATES = [
    "/usr/chindows/aai/share/models/small/ggml-small.bin",
    "/usr/local/share/ai-subtitle/models/ggml-base.bin",
    "/usr/local/share/ai-subtitle/models/base/ggml-base.bin",
]
DEFAULT_MODEL = MODEL_CANDIDATES[0]

_QUIET = 0.02                 # RMS below this is treated as silence (normalized range)
_BURST_MIN_SILENCE = 0.30     # seconds of quiet needed to separate a leading burst
_PAD = 0.2                    # seconds of audio kept around trimmed speech edges
_PARALLEL_FROM = 120.0        # transcribe files >= this many seconds with n_processors


class TranscriberError(RuntimeError):
    pass


class Transcriber:
    """Lazily-loaded local whisper.cpp transcriber (model shared across calls)."""

    _lock = threading.Lock()

    def __init__(self, model_path: str | None = None, language: str = "zh"):
        self.model_path = model_path or resolve_model_path()
        self.language = language
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            if not os.path.exists(self.model_path):
                raise TranscriberError(f"local model not found: {self.model_path}")
            try:
                from pywhispercpp.model import Model
            except ImportError as exc:
                raise TranscriberError(
                    "pywhispercpp not installed") from exc
            with self._lock:
                if self._model is None:
                    self._model = Model(self.model_path, n_threads=_THREADS,
                                        print_progress=False)
        return self._model

    def transcribe(self, audio_path: str) -> str:
        """Return the plain-text transcript of an audio file.

        The wav is pre-processed before ASR:
          - normalized (boosts quiet system-audio recordings),
          - leading transient/clipped burst and trailing silence trimmed
            (a monitor-source startup "pop" otherwise makes whisper abort
            the rest of the file),
          - long files are transcribed with whisper's parallel split so the
            whole recording is covered instead of stopping after the first
            speech burst.
        """
        model = self._ensure_model()
        audio, rate = self._load_audio(audio_path)
        audio = self._preprocess(audio, rate)
        n_processors = self._parallel(audio, rate)
        segs = model.transcribe(audio, language=self.language,
                                n_processors=n_processors)
        return " ".join(s.text.strip() for s in segs if s.text.strip())

    # -- audio pre-processing -------------------------------------------------
    @staticmethod
    def _load_audio(path: str) -> tuple[np.ndarray, int]:
        """Load a mono 16-bit wav as float32 in [-1, 1]; returns (audio, rate)."""
        with wave.open(path, "rb") as wf:
            rate = wf.getframerate()
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            raw = np.frombuffer(wf.readframes(wf.getnframes()),
                                dtype="<i2").astype(np.float32)
        if ch == 1:
            audio = raw
        else:
            audio = raw.reshape(-1, ch).mean(axis=1)
        if sw != 2:
            raise TranscriberError("wav must be 16-bit PCM")
        return audio / 32768.0, rate

    @classmethod
    def _preprocess(cls, audio: np.ndarray, rate: int) -> np.ndarray:
        if audio.size == 0:
            return audio
        peak = float(np.abs(audio).max())
        if peak > 0:
            audio = audio * (0.9 / peak)      # normalize to a healthy level
        audio = cls._strip_leading_burst(audio, rate)
        audio = cls._trim_edges(audio, rate)
        return audio

    @classmethod
    def _windowed_rms(cls, audio: np.ndarray, rate: int) -> tuple[np.ndarray, int]:
        win = max(1, int(rate * 0.05))        # 50ms windows
        n = audio.size // win * win
        if n == 0:
            return np.array([float(np.sqrt(np.mean(audio ** 2)))]), 1
        frames = audio[:n].reshape(-1, win)
        return np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1)), win

    @classmethod
    def _strip_leading_burst(cls, audio: np.ndarray, rate: int) -> np.ndarray:
        """Drop a loud clipped burst (monitor wake-up pop) at the file start."""
        rms, win = cls._windowed_rms(audio, rate)
        gap = max(1, int(_BURST_MIN_SILENCE * rate) // win)
        run = 0
        for i, v in enumerate(rms):
            if v <= _QUIET:
                run += 1
                if run >= gap and i + 1 < len(rms) and rms[i + 1] > _QUIET:
                    # a loud region existed before the quiet gap -> leading burst
                    if np.any(rms[: i + 1] > _QUIET * 4):
                        return audio[(i + 1) * win:]
            else:
                run = 0
        return audio

    @classmethod
    def _trim_edges(cls, audio: np.ndarray, rate: int) -> np.ndarray:
        rms, win = cls._windowed_rms(audio, rate)
        speech = np.where(rms > _QUIET)[0]
        if speech.size == 0:
            return audio
        pad = int(_PAD * rate)
        start = max(0, speech[0] * win - pad)
        end = min(audio.size, (speech[-1] + 1) * win + pad)
        return audio[start:end]

    @staticmethod
    def _parallel(audio: np.ndarray, rate: int):
        """whisper n_processors for long audio; None (sequential) for short."""
        if len(audio) / rate >= _PARALLEL_FROM:
            return 2
        return None

    def transcribe_to(self, wav_path: str, txt_dir: str) -> str:
        """Transcribe wav_path into a .txt file in txt_dir. Returns the path.

        Idempotent: reuses an existing non-empty transcript if present.
        """
        txt_path = transcript_path(wav_path, txt_dir)
        if os.path.exists(txt_path) and os.path.getsize(txt_path) > 0:
            return txt_path
        os.makedirs(txt_dir, exist_ok=True)
        logger.info("transcribing %s ...", wav_path)
        text = self.transcribe(wav_path)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(text if text.strip() else "\n")
        logger.info("transcribed %s (%d chars)", txt_path, len(text))
        return txt_path


def transcript_path(wav_path: str, txt_dir: str) -> str:
    """Pair a segment wav with its transcript .txt path."""
    base = os.path.basename(wav_path)
    stem = base.rsplit(".", 1)[0]
    return os.path.join(txt_dir, f"{stem}.txt")


def resolve_model_path() -> str:
    """Return the first existing model from MODEL_CANDIDATES."""
    for p in MODEL_CANDIDATES:
        if os.path.exists(p):
            return p
    return DEFAULT_MODEL


def default_transcriber() -> Transcriber:
    return Transcriber()