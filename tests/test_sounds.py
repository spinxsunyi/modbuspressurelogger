"""Glass Chime sound regression tests; no Windows or speakers required."""
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


def test_glass_chime_wav_valid_and_distinct():
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


def test_windows_backend_uses_supported_memory_flag(monkeypatch):
    """Catch invalid winsound constants without requiring a Windows CI runner."""
    import sys
    import types
    import sounds

    calls = []
    fake = types.SimpleNamespace(
        SND_MEMORY=4,
        PlaySound=lambda data, flags: calls.append((data, flags)),
    )
    monkeypatch.setattr(sounds.os, 'name', 'nt')
    monkeypatch.setitem(sys.modules, 'winsound', fake)
    SoundManager._windows_backend(PATTERNS['connected'])
    assert len(calls) == 1
    assert calls[0][0].startswith(b'RIFF')
    assert calls[0][1] == fake.SND_MEMORY


def test_connected_and_recording_start_have_distinct_audio_identity():
    """Connection is a longer glass chime; record start is a short tactile cue."""
    with wave.open(io.BytesIO(_render_wav(PATTERNS['connected'])), 'rb') as wav:
        connected_duration = wav.getnframes() / wav.getframerate()
    with wave.open(io.BytesIO(_render_wav(PATTERNS['recording_started'])), 'rb') as wav:
        recording_duration = wav.getnframes() / wav.getframerate()
    assert connected_duration > recording_duration + .25
    assert _render_wav(PATTERNS['connected']) != _render_wav(PATTERNS['recording_started'])
