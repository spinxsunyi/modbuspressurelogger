"""Operational audio regression tests; no speakers or Windows required."""
import threading
import time
import pytest
from sounds import SoundManager, PATTERNS

EXPECTED={
    'connected','manual_disconnect','connection_lost','connection_failed',
    'recording_started','recording_stopped','recording_interrupted','storage_error',
}

def test_all_eight_operational_sound_patterns_defined():
    assert set(PATTERNS)==EXPECTED
    for pattern in PATTERNS.values():
        assert pattern and all(duration>0 and frequency>=0 for frequency,duration in pattern)

def test_sound_is_asynchronous_and_nonblocking():
    started=threading.Event()
    release=threading.Event()
    completed=threading.Event()
    def slow_backend(pattern):
        started.set()
        release.wait(2)
        completed.set()
    manager=SoundManager(backend=slow_backend)
    try:
        before=time.monotonic()
        assert manager.play('connected')
        assert time.monotonic()-before<0.25
        assert started.wait(1)
        before=time.monotonic()
        assert manager.play('recording_started')
        assert time.monotonic()-before<0.25
    finally:
        release.set()
    assert completed.wait(1)
    manager.worker.join(2)

def test_global_mute_prevents_playback_and_clears_pending():
    heard=[]
    manager=SoundManager(enabled=False,backend=lambda pattern:heard.append(pattern))
    assert manager.play('connected') is False
    assert not heard
    manager.set_enabled(True)
    assert manager.play('recording_started')
    manager.worker.join(1)
    assert heard==[PATTERNS['recording_started']]
    manager.set_enabled(False)
    assert manager.play('storage_error') is False
    assert heard==[PATTERNS['recording_started']]

def test_unknown_sound_rejected():
    manager=SoundManager(enabled=False)
    with pytest.raises(ValueError):
        manager.play('unknown_event')

def test_audio_backend_failure_does_not_crash_worker():
    manager=SoundManager(backend=lambda pattern:(_ for _ in ()).throw(OSError('no speaker')))
    assert manager.play('storage_error')
    manager.worker.join(1)
    assert not manager.worker.is_alive()
