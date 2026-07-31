from __future__ import annotations

from pathlib import Path

from app.gui.widgets.preview_waveform import PreviewWaveformWidget
from app.models.voice_preview import VoicePreviewResult


def test_voice_preview_result_exposes_cache_and_latency(tmp_path: Path) -> None:
    target = tmp_path / "preview.wav"
    target.write_bytes(b"audio")
    result = VoicePreviewResult(path=target, cache_hit=True, latency_ms=7)

    assert result.path == target
    assert result.cache_hit is True
    assert result.latency_ms == 7


def test_preview_waveform_is_deterministic_and_clears(qt_app, tmp_path: Path) -> None:
    target = tmp_path / "preview.mp3"
    target.write_bytes(bytes(range(256)) * 8)
    widget = PreviewWaveformWidget()

    widget.set_path(target)
    first = widget.samples
    widget.set_path(target)
    second = widget.samples

    assert first
    assert first == second
    assert all(0.0 < value <= 1.0 for value in first)

    widget.clear()
    assert widget.samples == ()


def test_voice_browser_preview_worker_uses_request_identity() -> None:
    from app.gui.voice_browser import _PreviewWorker

    class Service:
        def preview_result(self, item, text, settings):
            return VoicePreviewResult(Path("preview.wav"), False, 10)

    worker = _PreviewWorker(42, Service(), object(), "Hej", object())
    captured = []
    worker.finished.connect(lambda request_id, result: captured.append((request_id, result)))
    worker.run()

    assert captured[0][0] == 42
    assert captured[0][1].latency_ms == 10
