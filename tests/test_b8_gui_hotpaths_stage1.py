"""B8.2B stage 1: nonblocking provider analysis and packaged health checks."""
from __future__ import annotations

import queue
import threading
from types import SimpleNamespace

from app.gui.main import MainWindow
from app.models.domain import AppSettings
from app.services.git_service import GitStatus
from app.services.health_service import HealthService


class _RoutingSignal:
    def __init__(self):
        self.results = queue.Queue()

    def emit(self, generation, signature, result):
        self.results.put((generation, signature, result))


class _RoutingService:
    def __init__(self):
        self.calls = []
        self.release = threading.Event()

    def analyze(self, **kwargs):
        self.calls.append(kwargs)
        self.release.wait(timeout=5)
        return SimpleNamespace(scoped_jobs=kwargs['scoped_jobs'], provider=kwargs['settings'].provider)


class _FakeMain:
    refresh_smart_provider_routing = MainWindow.refresh_smart_provider_routing
    _smart_routing_apply = MainWindow._smart_routing_apply
    _smart_routing_start_worker = MainWindow._smart_routing_start_worker
    _smart_routing_completed = MainWindow._smart_routing_completed

    def __init__(self):
        self.smart_provider_routing = SimpleNamespace(set_state=self._set_state)
        self.provider = SimpleNamespace(currentText=lambda: 'mock')
        self.generation_controller = SimpleNamespace(generation_jobs=lambda: [], is_active=False)
        self.project_controller = SimpleNamespace(current_project=None)
        self.connection_status = SimpleNamespace(toolTip=lambda: '', text=lambda: 'Ready')
        self.smart_provider_routing_service = _RoutingService()
        self._smart_routing_ready = _RoutingSignal()
        self._test_fast_path = False
        self._routing_generation = 0
        self._routing_worker_active = False
        self._routing_pending_request = None
        self._routing_closing = False
        self.applied = []

    def settings(self):
        return AppSettings(provider='mock', model_id='model', voice_id='voice')

    def _smart_provider_routing_profile(self, settings):
        return None

    def smart_provider_routing_preference(self):
        return 'balanced'

    def _set_state(self, state):
        self.applied.append(state)

    def statusBar(self):
        return SimpleNamespace(showMessage=lambda *args: None)


def test_routing_analysis_does_not_run_on_caller_thread():
    main = _FakeMain()
    assert main.refresh_smart_provider_routing(force=True) is None
    assert main.applied == []
    main.smart_provider_routing_service.release.set()
    result = main._smart_routing_ready.results.get(timeout=8)
    main._smart_routing_completed(*result)
    assert len(main.applied) == 1
    assert main.applied[0].provider == 'mock'
    assert len(main.smart_provider_routing_service.calls) == 1


def test_routing_coalesces_and_drops_stale_result():
    main = _FakeMain()
    assert main.refresh_smart_provider_routing(force=True) is None
    main.connection_status = SimpleNamespace(toolTip=lambda: '', text=lambda: 'Changed')
    main.refresh_smart_provider_routing(force=True)
    main.smart_provider_routing_service.release.set()
    first = main._smart_routing_ready.results.get(timeout=8)
    main._smart_routing_completed(*first)
    assert main.applied == []
    second = main._smart_routing_ready.results.get(timeout=8)
    main._smart_routing_completed(*second)
    assert len(main.applied) == 1
    assert len(main.smart_provider_routing_service.calls) == 2


def test_manual_routing_apply_remains_synchronous_and_does_not_switch_provider():
    main = _FakeMain()
    main.smart_provider_routing_service.release.set()
    state = main.refresh_smart_provider_routing(force=True, synchronous=True)
    assert state is main.applied[0]
    assert main.provider.currentText() == 'mock'
    assert main._routing_worker_active is False


def test_packaged_health_metadata_skips_git_subprocess(monkeypatch, tmp_path):
    class NoGit:
        def status(self):
            raise AssertionError('packaged runtime must never query Git')

    runtime = SimpleNamespace(artifacts_dir=tmp_path)
    report = SimpleNamespace(latest_report_dir=lambda: None)
    service = HealthService(runtime, NoGit(), report, SimpleNamespace(latest_bundle=None))
    monkeypatch.setattr(HealthService, '_is_packaged_runtime', staticmethod(lambda: True))
    git, *_ = service._metadata()
    assert isinstance(git, GitStatus)
    assert git.branch == 'not_applicable'
    assert git.clean


def test_source_health_still_queries_git(monkeypatch, tmp_path):
    class Git:
        calls = 0
        def status(self):
            self.calls += 1
            return GitStatus('feature/b8', False, ['app/gui/main.py'])

    git = Git()
    runtime = SimpleNamespace(artifacts_dir=tmp_path)
    service = HealthService(runtime, git, SimpleNamespace(latest_report_dir=lambda: None), SimpleNamespace(latest_bundle=None))
    monkeypatch.setattr(HealthService, '_is_packaged_runtime', staticmethod(lambda: False))
    assert service._metadata()[0].branch == 'feature/b8'
    assert git.calls == 1
