from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from app.models.api_profile import ApiProfile
from app.models.provider_manifest import ProviderManifest


@dataclass(frozen=True)
class ProviderAccountEditorValues:
    display_name: str
    api_key: str | None
    metadata: dict[str, str]


class ProviderAccountEditorDialog(QDialog):
    """One provider-aware form for creating or editing named accounts."""

    FIELD_LABELS = {
        "region": "Region",
        "endpoint": "Endpoint",
        "project_id": "Project ID",
        "credential_reference": "Credential reference",
        "api_endpoint": "API endpoint hostname",
        "aws_profile": "AWS profile",
    }

    FIELD_HINTS = {
        "region": "Cloud region used by this account.",
        "endpoint": "Optional provider endpoint when supported.",
        "project_id": "Optional project identifier used with Google credentials.",
        "credential_reference": "Optional service-account file reference. Leave blank to use ADC.",
        "api_endpoint": "Optional regional API hostname.",
        "aws_profile": "Optional named AWS profile. Leave blank to use the default credential chain.",
    }

    def __init__(
        self,
        manifest: ProviderManifest,
        *,
        profile: ApiProfile | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.manifest = manifest
        self.profile = profile
        self.metadata_edits: dict[str, QLineEdit] = {}
        self.setWindowTitle("Edit provider account" if profile else "Add provider account")
        self.setMinimumWidth(520)
        self.setObjectName("providerAccountEditorDialog")
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel(self.manifest.display_name)
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        credential_hint = QLabel(self._credential_hint())
        credential_hint.setObjectName("dialogSubtitle")
        credential_hint.setWordWrap(True)
        root.addWidget(credential_hint)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.name_edit = QLineEdit(self.profile.display_name if self.profile else "")
        self.name_edit.setPlaceholderText(f"My {self.manifest.display_name} account")
        form.addRow("Account name", self.name_edit)

        self.secret_edit: QLineEdit | None = None
        if self.manifest.profile_secret_required:
            self.secret_edit = QLineEdit()
            self.secret_edit.setEchoMode(QLineEdit.Password)
            if self.profile and self.profile.has_saved_key:
                self.secret_edit.setPlaceholderText("Saved credential — leave blank to keep it")
            else:
                self.secret_edit.setPlaceholderText("Provider credential / API key")
            form.addRow("Credential", self.secret_edit)

        initial_metadata = dict(self.profile.metadata) if self.profile else {}
        for field in self.manifest.profile_metadata_fields:
            edit = QLineEdit(str(initial_metadata.get(field, "")))
            edit.setPlaceholderText(self.FIELD_HINTS.get(field, "Optional provider setting"))
            self.metadata_edits[field] = edit
            form.addRow(self.FIELD_LABELS.get(field, field.replace("_", " ").title()), edit)

        root.addLayout(form)

        if not self.manifest.profile_secret_required:
            note = QLabel(
                "S-Talking will not store a provider secret for this account. "
                "Credentials are resolved from the provider's external credential chain or reference."
            )
            note.setObjectName("providerAccountExternalCredentialHint")
            note.setWordWrap(True)
            root.addWidget(note)

        self.error_label = QLabel("")
        self.error_label.setObjectName("providerAccountEditorError")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def values(self) -> ProviderAccountEditorValues:
        secret: str | None = None
        if self.secret_edit is not None:
            value = self.secret_edit.text().strip()
            secret = value or None
        metadata = {
            field: edit.text().strip()
            for field, edit in self.metadata_edits.items()
            if edit.text().strip()
        }
        return ProviderAccountEditorValues(
            display_name=self.name_edit.text().strip(),
            api_key=secret,
            metadata=metadata,
        )

    def _validate_and_accept(self) -> None:
        values = self.values()
        if not values.display_name:
            self._show_error("Account name is required.")
            return
        if self.manifest.profile_secret_required and self.profile is None and not values.api_key:
            self._show_error("A provider credential is required for this account.")
            return
        if (
            "region" in self.manifest.profile_metadata_fields
            and "endpoint" in self.manifest.profile_metadata_fields
            and not values.metadata.get("region")
            and not values.metadata.get("endpoint")
        ):
            self._show_error("Provide either a region or an endpoint.")
            return
        self.accept()

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _credential_hint(self) -> str:
        if self.manifest.profile_secret_required:
            return (
                "The credential is stored in S-Talking's secure credential store. "
                "Only safe account metadata is written to the profile file."
            )
        return (
            "This provider uses external credentials. Configure only the safe account "
            "reference fields below; no raw cloud credential is stored in the profile file."
        )
