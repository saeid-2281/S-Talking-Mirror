from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSettings, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QApplication,
    QScrollArea,
    QSlider,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import icon
from app.models.domain import AppSettings
from app.models.preview import PreviewRecord
from app.gui.widgets.audio_player import AudioPlayerWidget
from app.services.audio_player_service import AudioPlayerService
from app.services.voice_service import AccountUsage, VoiceCatalog, VoiceItem, VoiceModelItem, VoiceService


class _CatalogWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service: VoiceService, settings: AppSettings, *, force: bool = True) -> None:
        super().__init__()
        self.service = service
        self.settings = settings
        self.force = force

    def run(self) -> None:
        try:
            self.finished.emit(self.service.refresh_catalog(self.settings, force=self.force))
        except Exception as exc:
            self.failed.emit(str(exc))


class _PreviewWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, service: VoiceService, item: VoiceItem, text: str, settings: AppSettings) -> None:
        super().__init__()
        self.service = service
        self.item = item
        self.text = text
        self.settings = settings

    def run(self) -> None:
        try:
            self.finished.emit(self.service.preview(self.item, self.text, self.settings))
        except Exception as exc:
            self.failed.emit(str(exc))


@dataclass(frozen=True)
class _FilterState:
    query: str
    favorites_only: bool
    language: str | None
    category: str | None
    accent: str | None
    gender: str | None
    age: str | None
    sort_mode: str


class VoiceBrowserDialog(QDialog):
    voice_selected = Signal(str, str)
    model_selected = Signal(str)
    settings_updated = Signal(object)
    catalog_refreshed = Signal(object)

    def __init__(
        self,
        *,
        service: VoiceService,
        settings_provider: Callable[[], AppSettings],
        desktop_service: object | None = None,
        audio_player_service: AudioPlayerService | None = None,
        open_account_manager: Callable[[], None] | None = None,
        open_dictionary_manager: Callable[[], None] | None = None,
        dictionary_summary_provider: Callable[[], str] | None = None,
        profile_name_provider: Callable[[str], str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.settings_provider = settings_provider
        self.desktop_service = desktop_service
        self.audio_player_service = audio_player_service or AudioPlayerService()
        self.open_account_manager = open_account_manager
        self.open_dictionary_manager = open_dictionary_manager
        self.dictionary_summary_provider = dictionary_summary_provider
        self.profile_name_provider = profile_name_provider
        self.catalog: VoiceCatalog | None = None
        self.items: list[VoiceItem] = []
        self.models: list[VoiceModelItem] = []
        self.saved_previews: list[PreviewRecord] = []
        self._threads: list[QThread] = []
        self._preview_thread: QThread | None = None
        self.setWindowTitle("Voice Browser")
        self.setModal(False)
        self._build()
        self.restore_geometry()
        self._load_cached()
        self._preview_text_changed()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        self.setObjectName("voiceBrowserDialog")

        context_card = QFrame()
        context_card.setObjectName("voiceContextCard")
        top = QHBoxLayout(context_card)
        top.setContentsMargins(12, 10, 12, 10)
        top.setSpacing(10)
        self.provider_label = QLabel("Provider: —")
        self.profile_label = QLabel("Profile: —")
        self.dictionary_label = QLabel("Dictionary: —")
        self.dictionary_enabled = QCheckBox("Enable dictionary")
        self.dictionary_enabled.setChecked(bool(self.settings_provider().pronunciation_dictionary_locators))
        self.dictionary_enabled.toggled.connect(lambda _checked: self.settings_updated.emit(self.preview_settings()))
        self.accounts_button = QToolButton()
        self.accounts_button.setIcon(icon("settings"))
        self.accounts_button.setToolTip("Provider accounts")
        self.accounts_button.clicked.connect(lambda: self.open_account_manager() if self.open_account_manager else None)
        self.dictionaries_button = QToolButton()
        self.dictionaries_button.setIcon(icon("settings"))
        self.dictionaries_button.setToolTip("Pronunciation dictionaries")
        self.dictionaries_button.clicked.connect(lambda: self.open_dictionary_manager() if self.open_dictionary_manager else None)
        self.account_label = QLabel("Account: not loaded")
        self.account_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.refresh_button = QPushButton("Refresh catalog")
        self.refresh_button.setObjectName("primaryQuietButton")
        self.refresh_button.clicked.connect(self.refresh_catalog)
        top.addWidget(self.provider_label)
        top.addSpacing(18)
        top.addWidget(self.profile_label)
        top.addSpacing(12)
        top.addWidget(self.dictionary_label)
        top.addWidget(self.dictionary_enabled)
        top.addWidget(self.accounts_button)
        top.addWidget(self.dictionaries_button)
        top.addWidget(self.account_label, 1)
        top.addWidget(self.refresh_button)
        root.addWidget(context_card)

        filters = QFrame()
        filters.setObjectName("voiceFilterCard")
        form = QFormLayout(filters)
        form.setContentsMargins(12, 10, 12, 10)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search name, voice ID, description, language, accent…")
        self.favorites = QCheckBox("Favorites only")
        self.favorites.setVisible(False)
        self.sort = QComboBox()
        self.sort.addItem("Provider order", "provider_order")
        self.sort.addItem("Name A-Z", "name")
        self.sort.addItem("Language", "language")
        self.sort.addItem("Recently used", "recent")
        self.language = QComboBox()
        self.category = QComboBox()
        self.accent = QComboBox()
        self.gender = QComboBox()
        self.age = QComboBox()
        self.model = QComboBox()
        self.model.setToolTip("The selected model will be applied together with the voice.")

        filter_row = QWidget()
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        for label, combo in (
            ("Language", self.language),
            ("Category", self.category),
            ("Accent", self.accent),
            ("Gender", self.gender),
            ("Age", self.age),
        ):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            column.addWidget(combo)
            filter_layout.addLayout(column)
        filter_layout.addWidget(self.favorites)
        filter_layout.addWidget(QLabel("Sort"))
        filter_layout.addWidget(self.sort)

        form.addRow("Search", self.search)
        form.addRow(filter_row)
        form.addRow("TTS model", self.model)
        root.addWidget(filters)

        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "All voices")
        self.tabs.addTab(QWidget(), "Favorites")
        self.tabs.addTab(QWidget(), "Recent")
        root.addWidget(self.tabs)

        splitter = QSplitter(Qt.Horizontal)
        self.splitter = splitter
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Favorite", "Voice Name", "Language", "Accent", "Gender", "Age", "Category"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(lambda *_: self.apply_selection())
        splitter.addWidget(self.table)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.details_scroll = scroll
        details = QWidget()
        details_layout = QVBoxLayout(details)
        self.title = QLabel("Select a voice")
        self.title.setObjectName("voiceDetailsTitle")
        self.meta = QLabel("")
        self.meta.setWordWrap(True)
        self.provider_id = QLabel("")
        self.provider_id.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.description = QLabel("Voice metadata and compatibility will appear here.")
        self.description.setWordWrap(True)
        self.compatibility = QLabel("")
        self.compatibility.setWordWrap(True)
        self.copy_id_button = QPushButton("Copy ID")
        self.copy_id_button.setIcon(icon("copy"))
        self.copy_id_button.clicked.connect(self.copy_selected_voice_id)
        self.copy_name_button = QPushButton("Copy Name")
        self.copy_name_button.setIcon(icon("copy"))
        self.copy_name_button.clicked.connect(self.copy_selected_voice_name)
        self.favorite_button = QPushButton("☆")
        self.favorite_button.setObjectName("favoriteButton")
        self.favorite_button.setToolTip("Add to favorites")
        self.favorite_button.setMinimumWidth(36)
        self.favorite_button.clicked.connect(self.toggle_favorite)
        self.preview_text = QPlainTextEdit()
        self.preview_text.setPlaceholderText("Enter a short preview sentence…")
        self.default_preview_text = "Hej! Dette er en kort prøve af den valgte danske stemme."
        self.preview_text.setPlainText(
            str(QSettings("S Talking", "S Talking").value("voice_preview/text", self.default_preview_text))
        )
        self.preview_text.textChanged.connect(self._preview_text_changed)
        self.preview_text.setMaximumHeight(115)
        self.preview_count = QLabel("0 characters")
        self.reset_preview_text_button = QPushButton("Reset preview text")
        self.reset_preview_text_button.clicked.connect(self.reset_preview_text)
        self.preview_button = QPushButton("Preview")
        self.preview_button.setIcon(icon("play"))
        self.preview_button.setMinimumWidth(128)
        self.preview_button.clicked.connect(self.generate_preview)
        self.cached_preview_button = QPushButton("Reuse cached")
        self.cached_preview_button.setIcon(icon("play"))
        self.cached_preview_button.setToolTip("Play the cached preview for the current text, voice, model, and settings.")
        self.cached_preview_button.setMinimumWidth(110)
        self.cached_preview_button.clicked.connect(self.play_cached_preview)
        self.stop_preview_button = QPushButton("Stop")
        self.stop_preview_button.setIcon(icon("stop"))
        self.stop_preview_button.setMinimumWidth(118)
        self.stop_preview_button.clicked.connect(self.stop_preview_generation)
        self.stop_audio_button = QPushButton("Stop audio")
        self.stop_audio_button.clicked.connect(self.audio_player_service.stop)
        self.stop_audio_button.setMinimumWidth(96)
        self.preview_status = QLabel("")
        self.preview_status.setWordWrap(True)
        self.audio_player = AudioPlayerWidget(self.audio_player_service, open_folder=self._open_folder)
        self.audio_settings = self._build_audio_settings()
        self.audio_settings.setObjectName("voiceAudioSettings")
        preview_actions = QWidget()
        preview_actions_layout = QGridLayout(preview_actions)
        preview_actions_layout.setContentsMargins(0, 0, 0, 0)
        for index, button in enumerate((self.preview_button, self.cached_preview_button, self.stop_preview_button, self.stop_audio_button)):
            preview_actions_layout.addWidget(button, index // 2, index % 2)
        self.saved_preview_table = QTableWidget(0, 6)
        self.saved_preview_table.setHorizontalHeaderLabels(["Text", "Generated", "Model", "Duration", "Size", "Chars"])
        self.saved_preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.saved_preview_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.saved_preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.saved_preview_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.saved_preview_table.horizontalHeader().setStretchLastSection(True)
        self.saved_preview_table.cellDoubleClicked.connect(lambda *_: self.play_selected_saved_preview())
        self.play_saved_button = QPushButton("Play")
        self.play_saved_button.setIcon(icon("play"))
        self.stop_saved_button = QPushButton("Stop")
        self.open_saved_button = QPushButton("Open folder")
        self.copy_saved_button = QPushButton("Copy path")
        self.delete_saved_button = QPushButton("Delete")
        self.regenerate_saved_button = QPushButton("Regenerate")
        self.clear_saved_button = QPushButton("Clear voice")
        self.play_saved_button.clicked.connect(self.play_selected_saved_preview)
        self.stop_saved_button.clicked.connect(self.audio_player_service.stop)
        self.open_saved_button.clicked.connect(self.open_selected_saved_preview_folder)
        self.copy_saved_button.clicked.connect(self.copy_selected_saved_preview_path)
        self.delete_saved_button.clicked.connect(self.delete_selected_saved_preview)
        self.regenerate_saved_button.clicked.connect(self.regenerate_selected_saved_preview)
        self.clear_saved_button.clicked.connect(self.clear_saved_previews_for_voice)
        saved_actions = QWidget()
        saved_actions_layout = QGridLayout(saved_actions)
        saved_actions_layout.setContentsMargins(0, 0, 0, 0)
        for index, button in enumerate((self.play_saved_button, self.stop_saved_button, self.open_saved_button, self.copy_saved_button, self.delete_saved_button, self.regenerate_saved_button)):
            button.setMinimumWidth(84)
            saved_actions_layout.addWidget(button, index // 3, index % 3)
        details_layout.addWidget(self.title)
        details_layout.addWidget(self.meta)
        details_layout.addWidget(self.provider_id)
        voice_actions = QHBoxLayout()
        voice_actions.addWidget(self.copy_name_button)
        voice_actions.addWidget(self.copy_id_button)
        voice_actions.addWidget(self.favorite_button)
        voice_actions.addStretch()
        details_layout.addLayout(voice_actions)
        details_layout.addWidget(self.description)
        details_layout.addWidget(self.compatibility)
        details_layout.addSpacing(8)
        details_layout.addWidget(QLabel("Preview text"))
        details_layout.addWidget(self.preview_text)
        details_layout.addWidget(self.preview_count)
        details_layout.addWidget(self.reset_preview_text_button)
        details_layout.addWidget(self.audio_settings)
        details_layout.addWidget(preview_actions)
        details_layout.addWidget(self.preview_status)
        details_layout.addWidget(self.audio_player)
        details_layout.addWidget(QLabel("Saved previews"))
        details_layout.addWidget(self.saved_preview_table)
        details_layout.addWidget(saved_actions)
        details_layout.addWidget(self.clear_saved_button)
        details_layout.addStretch()
        scroll.setWidget(details)
        splitter.addWidget(scroll)
        self.restore_splitter_state()
        root.addWidget(splitter, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("Use selected voice")
        self.apply_button.clicked.connect(self.apply_selection)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        buttons.addStretch()
        buttons.addWidget(self.apply_button)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)

        self.search.textChanged.connect(self.apply_filters)
        self.model.currentIndexChanged.connect(self._model_changed)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.favorites.toggled.connect(self.apply_filters)
        self.sort.currentTextChanged.connect(self.apply_filters)
        for combo in (self.language, self.category, self.accent, self.gender, self.age):
            combo.currentTextChanged.connect(self.apply_filters)

    def _build_audio_settings(self) -> QGroupBox:
        settings = self.settings_provider()
        group = QGroupBox("Audio settings")
        layout = QFormLayout(group)
        self.source_language = QComboBox()
        for label, code in (
            ("Auto", None),
            ("Danish (da)", "da"),
            ("English (en)", "en"),
            ("German (de)", "de"),
            ("Swedish (sv)", "sv"),
            ("Norwegian (no)", "no"),
            ("Turkish (tr)", "tr"),
            ("Persian (fa)", "fa"),
        ):
            self.source_language.addItem(label, code)
        index = self.source_language.findData(settings.language_code)
        self.source_language.setCurrentIndex(index if index >= 0 else 0)
        self.setting_sliders: dict[str, tuple[QSlider, QLabel]] = {}
        for key, label, value, hint in (
            ("stability", "Stability", settings.stability, "Creative ←→ Consistent"),
            ("similarity_boost", "Similarity", settings.similarity_boost, "Flexible ←→ Voice match"),
            ("style", "Style", settings.style, "Neutral ←→ Expressive"),
            ("speed", "Speed", (settings.speed - 0.7) / 0.5, "Slow ←→ Fast"),
        ):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(max(0, min(100, int(value * 100))))
            value_label = QLabel()
            slider.setToolTip(hint)
            row_layout.addWidget(slider, 1)
            row_layout.addWidget(value_label)
            self.setting_sliders[key] = (slider, value_label)
            layout.addRow(label, row)
            slider.valueChanged.connect(self._audio_settings_changed)
        self.speaker_boost = QCheckBox("Speaker boost")
        self.speaker_boost.setChecked(settings.use_speaker_boost)
        self.speaker_boost.toggled.connect(self._audio_settings_changed)
        self.source_language.currentIndexChanged.connect(self._audio_settings_changed)
        self.restore_voice_defaults_button = QPushButton("Restore voice defaults")
        self.restore_voice_defaults_button.clicked.connect(self.restore_voice_defaults)
        layout.addRow("Source language", self.source_language)
        layout.addRow("", self.speaker_boost)
        layout.addRow("", self.restore_voice_defaults_button)
        self._update_audio_setting_labels()
        return group

    def _audio_settings_changed(self) -> None:
        self._update_audio_setting_labels()
        self.update_cached_preview_button()
        self.settings_updated.emit(self.preview_settings())

    def _update_audio_setting_labels(self) -> None:
        for key, (slider, label) in self.setting_sliders.items():
            if key == "speed":
                label.setText(f"{0.7 + (slider.value() / 100) * 0.5:.2f}×")
            else:
                label.setText(f"{slider.value() / 100:.2f}")

    def restore_voice_defaults(self) -> None:
        self.setting_sliders["stability"][0].setValue(45)
        self.setting_sliders["similarity_boost"][0].setValue(75)
        self.setting_sliders["style"][0].setValue(20)
        self.setting_sliders["speed"][0].setValue(60)
        index = self.source_language.findData("da")
        self.source_language.setCurrentIndex(index if index >= 0 else 0)
        self.speaker_boost.setChecked(True)
        self._audio_settings_changed()

    def preview_settings(self) -> AppSettings:
        base = self.settings_provider()
        return base.model_copy(
            update={
                "model_id": self.model.currentData() or base.model_id,
                "language_code": self.source_language.currentData(),
                "stability": self.setting_sliders["stability"][0].value() / 100,
                "similarity_boost": self.setting_sliders["similarity_boost"][0].value() / 100,
                "style": self.setting_sliders["style"][0].value() / 100,
                "speed": 0.7 + (self.setting_sliders["speed"][0].value() / 100) * 0.5,
                "use_speaker_boost": self.speaker_boost.isChecked(),
                "pronunciation_dictionary_locators": base.pronunciation_dictionary_locators if self.dictionary_enabled.isChecked() else [],
            }
        )

    def _tab_changed(self) -> None:
        index = self.tabs.currentIndex()
        self.favorites.blockSignals(True)
        self.favorites.setChecked(index == 1)
        self.favorites.blockSignals(False)
        if index == 2:
            recent_index = self.sort.findData("recent")
            if recent_index >= 0:
                self.sort.blockSignals(True)
                self.sort.setCurrentIndex(recent_index)
                self.sort.blockSignals(False)
        QSettings("S Talking", "S Talking").setValue("voice_browser/tab", index)
        self.apply_filters()

    def restore_splitter_state(self) -> None:
        settings = QSettings("S Talking", "S Talking")
        tab = settings.value("voice_browser/tab", 0, type=int)
        self.tabs.setCurrentIndex(max(0, min(self.tabs.count() - 1, tab)))
        sizes = settings.value("voice_browser/splitter_sizes")
        if isinstance(sizes, list) and len(sizes) >= 2:
            left = max(420, min(820, int(sizes[0])))
            right = max(320, min(560, int(sizes[1])))
            self.splitter.setSizes([left, right])
        else:
            self.splitter.setSizes([720, 420])

    def save_splitter_state(self) -> None:
        QSettings("S Talking", "S Talking").setValue("voice_browser/splitter_sizes", self.splitter.sizes())

    def restore_geometry(self) -> None:
        settings = QSettings("S Talking", "S Talking")
        screen = (self.parentWidget() or QApplication.activeWindow() or self).screen() or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else self.geometry()
        saved_size = settings.value("voice_browser/size")
        if saved_size and hasattr(saved_size, "width"):
            width = saved_size.width()
            height = saved_size.height()
        else:
            width = int(available.width() * 0.85)
            height = int(available.height() * 0.85)
        width = max(960, min(width, available.width()))
        height = max(680, min(height, available.height()))
        self.resize(width, height)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def save_geometry(self) -> None:
        QSettings("S Talking", "S Talking").setValue("voice_browser/size", self.size())

    def _load_cached(self) -> None:
        settings = self.settings_provider()
        self.provider_label.setText(f"Provider: {settings.provider}")
        profile_id = str(settings.active_api_profile_id or "")
        profile_name = (
            self.profile_name_provider(profile_id)
            if profile_id and self.profile_name_provider is not None
            else ("Temporary key" if not profile_id else profile_id)
        )
        self.profile_label.setText(f"Profile: {profile_name}")
        self.profile_label.setToolTip(profile_id or "Temporary, unsaved credential")
        summary = self.dictionary_summary_provider() if self.dictionary_summary_provider else (settings.active_pronunciation_dictionary_id or "none")
        self.dictionary_label.setText(f"Dictionary: {summary or 'none'}")
        self.dictionary_enabled.setChecked(bool(settings.pronunciation_dictionary_locators))
        cached = self.service.cached_catalog(settings)
        if cached:
            self.catalog = cached
            self.items = list(cached.voices)
            self.models = list(cached.models)
            self._set_account(cached)
            self._rebuild_models()
        else:
            # A provider-wide repository may contain voices from another API
            # profile. Keep the browser empty until an account-specific catalog
            # is fetched rather than presenting stale cross-account entries.
            self.items = []
            self.models = []
        self._rebuild_filters()
        self.apply_filters()

    def refresh_catalog(self) -> None:
        settings = self.settings_provider()
        self.provider_label.setText(f"Provider: {settings.provider}")
        profile_id = str(settings.active_api_profile_id or "")
        profile_name = (
            self.profile_name_provider(profile_id)
            if profile_id and self.profile_name_provider is not None
            else ("Temporary key" if not profile_id else profile_id)
        )
        self.profile_label.setText(f"Profile: {profile_name}")
        self.profile_label.setToolTip(profile_id or "Temporary, unsaved credential")
        # Clear the visible account-specific data immediately so a slow network
        # refresh never leaves the previous account's models looking current.
        self.catalog = None
        self.items = []
        self.models = []
        self.apply_filters()
        self._rebuild_models()
        self._set_account(None)
        self._busy(True, "Refreshing account-specific voice catalog…")
        thread = QThread(self)
        worker = _CatalogWorker(self.service, settings, force=True)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._catalog_loaded)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda: self._cleanup_thread(thread))
        thread.start()
        self._threads.append(thread)
        self._catalog_worker = worker

    def _catalog_loaded(self, catalog: VoiceCatalog) -> None:
        self.catalog = catalog
        self.items = list(catalog.voices)
        self.models = list(catalog.models)
        self._rebuild_filters()
        self._rebuild_models()
        self._set_account(catalog)
        self.apply_filters()
        self.catalog_refreshed.emit(catalog)
        self._busy(False, f"Loaded {len(self.items)} voice(s).")

    def _set_account(self, catalog: VoiceCatalog | AccountUsage | None) -> None:
        account = catalog.account if isinstance(catalog, VoiceCatalog) else catalog
        if account is None:
            self.account_label.setText("Account: unavailable")
            return
        remaining = account.remaining_characters
        remaining_text = f" • {remaining:,} characters remaining" if remaining is not None else ""
        refreshed = f" • refreshed {catalog.refreshed_at[:19]}" if isinstance(catalog, VoiceCatalog) and catalog.refreshed_at else ""
        counts = f" • {len(catalog.voices)} voices • {sum(1 for model in catalog.models if model.can_do_text_to_speech)} TTS models" if isinstance(catalog, VoiceCatalog) else ""
        self.account_label.setText(
            f"Account: {account.tier or 'unknown'} • {account.status or 'unknown'}{remaining_text}{counts}{refreshed}"
        )
        self.account_label.setToolTip(self.account_label.text())

    def _rebuild_filters(self) -> None:
        values = {
            "language": sorted({item.language for item in self.items if item.language}),
            "category": sorted({item.category for item in self.items if item.category}),
            "accent": sorted({item.accent for item in self.items if item.accent}),
            "gender": sorted({item.gender for item in self.items if item.gender}),
            "age": sorted({item.age for item in self.items if item.age}),
        }
        for name, combo in (
            ("language", self.language),
            ("category", self.category),
            ("accent", self.accent),
            ("gender", self.gender),
            ("age", self.age),
        ):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("All", None)
            for value in values[name]:
                combo.addItem(value, value)
            if current and current != "All":
                index = combo.findText(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def _rebuild_models(self) -> None:
        current = self.settings_provider().model_id
        self.model.blockSignals(True)
        self.model.clear()
        if not self.models:
            self.model.addItem(current or "Default model", current)
        else:
            for model in self.models:
                languages = ", ".join(model.languages[:5])
                suffix = f" — {languages}" if languages else ""
                self.model.addItem(f"{model.name}{suffix}", model.model_id)
            index = self.model.findData(current)
            if index >= 0:
                self.model.setCurrentIndex(index)
            else:
                compatible = next((i for i, model in enumerate(self.models) if model.can_do_text_to_speech), 0)
                self.model.setCurrentIndex(compatible)
                self.preview_status.setText(f"Current model '{current}' was unavailable; using {self.model.currentData()}.")
        self.model.blockSignals(False)

    def apply_filters(self) -> None:
        settings = self.settings_provider()
        state = _FilterState(
            query=self.search.text(),
            favorites_only=self.favorites.isChecked(),
            language=self.language.currentData(),
            category=self.category.currentData(),
            accent=self.accent.currentData(),
            gender=self.gender.currentData(),
            age=self.age.currentData(),
            sort_mode=self.sort.currentData() or "provider_order",
        )
        selected_id = self.selected_item().voice_id if self.selected_item() else None
        self.items = self.service.list(
            provider=settings.provider,
            query=state.query,
            favorites_only=state.favorites_only,
            sort_mode=state.sort_mode,
            language=state.language,
            category=state.category,
            accent=state.accent,
            gender=state.gender,
            age=state.age,
        )
        model_id = self.model.currentData()
        if model_id:
            self.items = [
                item for item in self.items
                if not item.compatible_model_ids or str(model_id) in item.compatible_model_ids
            ]
        source_language = self.source_language.currentData() if hasattr(self, "source_language") else None
        if source_language:
            self.items = sorted(
                self.items,
                key=lambda item: 0 if (item.language or "").lower().startswith(str(source_language).lower()) else 1,
            )
        self._render_table(selected_id=selected_id)

    def _render_table(self, selected_id: str | None = None) -> None:
        self.table.setRowCount(len(self.items))
        for row, item in enumerate(self.items):
            values = [
                "★" if item.is_favorite else "☆",
                item.name,
                item.language or "—",
                item.accent or "—",
                item.gender or "—",
                item.age or "—",
                item.category or "—",
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, item.voice_id)
                cell.setToolTip(str(value))
                self.table.setItem(row, column, cell)
        if self.items:
            row = next((index for index, item in enumerate(self.items) if item.voice_id == selected_id), 0)
            self.table.selectRow(row)
        else:
            self._show_item(None)

    def selected_item(self) -> VoiceItem | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.items):
            return None
        return self.items[row]

    def _selection_changed(self) -> None:
        self.audio_player_service.stop()
        self._last_preview_path = None
        self._show_item(self.selected_item())

    def _show_item(self, item: VoiceItem | None) -> None:
        enabled = item is not None
        self.apply_button.setEnabled(enabled)
        self.preview_button.setEnabled(enabled)
        self.favorite_button.setEnabled(enabled)
        if item is None:
            self.title.setText("No voice selected")
            self.meta.clear()
            self.provider_id.clear()
            self.description.setText("Adjust the search or refresh the catalog.")
            self.compatibility.clear()
            self.render_saved_previews([])
            self.update_cached_preview_button()
            return
        self.title.setText(item.name)
        owner = "Owned" if item.is_owner else "Library/shared" if item.is_owner is False else "Ownership unknown"
        self.meta.setText(
            f"{item.provider} • {item.category or 'uncategorized'} • {item.language or 'language unknown'} • {owner}"
        )
        self.provider_id.setText(f"Provider ID: {item.voice_id}")
        self.description.setText(item.description or item.use_case or "No description supplied by provider.")
        models = ", ".join(item.compatible_model_ids) or "Provider did not publish a compatibility list."
        tiers = ", ".join(item.available_for_tiers) or "Tier availability not published."
        self.compatibility.setText(f"Compatible models: {models}\nAvailable tiers: {tiers}")
        self.favorite_button.setText("★" if item.is_favorite else "☆")
        self.favorite_button.setToolTip("Remove from favorites" if item.is_favorite else "Add to favorites")
        self.render_saved_previews(self.service.saved_previews(item))
        self.update_cached_preview_button()

    def toggle_favorite(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        self.service.set_favorite(item, not item.is_favorite)
        selected_id = item.voice_id
        self.apply_filters()
        for row, candidate in enumerate(self.items):
            if candidate.voice_id == selected_id:
                self.table.selectRow(row)
                break

    def apply_selection(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        self.voice_selected.emit(item.voice_id, item.name)
        model_id = self.model.currentData()
        if model_id:
            self.model_selected.emit(str(model_id))
        self.accept()
    def _model_changed(self) -> None:
        model_id = self.model.currentData()
        if model_id:
            QSettings("S Talking","S Talking").setValue("voice_browser/model_id",str(model_id))
            self.model_selected.emit(str(model_id))
            self.apply_filters()
            self.update_cached_preview_button()

    def copy_selected_voice_id(self) -> None:
        item=self.selected_item()
        if item:
            QApplication.clipboard().setText(item.voice_id)
            self.preview_status.setText("Provider ID copied.")

    def copy_selected_voice_name(self) -> None:
        item=self.selected_item()
        if item:
            QApplication.clipboard().setText(item.name)
            self.preview_status.setText("Voice name copied.")

    def generate_preview(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        text = self.preview_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Preview", "Enter a preview sentence first.")
            return
        settings = self.preview_settings()
        self._busy(True, "Generating preview…")
        thread = QThread(self)
        worker = _PreviewWorker(self.service, item, text, settings)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._preview_ready)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(lambda: self._cleanup_thread(thread))
        thread.start()
        self._threads.append(thread)
        self._preview_thread = thread
        self._preview_worker = worker

    def _preview_ready(self, path: Path) -> None:
        self._busy(False, f"Preview ready: {path.name}")
        self._last_preview_path = path
        self.preview_status.setText(f"Preview file: {path}")
        self.audio_player.load(path)
        self.audio_player_service.play()
        item = self.selected_item()
        if item:
            self.render_saved_previews(self.service.saved_previews(item))
        self.update_cached_preview_button()

    def _operation_failed(self, message: str) -> None:
        self._busy(False, "Operation failed.")
        self.preview_status.setText(message)
        QMessageBox.critical(self, "Voice Browser", message)

    def _busy(self, busy: bool, message: str) -> None:
        self.refresh_button.setEnabled(not busy)
        self.preview_button.setEnabled(not busy and self.selected_item() is not None)
        self.cached_preview_button.setEnabled(not busy and self._cached_preview_path() is not None)
        self.stop_preview_button.setEnabled(busy)
        self.apply_button.setEnabled(not busy and self.selected_item() is not None)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0 if busy else 1)
        if not busy:
            self.progress.setValue(1)
        self.preview_status.setText(message)

    def stop_preview_generation(self) -> None:
        if self._preview_thread is not None and self._preview_thread.isRunning():
            self._preview_thread.requestInterruption()
            self._preview_thread.quit()
        self._busy(False, "Preview generation stopped.")

    def play_cached_preview(self) -> None:
        path = self._cached_preview_path() or getattr(self, "_last_preview_path", None)
        if path is None:
            self.preview_status.setText("No cached preview exists for this voice and text.")
            return
        self.audio_player.load(path)
        self.audio_player_service.play()
        self.preview_status.setText(f"Playing cached preview: {path.name}")

    def render_saved_previews(self, records: list[PreviewRecord]) -> None:
        self.saved_previews = records
        self.saved_preview_table.setRowCount(len(records))
        for row, record in enumerate(records):
            excerpt = record.preview_text.replace("\n", " ")[:80]
            duration = f"{record.duration_seconds:.1f} s" if record.duration_seconds else "—"
            size = f"{record.file_size/1024:.1f} KB" if record.file_size else "—"
            values = [excerpt, record.created_at[:19], record.model_id, duration, size, record.character_count]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(record.preview_text if column == 0 else str(record.file_path))
                self.saved_preview_table.setItem(row, column, item)
        enabled = bool(records)
        for button in (self.play_saved_button, self.open_saved_button, self.copy_saved_button, self.delete_saved_button, self.regenerate_saved_button, self.clear_saved_button):
            button.setEnabled(enabled)

    def selected_saved_preview(self) -> PreviewRecord | None:
        row = self.saved_preview_table.currentRow()
        if 0 <= row < len(self.saved_previews):
            return self.saved_previews[row]
        return self.saved_previews[0] if self.saved_previews else None

    def play_selected_saved_preview(self) -> None:
        record = self.selected_saved_preview()
        if record is None:
            self.preview_status.setText("No saved preview selected.")
            return
        if not record.file_path.exists():
            item = self.selected_item()
            if item:
                self.render_saved_previews(self.service.saved_previews(item))
            self.preview_status.setText("Missing preview removed from the library.")
            return
        self.audio_player.load(record.file_path)
        self.audio_player_service.play()
        self.service.mark_preview_played(record)
        self.preview_status.setText(f"Playing saved preview: {record.file_path.name}")

    def open_selected_saved_preview_folder(self) -> None:
        record = self.selected_saved_preview()
        if record:
            self._open_folder(record.file_path.parent)

    def copy_selected_saved_preview_path(self) -> None:
        record = self.selected_saved_preview()
        if record:
            QApplication.clipboard().setText(str(record.file_path))
            self.preview_status.setText("Preview path copied.")

    def delete_selected_saved_preview(self) -> None:
        record = self.selected_saved_preview()
        if record is None:
            return
        self.service.delete_preview(record)
        item = self.selected_item()
        self.render_saved_previews(self.service.saved_previews(item) if item else [])
        self.preview_status.setText("Preview deleted.")
    def regenerate_selected_saved_preview(self) -> None:
        record=self.selected_saved_preview()
        if record:
            self.preview_text.setPlainText(record.preview_text)
        self.generate_preview()

    def clear_saved_previews_for_voice(self) -> None:
        item = self.selected_item()
        if item is None:
            return
        count = self.service.clear_previews_for_voice(item)
        self.render_saved_previews([])
        self.preview_status.setText(f"Cleared {count} saved preview(s) for this voice.")

    def reset_preview_text(self) -> None:
        self.preview_text.setPlainText(self.default_preview_text)

    def update_cached_preview_button(self) -> None:
        if hasattr(self, "cached_preview_button"):
            self.cached_preview_button.setEnabled(self._cached_preview_path() is not None or bool(getattr(self, "_last_preview_path", None)))

    def _preview_text_changed(self) -> None:
        text = self.preview_text.toPlainText()
        QSettings("S Talking", "S Talking").setValue("voice_preview/text", text)
        self.preview_count.setText(f"{len(text):,} characters")
        self.update_cached_preview_button()

    def _cached_preview_path(self) -> Path | None:
        item = self.selected_item()
        if item is None:
            return None
        settings = self.preview_settings()
        return self.service.cached_preview_path(item, self.preview_text.toPlainText(), settings)

    def _open_folder(self, path: Path) -> None:
        if self.desktop_service and hasattr(self.desktop_service, "open_path"):
            self.desktop_service.open_path(path)

    def _cleanup_thread(self, thread: QThread) -> None:
        if thread in self._threads:
            self._threads.remove(thread)
        thread.deleteLater()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.save_splitter_state()
        self.save_geometry()
        for thread in list(self._threads):
            thread.quit()
            thread.wait(1000)
        self.audio_player_service.stop()
        super().closeEvent(event)
