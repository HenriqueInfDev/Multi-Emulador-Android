"""Card de um celular na grade principal."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from config.settings import phone_number
from emulators.manager import BOOTING, ERROR, MISSING, OFF, ON, RESTARTING, STARTING, STOPPING, PhoneState
from ui import theme
from ui.icons import icon
from utils.system import human_size

ACTIONS = [
    ("start", "play", "Iniciar", "Ligar este celular"),
    ("stop", "power", "Desligar", "Desligar com segurança (os dados ficam salvos)"),
    ("restart", "restart", "Reiniciar", "Reiniciar o Android"),
    ("window", "window", "Janela", "Mostrar a janela do emulador"),
    ("apk", "apk", "Instalar", "Instalar aplicativos (APK)"),
    ("settings", "settings", "Ajustes", "Configurações deste celular"),
    ("files", "folder", "Arquivos", "Arquivos do emulador e transferências"),
    ("backup", "backup", "Backup", "Backups e restauração"),
]


class StatusDot(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(12, 12)
        self._color = theme.GRAY

    def set_color(self, color: str):
        self._color = color
        self.setStyleSheet(f"background:{color}; border-radius:6px;")


class DeviceCard(QFrame):
    action = Signal(str, str)  # (ação, nome do celular)
    selection_changed = Signal()

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.state: PhoneState | None = None
        self.setObjectName("card")
        self.setMinimumWidth(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(8)

        # Cabeçalho
        head = QHBoxLayout()
        head.setSpacing(8)
        self.check = QCheckBox()
        self.check.setToolTip("Selecionar para ações em grupo")
        self.check.toggled.connect(self._on_check)
        self.dot = StatusDot()
        self.lbl_name = QLabel(name)
        self.lbl_name.setObjectName("cardName")
        self.badge = QLabel(f"#{phone_number(name):02d}")
        self.badge.setObjectName("badge")
        head.addWidget(self.check)
        head.addWidget(self.dot)
        head.addWidget(self.lbl_name, 1)
        head.addWidget(self.badge)
        root.addLayout(head)

        self.lbl_status = QLabel("—")
        self.lbl_status.setStyleSheet("font-weight:600;")
        root.addWidget(self.lbl_status)

        # Informações
        self.info = QGridLayout()
        self.info.setHorizontalSpacing(10)
        self.info.setVerticalSpacing(3)
        self.vals = {}
        rows = [("android", "Android"), ("ram", "RAM"), ("storage", "Armazenamento"),
                ("screen", "Tela"), ("backup", "Último backup")]
        for i, (key, label) in enumerate(rows):
            k = QLabel(label)
            k.setObjectName("infoKey")
            v = QLabel("—")
            v.setObjectName("infoVal")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.info.addWidget(k, i, 0)
            self.info.addWidget(v, i, 1)
            self.vals[key] = v
        self.info.setColumnStretch(1, 1)
        self.info_box = QWidget()
        self.info_box.setLayout(self.info)
        root.addWidget(self.info_box)

        self.lbl_msg = QLabel("")
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setObjectName("muted")
        self.lbl_msg.hide()
        root.addWidget(self.lbl_msg)

        self.progress = QProgressBar()
        self.progress.setObjectName("thin")
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(4)
        self.progress.setVisible(False)
        sp = self.progress.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.progress.setSizePolicy(sp)
        root.addWidget(self.progress)

        # Ações
        self.buttons: dict[str, QToolButton] = {}
        grid = QGridLayout()
        grid.setSpacing(2)
        for i, (key, ic, text, tip) in enumerate(ACTIONS):
            b = QToolButton()
            b.setObjectName("action")
            b.setIcon(icon(ic, "#c9cfdb", 20))
            b.setIconSize(QSize(20, 20))
            b.setText(text)
            b.setToolTip(tip)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k, self.name))
            grid.addWidget(b, i // 4, i % 4)
            self.buttons[key] = b
        self.actions_box = QWidget()
        self.actions_box.setLayout(grid)
        root.addWidget(self.actions_box)

        self.btn_create = QPushButton("Criar este celular")
        self.btn_create.setObjectName("primary")
        self.btn_create.setIcon(icon("add", "white", 16))
        self.btn_create.clicked.connect(lambda: self.action.emit("create", self.name))
        root.addWidget(self.btn_create)

        # estado inicial até a primeira leitura
        self.lbl_status.setText("Carregando…")
        self.lbl_status.setStyleSheet(f"font-weight:600; color:{theme.MUTED};")
        self.info_box.hide()
        self.actions_box.hide()
        self.btn_create.hide()
        self.check.setEnabled(False)

    # ------------------------------------------------------------------
    def _on_check(self, checked: bool):
        self.setProperty("selected", "true" if checked else "false")
        self._repolish()
        self.selection_changed.emit()

    def _repolish(self):
        self.style().unpolish(self)
        self.style().polish(self)

    def is_selected(self) -> bool:
        return self.check.isChecked()

    def set_selected(self, value: bool):
        self.check.setChecked(value)

    def update_state(self, st: PhoneState, display_name: str, last_backup: datetime | None,
                     local_busy: str = ""):
        self.state = st
        status = st.status
        color = theme.STATUS_COLORS.get(status, theme.GRAY)
        text = st.busy_text or theme.STATUS_TEXT.get(status, status)
        if local_busy:
            text = local_busy
        self.dot.set_color(color)
        self.lbl_name.setText(display_name)
        self.lbl_status.setText(text)
        self.lbl_status.setStyleSheet(f"font-weight:600; color:{color};")

        running = st.running
        if self.property("running") != ("true" if running else "false"):
            self.setProperty("running", "true" if running else "false")
            self._repolish()

        info = st.info
        exists = bool(info and info.exists)
        self.info_box.setVisible(exists)
        self.actions_box.setVisible(exists)
        self.btn_create.setVisible(status == MISSING)
        self.check.setEnabled(exists)
        if not exists and self.check.isChecked():
            self.check.setChecked(False)

        if exists:
            api = info.api_level
            tag = info.image_tag
            self.vals["android"].setText(f"{info.android} (API {api})" + (f" · {tag}" if tag else ""))
            self.vals["ram"].setText(f"{info.ram_mb} MB" if info.ram_mb else "—")
            self.vals["storage"].setText(human_size(info.storage_bytes) if info.storage_bytes else "—")
            w, h, d = info.lcd
            self.vals["screen"].setText(f"{w}×{h} · {d} dpi" if w else "—")
            self.vals["backup"].setText(last_backup.strftime("%d/%m/%Y %H:%M") if last_backup else "Nenhum")
            if st.serial and running:
                self.badge.setText(f"#{phone_number(self.name):02d} · {st.serial.replace('emulator-', ':')}")
            else:
                self.badge.setText(f"#{phone_number(self.name):02d}")

        msg = st.message if status == ERROR else ""
        if status == MISSING:
            msg = "Este celular ainda não foi criado."
        self.lbl_msg.setText(msg)
        self.lbl_msg.setVisible(bool(msg))

        transitional = status in (BOOTING, STARTING, STOPPING, RESTARTING) or bool(local_busy) or status == "busy"
        self.progress.setVisible(transitional)

        idle = not transitional
        b = self.buttons
        b["start"].setEnabled(exists and status == OFF and idle)
        b["stop"].setEnabled(running and status != STOPPING and not local_busy)
        b["restart"].setEnabled(status == ON and idle)
        b["window"].setEnabled(running)
        b["apk"].setEnabled(status == ON and idle)
        b["settings"].setEnabled(exists and idle)
        b["files"].setEnabled(exists)
        b["backup"].setEnabled(exists and idle)
