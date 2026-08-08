from __future__ import annotations

import ast
from pathlib import Path

from PySide6.QtWidgets import QPushButton

from app.gui.dialogs.operations_workspace_dialog import OperationsWorkspaceDialog
from app.models.operations_command_center import (
    OperationsCommandSnapshot,
    OperationsDomainStatus,
)


ROOT = Path(__file__).resolve().parents[1]
DIALOG = ROOT / "app/gui/dialogs/operations_workspace_dialog.py"
MAIN = ROOT / "app/gui/main.py"
DIALOG_INIT = ROOT / "app/gui/dialogs/__init__.py"
DOC = ROOT / "docs/OPERATIONS_WORKSPACE_PHASE85.md"


class _SnapshotService:
    def snapshot(self, *, project_id: int | None = None) -> OperationsCommandSnapshot:
        return OperationsCommandSnapshot(
            snapshot_id="phase85-test",
            generated_at="2026-08-08T12:00:00+00:00",
            version="1.0.0",
            channel="stable",
            project_id=project_id,
            overall_status="attention",
            status_summary="One operational domain needs review.",
            domains=(
                OperationsDomainStatus(
                    code="slo",
                    label="SLO",
                    status="healthy",
                    headline="SLO is within target.",
                    metric="99.99%",
                    detail="Verified SLO evidence.",
                    action_code="service-level-objectives",
                ),
                OperationsDomainStatus(
                    code="billing",
                    label="Billing",
                    status="warning",
                    headline="Billing review is due.",
                    metric="1 review",
                    detail="Verified financial evidence needs review.",
                    action_code="financial-audit",
                ),
            ),
            recommendations=("Review billing evidence.",),
        )


def _dialog_text() -> str:
    return DIALOG.read_text(encoding="utf-8")


def _main_text() -> str:
    return MAIN.read_text(encoding="utf-8")


def test_phase85_dialog_builds_seven_section_workspace(qt_app) -> None:
    dialog = OperationsWorkspaceDialog(_SnapshotService(), project_id=7)
    assert dialog.navigation.count() == 7
    assert dialog.pages.count() == 7
    assert dialog.search.accessibleName() == "Filter operational tools"
    assert dialog.current_snapshot is not None
    assert dialog.current_snapshot.project_id == 7


def test_phase85_refresh_projects_verified_domain_status(qt_app) -> None:
    dialog = OperationsWorkspaceDialog(_SnapshotService())
    assert dialog.healthy_label.text() == "Healthy 1"
    assert dialog.warning_label.text() == "Warning 1"
    assert dialog.critical_label.text() == "Critical 0"
    assert dialog.domain_table.rowCount() == 2
    assert dialog.tool_status_labels["service-level-objectives"].text() == "Healthy"
    assert dialog.tool_status_labels["financial-audit"].text() == "Warning"


def test_phase85_filter_focuses_matching_operational_group(qt_app) -> None:
    dialog = OperationsWorkspaceDialog(_SnapshotService())
    dialog.search.setText("billing")
    qt_app.processEvents()
    assert dialog.group_items["Overview"].isHidden()
    assert not dialog.group_items["Recovery"].isHidden()
    assert not dialog.group_items["Providers & Billing"].isHidden()
    assert dialog.navigation.currentItem().text() == "Providers & Billing"


def test_phase85_filter_falls_back_to_first_matching_tool_group(qt_app) -> None:
    dialog = OperationsWorkspaceDialog(_SnapshotService())
    dialog.search.setText("duplicate prevention")
    qt_app.processEvents()
    assert not dialog.group_items["Recovery"].isHidden()
    assert dialog.group_items["Providers & Billing"].isHidden()
    assert dialog.navigation.currentItem().text() == "Recovery"


def test_phase85_open_controls_emit_existing_specialist_code(qt_app) -> None:
    dialog = OperationsWorkspaceDialog(_SnapshotService())
    requested: list[str] = []
    dialog.openRequested.connect(requested.append)
    target = next(
        button
        for button in dialog.findChildren(QPushButton)
        if button.accessibleName() == "Open Financial Audit & Cost Integrity"
    )
    target.click()
    assert requested == ["financial-audit"]


def test_phase85_workspace_module_parses_and_exports_dialog() -> None:
    ast.parse(_dialog_text())
    init_text = DIALOG_INIT.read_text(encoding="utf-8")
    assert "OperationsWorkspaceDialog" in init_text
    assert '"OperationsWorkspaceDialog"' in init_text


def test_phase85_workspace_is_navigation_only_and_read_only() -> None:
    text = _dialog_text()
    assert "self.service.snapshot(" in text
    for token in (
        ".sync(",
        ".create_certification(",
        ".create_backup(",
        ".restore_backup(",
        ".save_policy(",
        ".reconcile(",
    ):
        assert token not in text


def test_phase85_reports_menu_is_consolidated_without_losing_legacy_actions() -> None:
    text = _main_text()
    for label in (
        "Operations Workspace",
        "Operations & Governance",
        "Release, Security & Runtime",
        "Generation Analytics & Controls",
        "Reports & Diagnostics",
        "Production Operations Command Center",
        "Operational Persistence & Evidence Store",
        "Operational Readiness Final Certification",
        "Provider Performance Governance",
        "Financial Audit & Cost Integrity",
        "Generation History",
        "Export Diagnostics",
    ):
        assert label in text
    assert "self.actions_by_name[text]=action" in text


def test_phase85_main_routes_workspace_tools_and_promotes_discovery() -> None:
    text = _main_text()
    assert "def open_operations_workspace(self):" in text
    assert "dialog.openRequested.connect(self._open_operations_tool)" in text
    assert "def _open_operations_tool(self,code):" in text
    assert "Reports: Operations Workspace" in text
    tree = ast.parse(text)
    discovery_lists = [
        ast.literal_eval(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.List)
        and all(
            isinstance(item, ast.Constant) and isinstance(item.value, str)
            for item in node.elts
        )
        and any(
            isinstance(item, ast.Constant) and item.value == "Operations Workspace"
            for item in node.elts
        )
        and any(
            isinstance(item, ast.Constant)
            and item.value == "Production Operations Command Center"
            for item in node.elts
        )
    ]
    assert discovery_lists
    discovery = discovery_lists[0]
    assert discovery.index("Operations Workspace") < discovery.index(
        "Production Operations Command Center"
    )
    for handler in (
        "self.open_incident_triage",
        "self.open_service_level_objectives",
        "self.open_provider_governance",
        "self.open_financial_audit",
        "self.open_operational_readiness",
    ):
        assert handler in text


def test_phase85_documentation_preserves_specialist_and_evidence_contracts() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "does not change operational evidence schemas" in text
    assert "existing specialist dialogs" in text
    assert "read-only" in text
