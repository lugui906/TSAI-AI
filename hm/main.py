#!/usr/bin/env python3
"""Meeting summarization daemon entry.

Pipeline: PipeWire capture -> single full wav -> AIM (newrun/run)
           -> minutes .md + desktop notification.

Recording is continuous (NO VAD segmentation): the whole meeting is kept in
one wav so the AIM summarizer sees full context. It only stops when the
process receives SIGINT/SIGTERM.

Usage:
    python main.py [--out DIR] [--seg DIR] [--target NODE] [--timeout S]
    python main.py --self-test   # run the pipeline against a synthetic wav
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import struct
import sys
import threading
import wave

from aim_client.client import AIMClient, AIMError
from meeting.notify import notify
from meeting.persistence import MeetingStore
from meeting.recorder import (  # noqa: E402
    PipeWireRecorder,
    detect_default_mic_source,
    detect_system_monitor_source,
)
from meeting.scheduler import Scheduler
from meeting.transcribe import Transcriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("meeting.main")

class WavSink:
    """Stream PCM into a single wav; RIFF header back-filled on close()."""

    RATE = 16000        # must match PipeWireRecorder's PCM output rate
    CHANNELS = 1
    SAMPWIDTH = 2

    def __init__(self, path: str, rate: int = RATE):
        self.path = path
        self.rate = rate
        self._data_size = 0
        self._f = open(path, "wb")
        block = rate * self.CHANNELS * self.SAMPWIDTH
        self._f.write(b"RIFF" + struct.pack("<I", 0) + b"WAVE"
                      + b"fmt " + struct.pack("<IHHIIHH", 16, 1, self.CHANNELS,
                                              rate, block,
                                              self.CHANNELS * self.SAMPWIDTH,
                                              self.SAMPWIDTH * 8)
                      + b"data" + struct.pack("<I", 0))

    def write(self, data: bytes):
        self._f.write(data)
        self._data_size += len(data)

    @property
    def seconds(self) -> float:
        return self._data_size / (self.rate * self.CHANNELS * self.SAMPWIDTH)

    def close(self):
        if not self._f.closed:
            self._f.seek(4)
            self._f.write(struct.pack("<I", 36 + self._data_size))
            self._f.seek(40)
            self._f.write(struct.pack("<I", self._data_size))
            self._f.close()

def _run_capture(args, out_dir, seg_dir):
    store = MeetingStore(out_dir)
    scheduler = Scheduler(AIMClient(timeout=args.timeout), seg_dir,
                          on_result=lambda md, first: store.save(md, first=first),
                          transcriber=Transcriber())
    full_path = os.path.join(seg_dir, f"full_{args.source}.wav")
    sink = WavSink(full_path)

    def on_pcm(data: bytes):
        sink.write(data)

    recorder = _make_recorder(args, on_pcm)
    stop_event = threading.Event()

    def stop_handler(signum, frame):
        logger.info("signal %s received, stopping", signum)
        stop_event.set()   # make the main loop exit
        recorder.stop()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    logger.info("meeting capture started (out=%s)", out_dir)
    recorder.start()
    try:
        # record until a stop signal arrives (Ctrl+C / SIGTERM)
        while not stop_event.is_set():
            stop_event.wait(1.0)
    finally:
        sink.close()
        try:
            scheduler.submit([full_path])
        except AIMError as exc:
            logger.error("AIM call failed: %s", exc)
        notify("会议纪要已生成", store.path)
        logger.info("done, minutes at %s", store.path)

def _self_test(args):
    """Synthetic audio round-trip: generate a wav and run it through AIM."""
    out_dir = args.out
    seg_dir = args.seg
    os.makedirs(seg_dir, exist_ok=True)
    store = MeetingStore(out_dir)
    scheduler = Scheduler(AIMClient(timeout=args.timeout), seg_dir,
                          on_result=lambda md, first: store.save(md, first=first),
                          transcriber=Transcriber())

    synth = os.path.join(seg_dir, "synth_tones.wav")
    _write_synth_wav(synth)
    try:
        scheduler.submit([synth])
    except AIMError as exc:
        logger.error("AIM call failed: %s", exc)
    notify("会议纪要已生成", store.path)
    logger.info("self-test done, minutes at %s", store.path)

def _make_recorder(args, on_pcm):
    """Build a recorder for the chosen source (internal / mic)."""
    if args.source == "mic":
        mic = args.target or detect_default_mic_source()
        logger.info("recording from microphone %s", mic)
        return PipeWireRecorder(on_pcm=on_pcm, target=mic,
                                system_internal=False)
    monitor = args.target or detect_system_monitor_source()
    logger.info("recording system internal audio from %s", monitor)
    return PipeWireRecorder(on_pcm=on_pcm, target=monitor,
                            system_internal=True)


def _write_synth_wav(path, seconds: float = 3.0, rate: int = 16000):
    import math
    pcm = bytearray()
    for i in range(int(rate * seconds)):
        # 300Hz tone to exercise the ASR/AIM pipeline
        sample = int(12000 * math.sin(2 * math.pi * 300 * i / rate))
        pcm += sample.to_bytes(2, "little", signed=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(pcm))

def main(argv=None):
    parser = argparse.ArgumentParser(description="TSAI-OS meeting summarizer")
    parser.add_argument("--out", default="meeting_out",
                        help="directory for final minutes .md")
    parser.add_argument("--seg", default="meeting_segments",
                        help="directory for the full meeting wav")
    parser.add_argument("--target", default=None,
                        help="PipeWire node name/id (overrides source auto-detection)")
    parser.add_argument("--source", choices=["internal", "mic"],
                        default="internal",
                        help="audio source: internal (system monitor) or mic")
    parser.add_argument("--timeout", type=float, default=1800,
                        help="AIM command timeout in seconds")
    parser.add_argument("--self-test", action="store_true",
                        help="run a synthetic audio pipeline and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        _self_test(args)
        return 0
    _run_capture(args, args.out, args.seg)
    return 0

if __name__ == "__main__":
    sys.exit(main())
