"""Settings page: business profile, appearance, VAT and backup/restore.

Blueprint 12. Changing the VAT rate only affects future sales; stored invoices
keep the amounts and the rate they were priced with. A restore takes an
automatic safety backup first and then asks for a restart so no stale database
connection stays in memory.
"""

from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.config import FONT_SIZES, THEMES
from core.exceptions import VeyraError
from core.logger import get_logger, log_unexpected
from core.money import format_rate
from core.paths import BACKUP_DIR, DATA_HOME, DATABASE_PATH
from services import backup_service, image_service, settings_service, sync_service
from ui import theme as theme_module
from ui.dialogs.base import ConfirmDialog, MessageDialog
from ui.widgets.banner import Banner
from ui.widgets.busy import BusyOverlay
from ui.widgets.card import Card
from ui.widgets.fields import Combo, Field, PercentSpin, SearchInput, TextArea
from ui.widgets.images import Thumbnail
from ui.widgets.table import Column, DataTable

logger = get_logger("ui.settings")

IMAGE_FILTER = "Images (*.jpg *.jpeg *.png *.webp *.bmp)"


class SettingsPage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window_ref = window
        self.settings = settings_service.get_settings()
        self._logo = self.settings.logo_image
        self._profile_image = self.settings.profile_image

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        self.scroll_area = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        self.banner = Banner(host)
        layout.addWidget(self.banner)

        layout.addWidget(self._business_card())
        layout.addWidget(self._appearance_card())
        layout.addWidget(self._tax_card())
        layout.addWidget(self._cloud_card())
        layout.addWidget(self._data_card())
        layout.addStretch(1)

        scroll.setWidget(host)
        outer.addWidget(scroll)
        self.busy = BusyOverlay(self)

    # -------------------------------------------------------- business card

    def _business_card(self) -> Card:
        card = Card("Business Profile", "Shown on the dashboard, reports and receipts.")

        self.business_name = SearchInput(self.settings.business_name)
        self.business_name.setPlaceholderText("e.g. Njeri General Stores")
        self.owner_name = SearchInput(self.settings.owner_name or "")
        self.owner_name.setPlaceholderText("Owner or proprietor")
        self.phone = SearchInput(self.settings.phone or "")
        self.phone.setPlaceholderText("e.g. 0712 345 678")
        self.email = SearchInput(self.settings.email or "")
        self.email.setPlaceholderText("Optional")
        self.address = TextArea(self.settings.address or "", rows=2)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(Field("Business Name", self.business_name, required=True))
        row.addWidget(Field("Owner Name", self.owner_name))
        card.add_layout(row)

        contact = QHBoxLayout()
        contact.setSpacing(12)
        contact.addWidget(Field("Phone", self.phone))
        contact.addWidget(Field("Email", self.email))
        card.add_layout(contact)
        card.add_widget(Field("Address", self.address))

        images = QHBoxLayout()
        images.setSpacing(16)
        images.addWidget(self._image_picker("Business Logo", "logo", kind="logos"))
        images.addWidget(self._image_picker("Profile Image", "profile", kind="profile"))
        images.addStretch(1)
        card.add_layout(images)

        save = QPushButton("Save Profile")
        save.setProperty("variant", "primary")
        save.clicked.connect(self.save_profile)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(save)
        card.add_layout(actions)
        return card

    def _image_picker(self, title: str, attribute: str, *, kind: str) -> QWidget:
        box = QFrame()
        box.setObjectName("Card")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)

        label = QLabel(title)
        label.setObjectName("FieldLabel")
        preview = Thumbnail(64)
        stored = self._logo if attribute == "logo" else self._profile_image
        preview.set_image(stored, title)
        layout.addWidget(label)
        layout.addWidget(preview)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        choose = QPushButton("Choose")
        choose.setProperty("variant", "quiet")
        remove = QPushButton("Remove")
        remove.setProperty("variant", "quiet")
        buttons.addWidget(choose)
        buttons.addWidget(remove)
        layout.addLayout(buttons)

        def pick() -> None:
            path, _ = QFileDialog.getOpenFileName(self, f"Choose {title.lower()}", "", IMAGE_FILTER)
            if not path:
                return
            try:
                stored_value = image_service.import_image(path, kind=kind)
            except VeyraError as error:
                self.banner.show_message(error.message, "danger")
                return
            if attribute == "logo":
                self._logo = stored_value
            else:
                self._profile_image = stored_value
            preview.set_image(stored_value, title)
            self.banner.show_message(
                f"{title} ready. Save the profile to keep it.", "info"
            )

        def clear() -> None:
            if attribute == "logo":
                self._logo = ""
            else:
                self._profile_image = ""
            preview.set_image(None, title)
            self.banner.show_message(
                f"{title} will be removed when you save the profile.", "info"
            )

        choose.clicked.connect(pick)
        remove.clicked.connect(clear)
        return box

    def save_profile(self) -> None:
        self.banner.clear()
        self.busy.start("Saving profile...")
        try:
            self.settings = settings_service.update_business_profile(
                business_name=self.business_name.text(),
                owner_name=self.owner_name.text(),
                phone=self.phone.text(),
                email=self.email.text(),
                address=self.address.toPlainText(),
                logo_image=self._logo,
                profile_image=self._profile_image,
            )
        except VeyraError as error:
            self.busy.stop()
            self.banner.show_message(error.message, "danger")
            return
        except Exception as exc:  # noqa: BLE001 - never show a traceback
            self.busy.stop()
            reference = log_unexpected(logger, "save business profile", exc)
            self.banner.show_message(
                f"The profile could not be saved. Reference {reference}.", "danger"
            )
            return
        self.busy.stop()
        self._logo = self.settings.logo_image
        self._profile_image = self.settings.profile_image
        self.window_ref.reload_settings()
        self.window_ref.notify("Business profile saved.")

    # ------------------------------------------------------ appearance card

    def _appearance_card(self) -> Card:
        card = Card("Appearance", "Previewed instantly; Save Appearance keeps it for next time.")

        self.theme_group = QButtonGroup(self)
        theme_row = QHBoxLayout()
        theme_row.setSpacing(14)
        for name in THEMES:
            button = QRadioButton(name)
            button.setChecked(name.lower() == self.settings.theme.lower())
            self.theme_group.addButton(button)
            theme_row.addWidget(button)
        theme_row.addStretch(1)
        card.add_widget(Field("Theme", self._wrap(theme_row)))

        self.font_size = Combo(list(FONT_SIZES))
        self.font_size.setCurrentText(self.settings.font_size)
        self.font_size.setFixedWidth(180)
        card.add_widget(Field("Font Size", self.font_size))

        self.theme_group.buttonClicked.connect(lambda _button: self._preview_appearance())
        self.font_size.currentTextChanged.connect(lambda _text: self._preview_appearance())

        save = QPushButton("Save Appearance")
        save.setProperty("variant", "primary")
        save.clicked.connect(self.save_appearance)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(save)
        card.add_layout(actions)
        return card

    def _preview_appearance(self) -> None:
        """Apply the picked theme/size right away so the choice is visible."""
        from PySide6.QtWidgets import QApplication

        theme_module.apply_theme(
            QApplication.instance(), self._selected_theme(), self.font_size.currentText()
        )

    def _selected_theme(self) -> str:
        button = self.theme_group.checkedButton()
        return button.text() if button else THEMES[0]

    @staticmethod
    def _wrap(row: QHBoxLayout) -> QWidget:
        host = QWidget()
        host.setLayout(row)
        return host

    def save_appearance(self) -> None:
        self.banner.clear()
        try:
            self.settings = settings_service.update_appearance(
                theme=self._selected_theme(), font_size=self.font_size.currentText()
            )
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            return
        except Exception as exc:  # noqa: BLE001
            reference = log_unexpected(logger, "save appearance", exc)
            self.banner.show_message(
                f"Appearance could not be saved. Reference {reference}.", "danger"
            )
            return
        self.window_ref.reload_settings()
        self.window_ref.notify(f"Appearance set to {self.settings.theme} / "
                               f"{self.settings.font_size}.")

    # ------------------------------------------------------------- tax card

    def _tax_card(self) -> Card:
        card = Card(
            "Tax Settings",
            "VAT applies to future sales only. Recorded invoices keep the rate "
            "and amounts they were sold with.",
        )

        self.vat_enabled = QCheckBox("VAT enabled")
        self.vat_enabled.setChecked(self.settings.vat_enabled)
        self.vat_rate = PercentSpin()
        self.vat_rate.set_decimal(self.settings.vat_rate)
        self.vat_rate.setFixedWidth(160)

        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(self.vat_enabled)
        row.addWidget(Field("VAT Rate", self.vat_rate))
        row.addStretch(1)
        card.add_layout(row)

        self.tax_hint = QLabel("")
        self.tax_hint.setObjectName("FieldHint")
        card.add_widget(self.tax_hint)

        save = QPushButton("Save Tax Settings")
        save.setProperty("variant", "primary")
        save.clicked.connect(self.save_tax)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(save)
        card.add_layout(actions)
        self._refresh_tax_hint()
        return card

    def _refresh_tax_hint(self) -> None:
        if self.settings.vat_enabled:
            self.tax_hint.setText(
                f"Charging VAT at {format_rate(self.settings.vat_rate)}% on every "
                "VAT-applicable product line."
            )
        else:
            self.tax_hint.setText(
                "VAT is switched off, so totals equal the subtotal less any discount."
            )

    def save_tax(self) -> None:
        self.banner.clear()
        try:
            self.settings = settings_service.update_tax_settings(
                vat_enabled=self.vat_enabled.isChecked(),
                vat_rate=self.vat_rate.decimal_value(),
            )
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            return
        except Exception as exc:  # noqa: BLE001
            reference = log_unexpected(logger, "save tax settings", exc)
            self.banner.show_message(
                f"Tax settings could not be saved. Reference {reference}.", "danger"
            )
            return
        self._refresh_tax_hint()
        self.window_ref.notify(self.settings.vat_label + " saved for future sales.")

    # ---------------------------------------------------------- cloud card

    def _cloud_card(self) -> Card:
        card = Card(
            "Cloud Sync",
            "Keeps a copy of the catalogue, sales ledger and profile in your "
            "Supabase project so a new computer starts with yesterday's data.",
        )

        self.cloud_status = QLabel("")
        self.cloud_status.setObjectName("FieldHint")
        self.cloud_status.setWordWrap(True)
        card.add_widget(self.cloud_status)

        self.sync_id = SearchInput(sync_service.shop_id())
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(
            Field("Sync ID - enter it on a new computer to restore", self.sync_id), 1
        )
        apply_id = QPushButton("Use This ID")
        apply_id.setProperty("variant", "quiet")
        apply_id.clicked.connect(self.apply_sync_id)
        row.addWidget(apply_id)
        card.add_layout(row)

        self.auto_sync = QCheckBox("Sync automatically after changes")
        self.auto_sync.setChecked(sync_service.auto_sync_enabled())
        self.auto_sync.toggled.connect(sync_service.set_auto_sync)
        card.add_widget(self.auto_sync)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        check = QPushButton("Check Connection")
        check.clicked.connect(self.check_connection)
        push = QPushButton("Sync Now")
        push.setProperty("variant", "primary")
        push.clicked.connect(self.sync_now)
        pull = QPushButton("Restore From Cloud...")
        pull.setProperty("variant", "quiet")
        pull.clicked.connect(self.restore_from_cloud)
        buttons.addWidget(check)
        buttons.addWidget(push)
        buttons.addWidget(pull)
        buttons.addStretch(1)
        card.add_layout(buttons)

        hint = QLabel(
            "First time? Open the Supabase SQL editor once and run cloud/schema.sql."
        )
        hint.setObjectName("FieldHint")
        card.add_widget(hint)
        self._refresh_cloud()
        return card

    def _refresh_cloud(self) -> None:
        state = sync_service.load_state()
        when = f" Last attempt: {state.last_at}." if state.last_at else ""
        self.cloud_status.setText(f"{state.message}{when}")
        if not self.sync_id.hasFocus():
            self.sync_id.setText(sync_service.shop_id())

    def apply_sync_id(self) -> None:
        self.banner.clear()
        try:
            sync_service.set_shop_id(self.sync_id.text())
        except VeyraError as error:
            self.banner.show_message(error.message, "danger")
            return
        self._refresh_cloud()
        self.window_ref.notify("Sync ID updated. Check the connection before restoring.")

    def check_connection(self) -> None:
        self.window_ref.run_sync(
            sync_service.probe, "probe", on_done=lambda _result: self._refresh_cloud()
        )

    def sync_now(self) -> None:
        self.window_ref.run_sync(
            sync_service.push, "push", on_done=lambda _result: self._refresh_cloud()
        )

    def restore_from_cloud(self) -> None:
        def done(result) -> None:
            self._refresh_cloud()
            if result.ok or "already holds" not in result.message:
                return
            if not ConfirmDialog.ask(
                self,
                "Replace the data on this computer?",
                "Everything recorded here will be replaced by the cloud copy. VEYRA "
                "takes a safety backup of the current data first.",
                confirm_label="Replace And Restore",
                variant="danger",
            ):
                return
            try:
                backup_service.create_backup()
            except VeyraError as error:
                self.banner.show_message(error.message, "danger")
                return
            self.window_ref.run_sync(
                lambda: sync_service.pull_and_restore(allow_overwrite=True),
                "pull",
                on_done=self._after_restore,
            )

        self.window_ref.run_sync(
            lambda: sync_service.pull_and_restore(allow_overwrite=False),
            "pull",
            on_done=done,
        )

    def _after_restore(self, result) -> None:
        self._refresh_cloud()
        if result.ok:
            self.window_ref.reload_settings()
            self.refresh()

    # ------------------------------------------------------------ data card

    def _data_card(self) -> Card:
        card = Card(
            "Backup and Restore",
            "Backups are timestamped copies of the SQLite database. Restoring replaces "
            "live data, so VEYRA takes a safety backup first.",
        )

        location = QLabel(f"Database: {DATABASE_PATH}\nBackups: {BACKUP_DIR}")
        location.setObjectName("FieldHint")
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card.add_widget(location)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        backup = QPushButton("Backup Database")
        backup.setProperty("variant", "primary")
        backup.clicked.connect(self.create_backup)
        restore = QPushButton("Restore From File...")
        restore.setProperty("variant", "danger")
        restore.clicked.connect(self.restore_from_file)
        open_folder = QPushButton("Open Backups Folder")
        open_folder.setProperty("variant", "quiet")
        open_folder.clicked.connect(self._open_backup_folder)
        buttons.addWidget(backup)
        buttons.addWidget(restore)
        buttons.addWidget(open_folder)
        buttons.addStretch(1)
        card.add_layout(buttons)

        self.backups = DataTable([
            Column("Created", "left", 170),
            Column("Size", "right", 110),
            Column("File", stretch=True),
            Column("", "center", 110),
        ])
        self.backups.set_empty_state(
            "No backups yet. Take one before making big changes.",
            title="No backups found",
        )
        self.backups.setMaximumHeight(220)
        card.add_widget(self.backups)
        self._refresh_backups()
        return card

    def _refresh_backups(self) -> None:
        try:
            entries = backup_service.list_backups()
        except Exception as exc:  # noqa: BLE001
            reference = log_unexpected(logger, "list backups", exc)
            self.banner.show_message(
                f"Backups could not be listed. Reference {reference}.", "danger"
            )
            return
        self.backups.set_rows([
            [
                entry.created_at.strftime("%d %b %Y %H:%M"),
                entry.size_label,
                entry.path.name,
                self._restore_button(entry),
            ]
            for entry in entries
        ])

    def _restore_button(self, entry) -> QPushButton:
        button = QPushButton("Restore")
        button.setProperty("variant", "quiet")
        button.clicked.connect(lambda _checked=False, path=entry.path: self.restore(path))
        return button

    def create_backup(self) -> None:
        self.banner.clear()
        self.busy.start("Backing up...")
        try:
            info = backup_service.create_backup()
        except VeyraError as error:
            self.busy.stop()
            self.banner.show_message(error.message, "danger")
            return
        except Exception as exc:  # noqa: BLE001
            self.busy.stop()
            reference = log_unexpected(logger, "create backup", exc)
            self.banner.show_message(
                f"The backup could not be created. Reference {reference}.", "danger"
            )
            return
        self.busy.stop()
        self._refresh_backups()
        self.window_ref.notify(f"Backup created: {info.name} ({info.size_label}).")

    def restore_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a backup", str(BACKUP_DIR), "VEYRA backups (*.db)"
        )
        if path:
            self.restore(path)

    def restore(self, path) -> None:
        if not ConfirmDialog.ask(
            self,
            "Restore this backup?",
            "Every product, sale and stock movement recorded since this backup was "
            "taken will be replaced. VEYRA saves a safety copy of the current "
            "database first.",
            confirm_label="Restore",
            variant="danger",
            detail=f"Source: {path}",
        ):
            return
        self.busy.start("Restoring database...")
        try:
            safety_net, _destination = backup_service.restore_backup(path)
        except VeyraError as error:
            self.busy.stop()
            self.banner.show_message(error.message, "danger")
            return
        except Exception as exc:  # noqa: BLE001
            self.busy.stop()
            reference = log_unexpected(logger, "restore backup", exc)
            self.banner.show_message(
                "The restore failed and nothing was replaced. "
                f"Reference {reference}.",
                "danger",
            )
            return
        self.busy.stop()
        self.refresh()
        note = (
            " A safety copy of the previous data was saved as "
            f"{safety_net.name}." if safety_net else ""
        )
        MessageDialog.show_message(
            self,
            "Database restored",
            "VEYRA is now running on the restored data." + note,
            kind="success",
        )
        if ConfirmDialog.ask(
            self,
            "Restart VEYRA?",
            "Restarting clears every cached connection and view. This is the safest "
            "way to continue after a restore.",
            confirm_label="Restart Now",
        ):
            self._restart()

    def _restart(self) -> None:
        from PySide6.QtWidgets import QApplication

        try:
            subprocess.Popen([sys.executable, *sys.argv], cwd=str(DATA_HOME))
        except OSError as exc:
            logger.error("Could not relaunch VEYRA: %s", exc)
            MessageDialog.show_message(
                self,
                "Restart manually",
                "VEYRA could not relaunch itself. Close the window and start the "
                "application again.",
                kind="warning",
            )
            return
        QApplication.instance().quit()

    @staticmethod
    def _open_backup_folder() -> None:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["explorer", str(BACKUP_DIR)])
        except OSError as exc:  # pragma: no cover - non-Windows fallback
            logger.warning("Could not open the backups folder: %s", exc)

    # ------------------------------------------------------- shell callbacks

    def refresh(self) -> None:
        self.settings = settings_service.get_settings()
        self._logo = self.settings.logo_image
        self._profile_image = self.settings.profile_image
        self.business_name.setText(self.settings.business_name)
        self.owner_name.setText(self.settings.owner_name or "")
        self.phone.setText(self.settings.phone or "")
        self.email.setText(self.settings.email or "")
        self.address.setPlainText(self.settings.address or "")
        self.vat_enabled.setChecked(self.settings.vat_enabled)
        self.vat_rate.set_decimal(self.settings.vat_rate)
        self.font_size.setCurrentText(self.settings.font_size)
        for button in self.theme_group.buttons():
            button.setChecked(button.text().lower() == self.settings.theme.lower())
        self._refresh_tax_hint()
        self._refresh_backups()
        self._refresh_cloud()
        # Returning to the page drops any unsaved preview and shows what is stored.
        from PySide6.QtWidgets import QApplication

        theme_module.apply_theme(
            QApplication.instance(), self.settings.theme, self.settings.font_size
        )
