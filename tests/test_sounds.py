"""Modern UI sound regression tests; no Windows or speakers required."""
import io
import threading
import time
import wave

import pytest
from sounds import SoundManager, PATTERNS, _render_wav

EXPECTED = {
    'connected', 'manual_disconnect', 'connection_lost', 'connection_failed',
    'recording_started', 'recording_stopped', 'recording_interrupted', 'storage_error',
}


def test_all_eight_operational_sound_patterns_defined():
    assert set(PATTERNS) == EXPECTED
    for pattern in PATTERNS.values():
        assert pattern and all(duration > 0 and frequency >= 0 for frequency, duration in pattern)


def test_modern_ui_wav_valid_and_distinct():
    rendered = [_render_wav(PATTERNS[event]) for event in sorted(EXPECTED)]
    assert len(set(rendered)) == 8
    for sound in rendered:
        with wave.open(io.BytesIO(sound), 'rb') as audio:
            assert audio.getnchannels() == 1
            assert audio.getsampwidth() == 2
            assert audio.getframerate() == 22050
            assert audio.getnframes() > 2205


def test_sound_is_asynchronous_and_nonblocking():
    started = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def slow_backend(pattern):
        started.set()
        release.wait(2)
        completed.set()

    manager = SoundManager(backend=slow_backend)
    try:
        before = time.monotonic()
        assert manager.play('connected')
        assert time.monotonic() - before < .25
        assert started.wait(1)
        before = time.monotonic()
        assert manager.play('recording_started')
        assert time.monotonic() - before < .25
    finally:
        release.set()
    assert completed.wait(1)


def test_global_mute_prevents_playback_and_clears_pending():
    heard = []
    heard_event = threading.Event()

    def backend(pattern):
        heard.append(pattern)
        heard_event.set()

    manager = SoundManager(enabled=False, backend=backend)
    assert manager.play('connected') is False
    assert not heard
    manager.set_enabled(True)
    assert manager.play('recording_started')
    assert heard_event.wait(1)
    assert heard == [PATTERNS['recording_started']]
    manager.set_enabled(False)
    assert manager.play('storage_error') is False
    assert heard == [PATTERNS['recording_started']]


def test_mute_clears_queued_audio():
    started = threading.Event()
    release = threading.Event()
    heard = []

    def backend(pattern):
        heard.append(pattern)
        started.set()
        release.wait(1)

    manager = SoundManager(backend=backend)
    assert manager.play('connected')
    assert started.wait(1)
    assert manager.play('storage_error')
    manager.set_enabled(False)
    release.set()
    time.sleep(.05)
    assert heard == [PATTERNS['connected']]


def test_unknown_sound_rejected():
    manager = SoundManager(enabled=False)
    with pytest.raises(ValueError):
        manager.play('unknown_event')


def test_audio_backend_failure_does_not_crash_worker():
    called = threading.Event()

    def failing_backend(pattern):
        called.set()
        raise OSError('no speaker')

    manager = SoundManager(backend=failing_backend)
    assert manager.play('storage_error')
    assert called.wait(1)
    # The persistent worker remains available after playback failures.
    assert manager.worker.is_alive()
