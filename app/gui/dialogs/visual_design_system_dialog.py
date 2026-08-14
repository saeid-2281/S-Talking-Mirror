"""Read-only A8 comparison and visual-system reference dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.visual_design_system_v2 import (
    ACTIVE_CONCEPT,
    COMPONENTS,
    ICONS,
    SPACING,
    TYPOGRAPHY,
    UI_INVENTORY,
    concept,
    concept_preview_stylesheet,
    token_rows,
)


class VisualDesignSystemDialog(QDialog):
    """Expose the real A8 inventory, three concepts and selected system."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("visualDesignSystemDialog")
        self.setWindowTitle("Visual Design System 2.0")
        self.resize(1080, 720)
        self.setMinimumSize(880, 600)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        heading = QLabel("Visual Design System 2.0")
        heading.setObjectName("visualDesignSystemTitle")
        heading.setStyleSheet("font-size:20px;font-weight:700;")
        subtitle = QLabel(
            "A8 compares three production-tool directions on real S-Talking surfaces, "
            "then freezes one semantic system for A9–A12 migration."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("visualDesignSystemSubtitle")
        root.addWidget(heading)
        root.addWidget(subtitle)

        selected = concept(ACTIVE_CONCEPT)
        self.selected_badge = QLabel(
            f"Selected direction: {selected.name}  ·  Professional AI Production Tool + Modern Desktop SaaS"
        )
        self.selected_badge.setObjectName("selectedConceptBadge")
        self.selected_badge.setStyleSheet(
            "padding:8px 10px;border-radius:7px;font-weight:600;"
            "background:#EDF1FF;color:#304FBF;border:1px solid #C9D4FF;"
        )
        root.addWidget(self.selected_badge)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("designConceptTabs")
        self.tabs.addTab(self._inventory_page(), "Visual inventory")
        for key in ("precision", "soft_professional", "modern_technical"):
            spec = concept(key)
            label = spec.name + ("  ✓ Selected" if key == ACTIVE_CONCEPT else "")
            self.tabs.addTab(self._concept_page(key), label)
        root.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _inventory_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "Inventory is mapped to the actual S-Talking shell. A8 establishes the visual contract; "
            "A9/A10 migrate workspace and dialog composition without changing production authority."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        table = QTableWidget(len(UI_INVENTORY), 4)
        table.setObjectName("visualInventoryTable")
        table.setHorizontalHeaderLabels(["Area", "Current S-Talking surface", "A8 contract", "Migration"])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        for row, item in enumerate(UI_INVENTORY):
            for col, value in enumerate((item.area, item.current_surface, item.a8_contract, item.migration_phase)):
                table.setItem(row, col, QTableWidgetItem(value))
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(table, 1)
        self.inventory_table = table
        return page

    def _concept_page(self, key: str) -> QWidget:
        spec = concept(key)
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(12)

        specimen = self._specimen(key)
        specimen.setMinimumWidth(500)
        root.addWidget(specimen, 3)

        details = QFrame()
        details.setObjectName("conceptDetails")
        details_layout = QVBoxLayout(details)
        title = QLabel(spec.name + (" — Selected" if key == ACTIVE_CONCEPT else ""))
        title.setStyleSheet("font-size:18px;font-weight:700;")
        description = QLabel(spec.description)
        description.setWordWrap(True)
        traits = QLabel(" · ".join(spec.characteristics))
        traits.setWordWrap(True)
        details_layout.addWidget(title)
        details_layout.addWidget(description)
        details_layout.addWidget(traits)

        token_table = QTableWidget(0, 2)
        token_table.setObjectName(f"{key}TokenTable")
        token_table.setHorizontalHeaderLabels(["Semantic token", "Value"])
        token_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for name, value in token_rows(key):
            row = token_table.rowCount()
            token_table.insertRow(row)
            token_table.setItem(row, 0, QTableWidgetItem(name))
            token_table.setItem(row, 1, QTableWidgetItem(value))
        token_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        token_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        details_layout.addWidget(token_table, 1)

        contract = QLabel(
            "Typography: "
            f"{TYPOGRAPHY.body}px body / {TYPOGRAPHY.section}px section / {TYPOGRAPHY.title}px title\n"
            f"Spacing: {SPACING.xs}/{SPACING.sm}/{SPACING.md}/{SPACING.lg}/{SPACING.xl}px\n"
            f"Icons: {ICONS.compact}/{ICONS.standard}/{ICONS.prominent}px · {ICONS.style}\n"
            f"Controls: {COMPONENTS.control_compact_height}/{COMPONENTS.control_comfortable_height}px · "
            f"Queue rows {COMPONENTS.queue_row_compact_height}/{COMPONENTS.queue_row_comfortable_height}px"
        )
        contract.setWordWrap(True)
        contract.setTextInteractionFlags(Qt.TextSelectableByMouse)
        details_layout.addWidget(contract)
        root.addWidget(details, 2)
        return page

    def _specimen(self, key: str) -> QFrame:
        specimen = QFrame()
        specimen.setObjectName("conceptSpecimen")
        layout = QVBoxLayout(specimen)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        toolbar = QFrame()
        toolbar.setObjectName("specimenToolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)
        for text in ("New", "Sources"):
            toolbar_layout.addWidget(QPushButton(text))
        toolbar_layout.addStretch()
        preflight = QPushButton("Preflight")
        start = QPushButton("Start")
        start.setObjectName("specimenPrimary")
        toolbar_layout.addWidget(preflight)
        toolbar_layout.addWidget(start)
        layout.addWidget(toolbar)

        provider = QFrame()
        provider.setObjectName("specimenProvider")
        provider_layout = QGridLayout(provider)
        provider_layout.setContentsMargins(10, 10, 10, 10)
        provider_layout.addWidget(self._label("Provider", "specimenMuted"), 0, 0)
        provider_layout.addWidget(self._label("ElevenLabs", "specimenTitle"), 0, 1)
        provider_layout.addWidget(self._label("Voice / Model", "specimenMuted"), 1, 0)
        provider_layout.addWidget(self._label("Danish · eleven_v3", "specimenSecondary"), 1, 1)
        provider_layout.addWidget(self._label("Connected", "specimenSuccess"), 0, 2, 2, 1)
        layout.addWidget(provider)

        queue = QFrame()
        queue.setObjectName("specimenQueue")
        queue_layout = QVBoxLayout(queue)
        queue_layout.setContentsMargins(10, 10, 10, 10)
        queue_title = self._label("Generation queue", "specimenTitle")
        queue_layout.addWidget(queue_title)
        table = QTableWidget(3, 4)
        table.setHorizontalHeaderLabels(["File", "Status", "Language", "Provider"])
        rows = (
            ("intro-01.mp3", "Pending", "da", "ElevenLabs"),
            ("lesson-02.mp3", "Running", "da", "ElevenLabs"),
            ("mixed-03.mp3", "Completed", "en override", "OpenAI"),
        )
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(value))
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        queue_layout.addWidget(table)
        states = QHBoxLayout()
        states.addWidget(self._label("Ready", "specimenSuccess"))
        states.addWidget(self._label("Needs review", "specimenWarning"))
        states.addWidget(self._label("Blocked", "specimenDanger"))
        states.addStretch()
        queue_layout.addLayout(states)
        layout.addWidget(queue, 1)

        specimen.setStyleSheet(concept_preview_stylesheet(key))
        return specimen

    @staticmethod
    def _label(text: str, object_name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        return label
