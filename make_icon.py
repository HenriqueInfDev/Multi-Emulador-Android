"""Gera assets/app.ico a partir do ícone desenhado em ui/icons.py (usado no build do .exe)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
from ui.icons import app_icon  # noqa: E402

out = Path(__file__).resolve().parent / "assets" / "app.ico"
out.parent.mkdir(exist_ok=True)
pix = app_icon().pixmap(256, 256)
if not pix.save(str(out), "ICO"):
    pix.save(str(out.with_suffix(".png")), "PNG")
    print("Formato ICO indisponível; gerado PNG")
else:
    print("Gerado", out)
