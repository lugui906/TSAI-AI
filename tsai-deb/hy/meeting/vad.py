"""Voice-activity segmentation using webrtcvad.

All audio preprocessing happens here, in the business layer (allowed by the
spec). This emits one fresh wav file per detected speech segment, which is
what gets handed to AIM for transcription / summarization.
"""

from __future__ import annotations

import logging
import os
import wave

import webrtcvad

logger = logging.getLogger("meeting.vad")

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480 samples @16k
FRAME_BYTES = FRAME_SAMPLES * 2                 # s16le mono


class VADConfig:
    """Tuning knobs for segmentation."""

    def __init__(self, aggressiveness: int = 2,
                 min_speech_frames: int = 6,   # ~180ms min voice to keep
                 min_silence_frames: int = 20):  # ~600ms silence ends a turn
        self.aggressiveness = aggressiveness
        self.min_speech_frames = min_speech_frames
        self.min_silence_frames = min_silence_frames


class VadSegmenter:
    """Consumes raw PCM and writes per-segment wav files."""

    def __init__(self, out_dir: str, config: VADConfig | None = None):
        self.out_dir = out_dir
        self.config = config or VADConfig()
        os.makedirs(out_dir, exist_ok=True)
        self._vad = webrtcvad.Vad(self.config.aggressiveness)
        self._frame_size = FRAME_BYTES

        self._in_speech = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._pcm = bytearray()
        self._seg_index = 0

    def process(self, pcm_bytes: bytes) -> list[str]:
        """Feed raw s16le mono 16k PCM. Returns newly finalized segment paths."""
        emitted: list[str] = []
        for start in range(0, len(pcm_bytes) - self._frame_size + 1, self._frame_size):
            frame = bytes(pcm_bytes[start:start + self._frame_size])
            path = self._handle_frame(frame)
            if path:
                emitted.append(path)
        del pcm_bytes
        return emitted

    def _handle_frame(self, frame: bytes) -> str | None:
        speech = self._vad.is_speech(frame, SAMPLE_RATE)
        if speech:
            self._in_speech = True
            self._speech_frames += 1
            self._silence_frames = 0
            self._pcm += frame
        else:
            if self._in_speech:
                self._silence_frames += 1
                self._pcm += frame  # keep trailing silence for natural cadence
                if self._silence_frames >= self.config.min_silence_frames and \
                        self._speech_frames >= self.config.min_speech_frames:
                    return self._finalize_and_reset()
            # not (yet) in speech: keep a little leading context for VAD warm-up
            elif len(self._pcm) < self._frame_size * 30:
                self._pcm += frame
        return None

    def stop(self) -> str | None:
        """Flush any in-progress segment. Call once at end of capture."""
        if self._in_speech and self._speech_frames >= self.config.min_speech_frames:
            return self._finalize_and_reset()
        self._pcm = bytearray()
        return None

    def _finalize_and_reset(self) -> str:
        path = os.path.join(self.out_dir, f"segment_{self._seg_index:05d}.wav")
        _write_wav(path, bytes(self._pcm), SAMPLE_RATE)
        self._seg_index += 1
        logger.info("emitted voice segment %s (%d bytes)", path, len(self._pcm))
        self._in_speech = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._pcm = bytearray()
        return path

    def segments_since(self, index: int) -> list[str]:
        """Return segment files with 00 sequence number >= index."""
        return [
            os.path.join(self.out_dir, name)
            for name in sorted(os.listdir(self.out_dir))
            if name.startswith("segment_") and name.endswith(".wav")
        ]


def _write_wav(path: str, pcm: bytes, rate: int):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)