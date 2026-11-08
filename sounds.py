"""Non-blocking, dependency-free Glass Chime operational sounds for Windows.

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

# (frequency Hz, duration ms); 0 Hz means a deliberate pause.
# Retain stable event tuples for the existing queue/backend API.
PATTERNS = {
    'connected': ((784, 145), (1175, 155), (1568, 240)),
    'manual_disconnect': ((988, 125), (659, 155), (494, 190)),
    'connection_lost': ((587, 145), (0, 85), (587, 145), (0, 85), (440, 245)),
    'connection_failed': ((494, 170), (392, 240)),
    'recording_started': ((440, 75), (0, 40), (659, 175)),
    'recording_stopped': ((784, 120), (523, 205)),
    'recording_interrupted': ((659, 125), (0, 70), (523, 125), (0, 70), (440, 230)),
    'storage_error': ((392, 160), (0, 80), (330, 180), (0, 80), (262, 260)),
}

_SAMPLE_RATE = 22050


@lru_cache(maxsize=16)
def _render_wav(pattern):
    """Render distinctive glass, tactile confirmation, and warning cues.

    Pure PCM synthesis keeps the application portable and avoids binary assets.
    """
    is_record_start = pattern == PATTERNS['recording_started']
    is_warning = pattern in (
        PATTERNS['connection_lost'], PATTERNS['connection_failed'],
        PATTERNS['recording_interrupted'], PATTERNS['storage_error'],
    )
    samples = []
    for index, (frequency, duration_ms) in enumerate(pattern):
        count = max(1, int(_SAMPLE_RATE * duration_ms / 1000))
        if not frequency:
            samples.extend([0] * count)
            continue
        for n in range(count):
            t = n / _SAMPLE_RATE
            progress = n / max(1, count - 1)
            if is_record_start:
                # A dry, tactile tick followed by a short, rounded digital pulse.
                if index == 0:
                    envelope = math.exp(-t * 68)
                    value = .35 * envelope * (
                        math.sin(2 * math.pi * 1900 * t)
                        + .30 * math.sin(2 * math.pi * 2800 * t)
                    )
                else:
                    envelope = min(1.0, t / .008) * math.exp(-t * 18)
                    value = .31 * envelope * (
                        math.sin(2 * math.pi * frequency * t)
                        + .12 * math.sin(2 * math.pi * frequency * 2 * t)
                    )
            elif is_warning:
                # Lower, restrained warnings: distinct from successful actions.
                attack = min(1.0, t / .012)
                release = min(1.0, (1 - progress) / .22)
                envelope = max(0.0, min(attack, release))
                value = .26 * envelope * (
                    math.sin(2 * math.pi * frequency * t)
                    + .12 * math.sin(2 * math.pi * frequency * 1.5 * t)
                )
            else:
                # Glass-like struck resonator: bright partials decay at
                # different rates, with a gentle onset to avoid harsh clicks.
                attack = min(1.0, t / .006)
                envelope = attack * math.exp(-t * 7.2)
                value = .30 * envelope * (
                    math.sin(2 * math.pi * frequency * t)
                    + .34 * math.exp(-t * 12) *
                    math.sin(2 * math.pi * frequency * 2.01 * t)
                    + .13 * math.exp(-t * 18) *
                    math.sin(2 * math.pi * frequency * 3.93 * t)
                )
            samples.append(int(max(-1.0, min(1.0, value)) * 32767))
    # A subtle echo for glass only; avoid muddying confirmation/warning cues.
    if not is_record_start and not is_warning:
        delay = int(.09 * _SAMPLE_RATE)
        tail = int(.19 * _SAMPLE_RATE)
        dry = samples + [0] * tail
        for i in range(delay, len(dry)):
            source = i - delay
            if source < len(samples):
                dry[i] = max(-32768, min(32767, dry[i] + int(samples[source] * .20)))
    else:
        dry = samples
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
            _render_wav(pattern), winsound.SND_MEMORY
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
