"""Ícones desenhados com a fonte de ícones do Windows 11 (Segoe Fluent Icons / MDL2)."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPen, QPixmap

GLYPHS = {
    "play": "",
    "power": "",
    "restart": "",
    "window": "",
    "apk": "",
    "settings": "",
    "folder": "",
    "backup": "",
    "add": "",
    "phone": "",
    "warning": "",
    "check": "",
    "error": "",
    "upload": "",
    "delete": "",
    "import": "",
    "export": "",
    "info": "",
    "selectall": "",
    "stop": "",
    "log": "",
    "refresh": "",
    "grid": "",
    "tools": "",
    "download": "",
}


@lru_cache(maxsize=1)
def icon_family() -> str:
    families = set(QFontDatabase.families())
    for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets"):
        if f in families:
            return f
    return ""


@lru_cache(maxsize=256)
def icon(name: str, color: str = "#c9cfdb", size: int = 20) -> QIcon:
    glyph = GLYPHS.get(name, "?")
    ic = QIcon()
    for scale in (1, 2):
        px = QPixmap(size * scale, size * scale)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        fam = icon_family()
        if fam:
            f = QFont(fam)
            f.setPixelSize(int(size * scale * 0.8))
            p.setFont(f)
            p.setPen(QColor(color))
            p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
        else:
            p.setPen(QColor(color))
            p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, name[:1].upper())
        p.end()
        px.setDevicePixelRatio(scale)
        ic.addPixmap(px)
    # versão desabilitada mais apagada
    return ic


def app_icon() -> QIcon:
    """Ícone do aplicativo: celular com grade, desenhado em código."""
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        px = QPixmap(s, s)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92)
        path = QPainterPath()
        path.addRoundedRect(r, s * 0.22, s * 0.22)
        p.fillPath(path, QColor("#3d7bfd"))
        # celular
        w, h = s * 0.42, s * 0.66
        phone = QRectF((s - w) / 2, (s - h) / 2, w, h)
        p.setPen(QPen(QColor("white"), max(1.0, s * 0.055)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(phone, s * 0.07, s * 0.07)
        # grade 2x2 de "telas"
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 220))
        g = s * 0.075
        cw = (w - 3 * g) / 2
        ch = (h * 0.62 - 3 * g) / 2
        for i in range(2):
            for j in range(2):
                p.drawRoundedRect(QRectF(phone.x() + g + i * (cw + g), phone.y() + g * 1.6 + j * (ch + g), cw, ch), s * 0.02, s * 0.02)
        p.drawEllipse(QPointF(s / 2, phone.bottom() - h * 0.12), s * 0.035, s * 0.035)
        p.end()
        ic.addPixmap(px)
    return ic
