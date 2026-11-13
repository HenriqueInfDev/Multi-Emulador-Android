"""Arquivos do emulador: pasta de dados no PC e transferências com o celular (adb push/pull)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QGridLayout, QLabel, QPushButton

from emulators.manager import ON
from ui.common import BaseDialog, error, muted, section
from ui.icons import icon
from ui.workers import run_task
from utils.system import dir_size, human_size, open_file, open_folder


class FilesDialog(BaseDialog):
    def __init__(self, parent, manager, name: str, status: str):
        super().__init__(parent, f"Arquivos — {manager.settings.display_name(name)}", 560)
        self.manager = manager
        self.name = name
        info = manager.avds.read(name)
        online = status == ON

        self.body.addWidget(section("No computador"))
        self.body.addWidget(muted(f"Pasta de dados do celular:\n{info.path}"))
        self.size = QLabel("Calculando tamanho…")
        self.size.setObjectName("muted")
        self.body.addWidget(self.size)
        run_task(dir_size, info.path, on_done=lambda n: self.size.setText(f"Ocupando {human_size(n)} no disco"))

        g = QGridLayout()
        b1 = self._btn("Abrir pasta de dados", "folder", lambda: open_folder(info.path))
        b2 = self._btn("Abrir pasta de backups", "backup", lambda: open_folder(manager.backups.phone_dir(name)))
        b3 = self._btn("Ver log do emulador", "log", self._open_log)
        g.addWidget(b1, 0, 0); g.addWidget(b2, 0, 1); g.addWidget(b3, 1, 0)
        self.body.addLayout(g)
        self.body.addWidget(muted("Não altere nem apague arquivos dessa pasta manualmente: são o disco do celular."))

        self.body.addWidget(section("Transferir com o celular"))
        self.body.addWidget(muted("Os arquivos enviados vão para a pasta Download do celular." if online
                                  else "Ligue o celular para transferir arquivos."))
        g2 = QGridLayout()
        self.b_push = self._btn("Enviar arquivos para o celular…", "upload", self._push)
        self.b_pull = self._btn("Copiar Download do celular para o PC…", "import", self._pull)
        self.b_shots = self._btn("Copiar fotos e capturas (DCIM)…", "import", self._pull_dcim)
        for b in (self.b_push, self.b_pull, self.b_shots):
            b.setEnabled(online)
        g2.addWidget(self.b_push, 0, 0); g2.addWidget(self.b_pull, 0, 1); g2.addWidget(self.b_shots, 1, 0)
        self.body.addLayout(g2)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)

        close = QPushButton("Fechar")
        close.clicked.connect(self.reject)
        self.body.addWidget(close)

    def _btn(self, text, ic, slot):
        b = QPushButton(text)
        b.setIcon(icon(ic, "#c9cfdb", 16))
        b.clicked.connect(slot)
        return b

    def _open_log(self):
        p = self.manager.log_path(self.name)
        if p.exists():
            open_file(p)
        else:
            error(self, "Log", "Este celular ainda não foi iniciado pelo gerenciador.")

    def _busy(self, text):
        self.status.setText(text)
        for b in (self.b_push, self.b_pull, self.b_shots):
            b.setEnabled(False)

    def _idle(self, text):
        self.status.setText(text)
        for b in (self.b_push, self.b_pull, self.b_shots):
            b.setEnabled(True)

    def _fail(self, exc):
        self._idle("")
        error(self, "Transferência", str(exc))

    def _push(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Enviar para o celular")
        if not files:
            return
        self._busy(f"Enviando {len(files)} arquivo(s)…")
        run_task(self.manager.push_files, self.name, files,
                 on_done=lambda _: self._idle(f"✔ {len(files)} arquivo(s) enviados para Download."), on_error=self._fail)

    def _pull_remote(self, remote: str, label: str):
        dest = QFileDialog.getExistingDirectory(self, "Salvar no computador em…")
        if not dest:
            return
        target = Path(dest) / f"{self.name}_{label}_{datetime.now():%Y-%m-%d_%H-%M-%S}"
        target.mkdir(parents=True, exist_ok=True)
        self._busy("Copiando…")
        run_task(self.manager.pull_dir, self.name, remote, str(target),
                 on_done=lambda _: (self._idle(f"✔ Copiado para {target}"), open_folder(target)), on_error=self._fail)

    def _pull(self):
        self._pull_remote("/sdcard/Download/.", "Download")

    def _pull_dcim(self):
        self._pull_remote("/sdcard/DCIM/.", "DCIM")
