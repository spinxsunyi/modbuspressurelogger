"""Non-blocking, dependency-free Modern UI operational sounds for Windows.

All audio is synthesized in memory as PCM WAV, with no external assets or
runtime installation. Audio errors never interrupt pressure acquisition.
"""
import io
import math
import os
import queue
import struct
import threading
import wave
from functools import lru_cache

# (frequency Hz, duration ms); 0 Hz represents a short intentional pause.
# Retained as stable, inspectable event definitions for callers and tests.
PATTERNS = {
    'connected': ((659, 90), (988, 165), (1319, 220)),
    'manual_disconnect': ((784, 115), (587, 150), (440, 145)),
    'connection_lost': ((494, 150), (0, 90), (494, 150), (0, 90), (392, 210)),
    'connection_failed': ((392, 160), (330, 210)),
    'recording_started': ((587, 95), (880, 125), (1175, 200)),
    'recording_stopped': ((880, 125), (659, 145), (523, 180)),
    'recording_interrupted': ((587, 140), (0, 75), (494, 140), (0, 75), (587, 190)),
    'storage_error': ((392, 170), (0, 70), (330, 180), (0, 70), (262, 250)),
}

_SAMPLE_RATE = 22050


@lru_cache(maxsize=16)
def _render_wav(pattern):
    """Create a gentle, layered UI chime with attack/release and a quiet tail."""
    samples = []
    for index, (frequency, duration_ms) in enumerate(pattern):
        count = max(1, int(_SAMPLE_RATE * duration_ms / 1000))
        if not frequency:
            samples.extend([0] * count)
            continue
        for n in range(count):
            t = n / _SAMPLE_RATE
            progress = n / count
            # Soft attack, rounded sustain, no click on release.
            attack = min(1.0, n / max(1, int(.014 * _SAMPLE_RATE)))
            release = min(1.0, (count - n - 1) / max(1, int(.075 * _SAMPLE_RATE)))
            envelope = max(0.0, min(attack, release)) ** 1.25
            fundamental = math.sin(2 * math.pi * frequency * t)
            harmonic = .18 * math.sin(2 * math.pi * frequency * 2 * t)
            shimmer = .10 * math.sin(2 * math.pi * (frequency * 1.005) * t)
            value = .21 * envelope * (fundamental + harmonic + shimmer)
            samples.append(int(max(-1, min(1, value)) * 32767))
    # Low-volume, decaying echo gives a modern notification feel.
    delay = int(.085 * _SAMPLE_RATE)
    tail = int(.16 * _SAMPLE_RATE)
    dry = samples + [0] * tail
    for i in range(delay, len(dry)):
        source = i - delay
        if source < len(samples):
            dry[i] = max(-32768, min(32767, dry[i] + int(samples[source] * .16)))
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(_SAMPLE_RATE)
        wav.writeframes(struct.pack('<' + 'h' * len(dry), *dry))
    return output.getvalue()


class SoundManager:
    """Bounded non-blocking queue; one persistent daemon playback worker."""

    def __init__(self, enabled=True, backend=None):
        self.enabled = bool(enabled)
        self.backend = backend if backend is not None else self._windows_backend
        self.events = queue.Queue(maxsize=8)
        self._lock = threading.Lock()
        self.worker = threading.Thread(
            target=self._run, daemon=True, name='pressure-logger-audio'
        )
        self.worker.start()

    @staticmethod
    def _windows_backend(pattern):
        if os.name != 'nt':
            return
        import winsound
        winsound.PlaySound(
            _render_wav(pattern), winsound.SND_MEMORY | winsound.SND_SYNC
        )

    def set_enabled(self, enabled):
        with self._lock:
            self.enabled = bool(enabled)
            if not self.enabled:
                while True:
                    try:
                        self.events.get_nowait()
                    except queue.Empty:
                        break

    def play(self, event):
        if event not in PATTERNS:
            raise ValueError('Unknown sound event: ' + str(event))
        with self._lock:
            if not self.enabled:
                return False
            try:
                self.events.put_nowait(event)
            except queue.Full:
                return False
        return True

    def _run(self):
        while True:
            event = self.events.get()
            with self._lock:
                enabled = self.enabled
            if enabled:
                try:
                    self.backend(PATTERNS[event])
                except Exception:
                    pass  # Missing audio device must never affect recording.
