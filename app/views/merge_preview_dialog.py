from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.controllers.metadata_controller import MetadataController
from app.models.metadata.metadata_structure import AboutXmlMod


class ModListSection(QWidget):
    """A labeled list section in the merge preview."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.header_label = QLabel(f"<b>{title}</b>")
        layout.addWidget(self.header_label)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list_widget.setMaximumHeight(200)
        layout.addWidget(self.list_widget)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

    def add_item(self, text: str) -> None:
        self.list_widget.addItem(text)


class MergePreviewDialog(QDialog):
    """Preview the changes made by merging an external mod list."""

    def __init__(
        self,
        new_mods: list[str],
        already_present: list[str],
        missing_packageids: list[str],
        source_filename: str = "",
        total_imported: int = 0,
        parent: QWidget | None = None,
        metadata_controller: MetadataController | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mergePreviewDialog")
        self.metadata_controller = metadata_controller or MetadataController.instance()
        self._new_mods = new_mods
        self._already_present = already_present
        self._missing_packageids = missing_packageids
        self._setup_ui(source_filename, total_imported)

    @property
    def new_mod_count(self) -> int:
        return len(self._new_mods)

    @property
    def already_present_count(self) -> int:
        return len(self._already_present)

    @property
    def missing_count(self) -> int:
        return len(self._missing_packageids)

    def _setup_ui(self, source_filename: str, total_imported: int) -> None:
        self.setWindowTitle(self.tr("Merge Modlist Preview"))
        self.resize(700, 500)
        outer_layout = QVBoxLayout(self)
        if source_filename:
            outer_layout.addWidget(
                QLabel(self.tr("Source: {filename}").format(filename=source_filename))
            )
        if total_imported > 0:
            outer_layout.addWidget(
                QLabel(
                    self.tr("Mods in imported list: {count}").format(
                        count=total_imported
                    )
                )
            )

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_content = QWidget()
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.new_section = ModListSection(
            self.tr("✚ New mods to add ({count})").format(count=self.new_mod_count)
        )
        self._populate_uuid_section(self.new_section, self._new_mods)
        content_layout.addWidget(self.new_section)
        self.already_present_section = ModListSection(
            self.tr("✓ Already active ({count})").format(
                count=self.already_present_count
            )
        )
        self._populate_uuid_section(self.already_present_section, self._already_present)
        content_layout.addWidget(self.already_present_section)
        self.missing_section = ModListSection(
            self.tr("⚠ Missing / not installed ({count})").format(
                count=self.missing_count
            )
        )
        for package_id in self._missing_packageids:
            self.missing_section.add_item(package_id)
        self.missing_section.setVisible(bool(self._missing_packageids))
        content_layout.addWidget(self.missing_section)
        content_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        outer_layout.addWidget(scroll_area)

        footer = QLabel(
            self.tr("After merging, the active list will be automatically sorted.")
        )
        footer.setWordWrap(True)
        outer_layout.addWidget(footer)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_button = QPushButton(self.tr("Cancel"))
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        self.merge_button = QPushButton(self.tr("Merge && Sort"))
        self.merge_button.setDefault(True)
        self.merge_button.clicked.connect(self.accept)
        self.merge_button.setEnabled(self.new_mod_count > 0)
        if self.new_mod_count == 0:
            self.merge_button.setToolTip(self.tr("No new mods to add."))
        buttons.addWidget(self.merge_button)
        outer_layout.addLayout(buttons)

    def _populate_uuid_section(self, section: ModListSection, uuids: list[str]) -> None:
        for uuid in uuids:
            mod = self.metadata_controller.get_mod(uuid)
            name = mod.name if mod is not None and mod.name else self.tr("Unknown")
            package_id = str(mod.package_id) if isinstance(mod, AboutXmlMod) else "???"
            section.add_item(f"{name}  ({package_id})")
