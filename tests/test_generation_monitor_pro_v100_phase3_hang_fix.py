from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container


def test_recovery_prompt_is_skipped_while_generation_is_active(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.gui.main import MainWindow

    context = create_application_context(
        create_service_container(RuntimeConfig.from_root(tmp_path))
    )

    window = SimpleNamespace(
        generation_controller=SimpleNamespace(is_active=True),
        context=context,
    )

    called = False

    def fail_load():
        nonlocal called
        called = True
        raise AssertionError(
            "Recovery snapshot must not be loaded during active generation"
        )

    monkeypatch.setattr(
        context.generation_recovery_service,
        "load",
        fail_load,
    )

    MainWindow.offer_generation_recovery(window)

    assert called is False
