"""Componentes e diálogos de mensagem compartilhados."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ui.icons import icon


def _box(parent, kind, title, text, details=""):
    box = QMessageBox(parent)
    box.setIcon(kind)
    box.setWindowTitle(title)
    box.setText(text)
    if details:
        box.setDetailedText(details)
    return box


def error(parent, title: str, text: str, details: str = "") -> None:
    _box(parent, QMessageBox.Icon.Critical, title, text, details).exec()


def info(parent, title: str, text: str) -> None:
    _box(parent, QMessageBox.Icon.Information, title, text).exec()


def warn(parent, title: str, text: str) -> None:
    _box(parent, QMessageBox.Icon.Warning, title, text).exec()


def confirm(parent, title: str, text: str, ok_text: str = "Continuar", danger: bool = False,
            cancel_text: str = "Cancelar") -> bool:
    box = _box(parent, QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question, title, text)
    ok = box.addButton(ok_text, QMessageBox.ButtonRole.AcceptRole)
    if danger:
        ok.setObjectName("danger")
    cancel = box.addButton(cancel_text, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel if danger else ok)
    box.exec()
    return box.clickedButton() is ok


def choose(parent, title: str, text: str, options: list[str], default: int = 0) -> int:
    """Pergunta com várias opções. Retorna o índice escolhido ou -1 se fechar."""
    box = _box(parent, QMessageBox.Icon.Question, title, text)
    buttons = [box.addButton(o, QMessageBox.ButtonRole.AcceptRole) for o in options]
    box.setDefaultButton(buttons[default])
    box.exec()
    clicked = box.clickedButton()
    return buttons.index(clicked) if clicked in buttons else -1


class Banner(QFrame):
    """Faixa de aviso no topo da janela."""
    action_clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.ic = QLabel()
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.btn = QPushButton()
        self.btn.hide()
        self.btn.clicked.connect(self.action_clicked.emit)
        lay.addWidget(self.ic)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.btn)
        self.hide()

    def show_message(self, kind: str, text: str, action: str = ""):
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        color = {"warn": "#f5b544", "error": "#ff7b84", "info": "#8fb3ff"}.get(kind, "#ffffff")
        self.ic.setPixmap(icon("warning" if kind != "info" else "info", color, 18).pixmap(18, 18))
        self.text.setText(text)
        self.btn.setText(action)
        self.btn.setVisible(bool(action))
        self.show()


def section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


def muted(text: str, wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    lbl.setWordWrap(wrap)
    return lbl


def button_row(*buttons, stretch_first=True) -> QHBoxLayout:
    row = QHBoxLayout()
    if stretch_first:
        row.addStretch(1)
    for b in buttons:
        row.addWidget(b)
    return row


class BaseDialog(QDialog):
    def __init__(self, parent: QWidget | None, title: str, width: int = 560):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(20, 18, 20, 16)
        self.body.setSpacing(10)
