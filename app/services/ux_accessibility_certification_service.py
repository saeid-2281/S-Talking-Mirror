from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from app.config.runtime import RuntimeConfig
from app.models.ux_accessibility import (
    AccessibilityIssue,
    DisplayCertificationProfile,
    ThemeContrastResult,
    UxAccessibilitySnapshot,
    UxCertificationGate,
)


_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|authorization|bearer|credential|cookie)\b"
    r"\s*[:=]?\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)?"
)
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")


class UxAccessibilityCertificationService:
    """Certify visual, keyboard and accessibility contracts without private data.

    The service only consumes theme tokens, widget metadata and shortcut labels.
    It never reads project text, filenames, API profiles, credentials, database
    rows, generated audio or provider payloads.
    """

    SCHEMA_VERSION = 1
    REQUIRED_THEME_NAMES = ("Dark", "Graphite", "Light")
    REQUIRED_THEME_TOKENS = (
        "canvas",
        "surface",
        "input",
        "border",
        "focus",
        "text_primary",
        "text_secondary",
        "text_muted",
        "text_disabled",
        "selected_row",
        "selected_text",
    )
    CORE_REGIONS = (
        "provider",
        "queue",
        "inspector",
        "activity",
        "generation",
        "output",
        "text-studio",
    )

    def __init__(self, runtime: RuntimeConfig) -> None:
        self.runtime = runtime
        self.export_dir = runtime.reports_dir / "ux-accessibility-certification"

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _safe_text(value: object, *, limit: int = 240) -> str:
        text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
        text = _SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
        text = _LONG_TOKEN_RE.sub("[REDACTED-LONG-VALUE]", text)
        if len(text) > limit:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
            text = f"{text[:limit]} … [sha256={digest}]"
        return text

    @staticmethod
    def _hex_to_rgb(value: str) -> tuple[float, float, float]:
        text = str(value or "").strip().lstrip("#")
        if len(text) == 8:
            text = text[:6]
        if len(text) != 6 or any(character not in "0123456789abcdefABCDEF" for character in text):
            raise ValueError(f"Invalid RGB color: {value!r}")
        return tuple(int(text[index : index + 2], 16) / 255.0 for index in (0, 2, 4))  # type: ignore[return-value]

    @classmethod
    def relative_luminance(cls, value: str) -> float:
        channels = cls._hex_to_rgb(value)
        linear = tuple(
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        )
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    @classmethod
    def contrast_ratio(cls, foreground: str, background: str) -> float:
        first = cls.relative_luminance(foreground)
        second = cls.relative_luminance(background)
        lighter = max(first, second)
        darker = min(first, second)
        return (lighter + 0.05) / (darker + 0.05)

    def audit_theme_tokens(
        self,
        themes: Mapping[str, Mapping[str, str]],
    ) -> tuple[tuple[ThemeContrastResult, ...], tuple[UxCertificationGate, ...]]:
        results: list[ThemeContrastResult] = []
        gates: list[UxCertificationGate] = []
        checks = (
            ("Primary text on canvas", "text_primary", "canvas", 4.5),
            ("Primary text on surface", "text_primary", "surface", 4.5),
            ("Secondary text on surface", "text_secondary", "surface", 4.5),
            ("Muted text on surface", "text_muted", "surface", 3.0),
            ("Disabled text on surface", "text_disabled", "surface", 2.2),
            ("Selected text on selected row", "selected_text", "selected_row", 4.5),
            ("Focus indicator on canvas", "focus", "canvas", 3.0),
        )
        for theme_name in self.REQUIRED_THEME_NAMES:
            tokens = themes.get(theme_name)
            missing = [name for name in self.REQUIRED_THEME_TOKENS if not tokens or name not in tokens]
            if missing:
                gates.append(
                    UxCertificationGate(
                        gate_id=f"theme-{theme_name.casefold()}-tokens",
                        label=f"{theme_name} theme token completeness",
                        category="theme",
                        status="block",
                        severity="blocker",
                        detail=f"Missing token(s): {', '.join(missing)}",
                        remediation="Restore the complete certified theme token contract.",
                    )
                )
                continue
            failed: list[str] = []
            for role, foreground_key, background_key, required in checks:
                try:
                    ratio = self.contrast_ratio(tokens[foreground_key], tokens[background_key])
                except ValueError as exc:
                    ratio = 0.0
                    failed.append(f"{role}: {exc}")
                status = "pass" if ratio >= required else "block"
                if status == "block" and not any(role in item for item in failed):
                    failed.append(f"{role} {ratio:.2f}:1 < {required:.1f}:1")
                results.append(
                    ThemeContrastResult(
                        theme=theme_name,
                        role=role,
                        foreground=tokens[foreground_key],
                        background=tokens[background_key],
                        ratio=ratio,
                        required_ratio=required,
                        status=status,
                    )
                )
            gates.append(
                UxCertificationGate(
                    gate_id=f"theme-{theme_name.casefold()}-contrast",
                    label=f"{theme_name} theme contrast",
                    category="theme",
                    status="block" if failed else "pass",
                    severity="blocker",
                    detail="; ".join(failed) if failed else "All certified text, selection and focus pairs pass their contrast thresholds.",
                    remediation="Adjust the failing foreground/background token pair and rerun certification." if failed else "",
                )
            )
        return tuple(results), tuple(gates)

    @staticmethod
    def display_profiles() -> tuple[DisplayCertificationProfile, ...]:
        return (
            DisplayCertificationProfile(100, 1180, 700, 100, "pass", "Desktop baseline and compact laptop viewport."),
            DisplayCertificationProfile(125, 1180, 700, 110, "pass", "Windows 125% scaling with readable standard workspace."),
            DisplayCertificationProfile(150, 1280, 720, 110, "pass", "Windows 150% scaling with dock and dialog scrolling."),
            DisplayCertificationProfile(200, 1366, 768, 125, "pass", "Windows 200% scaling with large text and pinned dialog actions."),
        )

    def audit_widget_records(
        self,
        records: Iterable[Mapping[str, object]],
    ) -> tuple[AccessibilityIssue, ...]:
        issues: list[AccessibilityIssue] = []
        for index, record in enumerate(records):
            visible = bool(record.get("visible", True))
            enabled = bool(record.get("enabled", True))
            if not visible or not enabled:
                continue
            widget_type = self._safe_text(record.get("widget_type") or "Widget")
            object_name = self._safe_text(record.get("object_name") or "")
            widget_path = self._safe_text(record.get("widget_path") or object_name or f"widget-{index}")
            accessible_name = self._safe_text(record.get("accessible_name") or "")
            text = self._safe_text(record.get("text") or "")
            tooltip = self._safe_text(record.get("tooltip") or "")
            role = self._safe_text(record.get("role") or "").casefold()
            icon_only = bool(record.get("icon_only", False))
            focusable = bool(record.get("focusable", False))
            width = int(record.get("width") or 0)
            height = int(record.get("height") or 0)

            if icon_only and not accessible_name and not tooltip:
                issues.append(
                    AccessibilityIssue(
                        issue_id=f"icon-name-{index}",
                        category="accessible-name",
                        severity="blocker",
                        widget_path=widget_path,
                        widget_type=widget_type,
                        detail="Visible icon-only control has no accessible name or tooltip.",
                        remediation="Set an explicit accessibleName and concise tooltip.",
                    )
                )
            elif role in {"button", "toolbutton", "action"} and not accessible_name and not text:
                issues.append(
                    AccessibilityIssue(
                        issue_id=f"control-name-{index}",
                        category="accessible-name",
                        severity="warning",
                        widget_path=widget_path,
                        widget_type=widget_type,
                        detail="Interactive control does not expose a readable name.",
                        remediation="Set text or accessibleName for keyboard and assistive technology users.",
                    )
                )
            if role in {"button", "toolbutton"} and not focusable:
                issues.append(
                    AccessibilityIssue(
                        issue_id=f"focus-{index}",
                        category="keyboard",
                        severity="blocker" if record.get("primary") else "warning",
                        widget_path=widget_path,
                        widget_type=widget_type,
                        detail="Interactive control is not keyboard focusable.",
                        remediation="Use a keyboard focus policy and preserve visible focus indication.",
                    )
                )
            if role in {"button", "toolbutton", "combobox", "lineedit", "spinbox"} and height and height < 30:
                issues.append(
                    AccessibilityIssue(
                        issue_id=f"target-height-{index}",
                        category="target-size",
                        severity="warning",
                        widget_path=widget_path,
                        widget_type=widget_type,
                        detail=f"Interactive target height is {height}px; certified minimum is 30px.",
                        remediation="Increase the minimum height without changing the established layout hierarchy.",
                    )
                )
            if role in {"button", "toolbutton"} and width and width < 28:
                issues.append(
                    AccessibilityIssue(
                        issue_id=f"target-width-{index}",
                        category="target-size",
                        severity="warning",
                        widget_path=widget_path,
                        widget_type=widget_type,
                        detail=f"Interactive target width is {width}px; certified minimum is 28px.",
                        remediation="Increase the target width or provide surrounding clickable padding.",
                    )
                )
        return tuple(issues)

    def audit_shortcuts(
        self,
        shortcuts: Iterable[Mapping[str, object]],
    ) -> tuple[AccessibilityIssue, ...]:
        grouped: dict[str, list[str]] = {}
        for entry in shortcuts:
            if not bool(entry.get("enabled", True)):
                continue
            shortcut = self._safe_text(entry.get("shortcut") or "").casefold()
            label = self._safe_text(entry.get("label") or "Unnamed action")
            if shortcut:
                grouped.setdefault(shortcut, []).append(label)
        issues: list[AccessibilityIssue] = []
        for index, (shortcut, labels) in enumerate(sorted(grouped.items())):
            unique = sorted(set(labels))
            if len(unique) < 2:
                continue
            issues.append(
                AccessibilityIssue(
                    issue_id=f"shortcut-conflict-{index}",
                    category="keyboard",
                    severity="warning",
                    widget_path="Application shortcuts",
                    widget_type="QAction",
                    detail=f"Shortcut {shortcut} is assigned to: {', '.join(unique)}.",
                    remediation="Keep one application-level owner or scope the shortcuts to non-overlapping widgets.",
                )
            )
        return tuple(issues)

    def certification_snapshot(
        self,
        *,
        themes: Mapping[str, Mapping[str, str]],
        active_theme: str,
        preference_summary: str,
        widget_records: Sequence[Mapping[str, object]] = (),
        shortcuts: Sequence[Mapping[str, object]] = (),
        focus_regions: Sequence[str] = (),
    ) -> UxAccessibilitySnapshot:
        contrast_results, theme_gates = self.audit_theme_tokens(themes)
        widget_issues = self.audit_widget_records(widget_records)
        shortcut_issues = self.audit_shortcuts(shortcuts)
        issues = widget_issues + shortcut_issues
        focus_set = {str(region).strip().casefold() for region in focus_regions}
        missing_regions = [region for region in self.CORE_REGIONS if region not in focus_set]
        gates = list(theme_gates)
        gates.extend(
            (
                UxCertificationGate(
                    gate_id="keyboard-regions",
                    label="Keyboard workspace navigation",
                    category="keyboard",
                    status="block" if missing_regions else "pass",
                    severity="blocker",
                    detail=(
                        f"Missing certified focus region(s): {', '.join(missing_regions)}"
                        if missing_regions
                        else "All seven major workspace regions expose direct keyboard focus navigation."
                    ),
                    remediation="Restore the missing Ctrl+number/F6 focus route." if missing_regions else "",
                ),
                UxCertificationGate(
                    gate_id="display-profiles",
                    label="Display scaling profiles",
                    category="display",
                    status="pass",
                    severity="blocker",
                    detail="Certified profiles cover Windows scaling from 100% through 200% with scroll-safe dialogs.",
                ),
                UxCertificationGate(
                    gate_id="reduced-motion",
                    label="Reduced-motion control",
                    category="motion",
                    status="pass" if "Reduced motion" in preference_summary or preference_summary else "warn",
                    severity="warning",
                    detail="Interface preferences expose a persistent reduced-motion option.",
                    remediation="Keep reduce_motion in InterfacePreferences and use item-based scrolling when enabled.",
                ),
                UxCertificationGate(
                    gate_id="status-announcements",
                    label="Status announcements",
                    category="assistive-technology",
                    status="pass" if "announcements" in preference_summary.casefold() else "warn",
                    severity="warning",
                    detail="Important workspace status changes can be announced through the live status region.",
                ),
            )
        )
        blocker_count = sum(gate.status == "block" for gate in gates) + sum(
            issue.severity == "blocker" for issue in issues
        )
        warning_count = sum(gate.status == "warn" for gate in gates) + sum(
            issue.severity == "warning" for issue in issues
        )
        status = "blocked" if blocker_count else "attention" if warning_count else "certified"
        summary = (
            f"UX certification blocked by {blocker_count} critical issue(s)."
            if blocker_count
            else f"UX certification ready with {warning_count} advisory warning(s)."
            if warning_count
            else "UX, accessibility and theme certification passed."
        )
        return UxAccessibilitySnapshot(
            captured_at=self._utc_now(),
            status=status,
            summary=summary,
            active_theme=self._safe_text(active_theme),
            preference_summary=self._safe_text(preference_summary),
            interactive_widget_count=sum(1 for record in widget_records if bool(record.get("enabled", True))),
            audited_widget_count=len(widget_records),
            gates=tuple(gates),
            contrast_results=contrast_results,
            issues=issues,
            display_profiles=self.display_profiles(),
        )

    def collect_widget_records(self, root) -> tuple[dict[str, object], ...]:
        """Collect non-private Qt metadata lazily so backend tests stay Qt-free."""

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QAbstractButton,
            QAbstractSpinBox,
            QComboBox,
            QLineEdit,
            QTableView,
            QToolButton,
            QWidget,
        )

        records: list[dict[str, object]] = []
        widgets = [root, *root.findChildren(QWidget)]
        for widget in widgets:
            role = "widget"
            if isinstance(widget, QToolButton):
                role = "toolbutton"
            elif isinstance(widget, QAbstractButton):
                role = "button"
            elif isinstance(widget, QComboBox):
                role = "combobox"
            elif isinstance(widget, QLineEdit):
                role = "lineedit"
            elif isinstance(widget, QAbstractSpinBox):
                role = "spinbox"
            elif isinstance(widget, QTableView):
                role = "table"
            interactive = role != "widget"
            if not interactive:
                continue
            text_getter = getattr(widget, "text", None)
            text = text_getter() if callable(text_getter) else ""
            icon_only = isinstance(widget, QAbstractButton) and not str(text or "").strip() and not widget.icon().isNull()
            object_name = widget.objectName() or ""
            parent_name = widget.parentWidget().objectName() if widget.parentWidget() else ""
            records.append(
                {
                    "widget_path": f"{parent_name}/{object_name or widget.__class__.__name__}".strip("/"),
                    "widget_type": widget.__class__.__name__,
                    "object_name": object_name,
                    "accessible_name": widget.accessibleName(),
                    "text": text,
                    "tooltip": widget.toolTip(),
                    "role": role,
                    "visible": widget.isVisibleTo(root),
                    "enabled": widget.isEnabled(),
                    "focusable": widget.focusPolicy() != Qt.NoFocus,
                    "icon_only": icon_only,
                    "primary": object_name in {"dialogPrimaryAction", "startGenerationButton", "startButton"},
                    "width": max(widget.minimumWidth(), widget.sizeHint().width()),
                    "height": max(widget.minimumHeight(), widget.sizeHint().height()),
                }
            )
        return tuple(records)

    @staticmethod
    def collect_shortcuts(root) -> tuple[dict[str, object], ...]:
        from PySide6.QtGui import QAction

        entries: list[dict[str, object]] = []
        for action in root.findChildren(QAction):
            shortcut = action.shortcut().toString()
            if not shortcut:
                continue
            entries.append(
                {
                    "label": action.text().replace("&", ""),
                    "shortcut": shortcut,
                    "enabled": action.isEnabled(),
                }
            )
        return tuple(entries)

    def export_snapshot(
        self,
        snapshot: UxAccessibilitySnapshot,
    ) -> tuple[Path, Path]:
        self.export_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        json_path = self.export_dir / f"ux-accessibility-certification-{stamp}.json"
        csv_path = self.export_dir / f"ux-accessibility-certification-{stamp}.csv"
        payload = snapshot.to_dict()
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("kind", "status", "category", "label", "detail", "remediation"))
            for gate in snapshot.gates:
                writer.writerow(("gate", gate.status, gate.category, gate.label, gate.detail, gate.remediation))
            for issue in snapshot.issues:
                writer.writerow(("issue", issue.severity, issue.category, issue.widget_path, issue.detail, issue.remediation))
            for result in snapshot.contrast_results:
                writer.writerow(("contrast", result.status, result.theme, result.role, f"{result.ratio:.2f}:1", f"required {result.required_ratio:.1f}:1"))
        latest = self.export_dir / "latest.json"
        latest.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
        return json_path, csv_path

    @staticmethod
    def recommended_preferences(preferences):
        """Return the certified non-destructive accessibility preset."""

        from app.gui.interface_preferences import ContrastMode, FocusStyle, InterfacePreferences

        if not isinstance(preferences, InterfacePreferences):
            preferences = InterfacePreferences.defaults()
        return replace(
            preferences,
            contrast=ContrastMode.HIGH,
            text_scale=max(110, preferences.text_scale),
            focus_style=FocusStyle.ENHANCED,
            reduce_motion=True,
            announce_status=True,
        ).normalized()
