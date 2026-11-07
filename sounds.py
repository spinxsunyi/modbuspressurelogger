"""Non-blocking Windows status tones; no external audio assets or dependencies."""
import os
import queue
import threading

PATTERNS = {
    'connected': ((880, 90), (1175, 110)),
    'manual_disconnect': ((880, 90), (587, 120)),
    'connection_lost': ((440, 170), (0, 80), (440, 170)),
    'connection_failed': ((330, 140), (0, 65), (330, 140)),
    'recording_started': ((784, 90), (1047, 140)),
    'recording_stopped': ((784, 100), (523, 130)),
    'recording_interrupted': ((520, 180), (0, 80), (520, 180), (0, 80), (520, 180)),
    'storage_error': ((330, 220), (0, 70), (330, 220), (0, 70), (330, 220)),
}

class SoundManager:
    """One background worker. A full queue drops cues rather than delaying acquisition."""
    def __init__(self, enabled=True, backend=None):
        self.enabled=bool(enabled)
        self.backend=backend if backend is not None else self._windows_backend
        self.events=queue.Queue(maxsize=8)
        self.worker=None
        self._lock=threading.Lock()

    @staticmethod
    def _windows_backend(pattern):
        if os.name!='nt':
            return
        import winsound
        for frequency, duration in pattern:
            if frequency:
                winsound.Beep(frequency,duration)
            else:
                import time
                time.sleep(duration/1000)

    def set_enabled(self, enabled):
        with self._lock:
            self.enabled=bool(enabled)
            if not self.enabled:
                while True:
                    try:self.events.get_nowait()
                    except queue.Empty:break

    def play(self, event):
        if event not in PATTERNS:
            raise ValueError('Unknown sound event: '+str(event))
        with self._lock:
            if not self.enabled:return False
            try:self.events.put_nowait(event)
            except queue.Full:return False
            if self.worker is None or not self.worker.is_alive():
                self.worker=threading.Thread(target=self._run,daemon=True,name='pressure-logger-audio')
                self.worker.start()
        return True

    def _run(self):
        while True:
            try:event=self.events.get_nowait()
            except queue.Empty:return
            with self._lock:
                enabled=self.enabled
            if enabled:
                try:self.backend(PATTERNS[event])
                except Exception:pass  # Missing audio device must never affect recording.
