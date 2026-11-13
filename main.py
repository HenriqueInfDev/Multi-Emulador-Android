"""Android Emulator Manager — gerenciador de até 12 emuladores Android independentes.

Uso:
    python main.py
    python main.py --screenshot arquivo.png [--delay 6]   (gera uma captura da janela e fecha; usado em testes)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from config.settings import APP_NAME, APP_TITLE, SettingsStore, logs_dir  # noqa: E402


def setup_logging() -> None:
    handler = RotatingFileHandler(logs_dir() / "manager.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def single_instance_lock():
    """Impede abrir dois gerenciadores ao mesmo tempo (evita comandos conflitantes nos mesmos emuladores)."""
    import ctypes

    handle = ctypes.windll.kernel32.CreateMutexW(None, False, f"Local\\{APP_NAME}_instance")
    already = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    return handle, already


def start_from_cli(names: list[str]) -> int:
    """Liga celulares pela linha de comando (atalhos, Agendador de Tarefas). Erros vão para o log."""
    from emulators.manager import EmulatorManager

    manager = EmulatorManager(SettingsStore())
    code = 0
    for name in names:
        try:
            serial = manager.start(name)
            logging.info("CLI: %s iniciado (%s)", name, serial)
        except Exception as exc:  # noqa: BLE001
            logging.error("CLI: falha ao iniciar %s: %s", name, exc)
            code = 1
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot")
    parser.add_argument("--delay", type=float, default=6)
    parser.add_argument("--start", nargs="+", metavar="CELULAR",
                        help="liga os celulares indicados (ex.: celular_01) sem abrir a janela e sai")
    args, _ = parser.parse_known_args()

    setup_logging()
    if args.start:
        return start_from_cli(args.start)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setStyle("Fusion")

    from ui.theme import QSS
    app.setStyleSheet(QSS)

    _mutex, already = single_instance_lock()
    if already and not args.screenshot:
        QMessageBox.information(None, APP_TITLE, "O Android Emulator Manager já está aberto.")
        return 0

    from emulators.manager import EmulatorManager
    from ui.main_window import MainWindow

    store = SettingsStore()
    manager = EmulatorManager(store)
    win = MainWindow(store, manager)
    win.show()

    if args.screenshot:
        def shot():
            win.grab().save(args.screenshot)
            win._force_close = True
            app.quit()
        QTimer.singleShot(int(args.delay * 1000), shot)

    logging.info("Gerenciador iniciado")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
