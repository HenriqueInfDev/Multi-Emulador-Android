"""Backups de um celular: criar, restaurar, exportar, importar e excluir."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem,
)

from backup.backup import BackupInfo, Cancelled
from ui.common import Banner, BaseDialog, confirm, error, info, muted, section
from ui.icons import icon
from ui.workers import run_task
from utils.system import human_size, open_folder


class BackupDialog(BaseDialog):
    def __init__(self, parent, manager, name: str):
        super().__init__(parent, f"Backups — {manager.settings.display_name(name)}", 760)
        self.manager = manager
        self.bm = manager.backups
        self.name = name
        self.task = None
        self.backups: list[BackupInfo] = []

        self.banner = Banner()
        self.body.addWidget(self.banner)

        self.body.addWidget(section("Novo backup"))
        self.body.addWidget(muted(
            "Copia o celular inteiro (apps, contas, configurações, arquivos e histórico). "
            "O celular precisa estar desligado para a cópia ser consistente."))
        row = QHBoxLayout()
        self.label = QLineEdit()
        self.label.setPlaceholderText("Descrição opcional (ex.: antes de atualizar o app)")
        self.snap = QCheckBox("Incluir estado rápido (quick boot)")
        self.snap.setToolTip("Inclui a 'foto' da memória para religar instantaneamente. "
                             "Ocupa vários GB a mais; sem ela o celular faz uma inicialização normal após restaurar.")
        self.btn_new = QPushButton("Criar backup")
        self.btn_new.setObjectName("primary")
        self.btn_new.setIcon(icon("backup", "white", 16))
        self.btn_new.clicked.connect(self._create)
        row.addWidget(self.label, 1)
        row.addWidget(self.snap)
        row.addWidget(self.btn_new)
        self.body.addLayout(row)

        self.body.addWidget(section("Backups salvos"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Data e hora", "Tipo", "Descrição", "Tamanho", "Android"])
        hh = self.table.horizontalHeader()
        for i in range(5):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(220)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.body.addWidget(self.table)

        actions = QHBoxLayout()
        self.btn_restore = QPushButton("Restaurar")
        self.btn_restore.setIcon(icon("restart", "#c9cfdb", 16))
        self.btn_restore.clicked.connect(self._restore)
        self.btn_export = QPushButton("Exportar…")
        self.btn_export.setIcon(icon("export", "#c9cfdb", 16))
        self.btn_export.clicked.connect(self._export)
        self.btn_import = QPushButton("Importar…")
        self.btn_import.setIcon(icon("import", "#c9cfdb", 16))
        self.btn_import.clicked.connect(self._import)
        self.btn_delete = QPushButton("Excluir")
        self.btn_delete.setIcon(icon("delete", "#ff9aa2", 16))
        self.btn_delete.clicked.connect(self._delete)
        self.btn_folder = QPushButton("Abrir pasta")
        self.btn_folder.setIcon(icon("folder", "#c9cfdb", 16))
        self.btn_folder.clicked.connect(lambda: open_folder(self.bm.phone_dir(self.name)))
        for b in (self.btn_restore, self.btn_export, self.btn_import, self.btn_delete):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(self.btn_folder)
        self.body.addLayout(actions)

        prow = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.hide()
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.hide()
        self.btn_cancel.clicked.connect(self._cancel)
        prow.addWidget(self.progress, 1)
        prow.addWidget(self.btn_cancel)
        self.body.addLayout(prow)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)

        close_row = QHBoxLayout()
        close_row.addWidget(muted(f"Pasta: {self.bm.phone_dir(name)}"), 1)
        self.btn_close = QPushButton("Fechar")
        self.btn_close.clicked.connect(self.reject)
        close_row.addWidget(self.btn_close)
        self.body.addLayout(close_row)

        self._reload()

    # ------------------------------------------------------------------
    def _running(self) -> bool:
        return bool(self.manager.scan_processes().get(self.name))

    def _reload(self):
        self.backups = self.bm.list(self.name)
        self.table.setRowCount(0)
        for b in self.backups:
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [b.created.strftime("%d/%m/%Y %H:%M:%S"), b.kind_text, b.label or "—",
                    human_size(b.size), b.android or "—"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 3:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, it)
        if self.backups:
            self.table.selectRow(0)
        running = self._running()
        if running:
            self.banner.show_message("warn", "Este celular está ligado. Desligue-o para criar ou restaurar backups. "
                                             "Exportar, importar e excluir continuam disponíveis.")
        else:
            self.banner.hide()
        self._update_buttons()

    def _selected(self) -> BackupInfo | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.backups[rows[0].row()]

    def _update_buttons(self, busy: bool = False):
        busy = busy or self.task is not None
        running = self._running() if not busy else True
        sel = self._selected() is not None
        self.btn_new.setEnabled(not busy and not running)
        self.btn_restore.setEnabled(not busy and not running and sel)
        self.btn_export.setEnabled(not busy and sel)
        self.btn_delete.setEnabled(not busy and sel)
        self.btn_import.setEnabled(not busy)
        self.btn_close.setEnabled(not busy)

    # ------------------------------------------------------------------ execução com progresso
    def _run(self, fn, busy_text: str, on_done, *args, **kwargs):
        self.manager.set_busy(self.name, "busy", busy_text)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.show()
        self.btn_cancel.show()
        self.btn_cancel.setEnabled(True)
        self.status.setText(busy_text)
        self._t0 = time.time()

        def done(result):
            self._finish()
            on_done(result)

        def failed(exc):
            self._finish()
            if isinstance(exc, Cancelled):
                self.status.setText("Operação cancelada. Nada foi alterado.")
            else:
                self.status.setText("")
                error(self, "Backup", str(exc))

        self.task = run_task(fn, *args, with_progress=True, with_cancel=True,
                             on_progress=self._on_progress, on_done=done, on_error=failed, **kwargs)
        self._update_buttons(busy=True)

    def _on_progress(self, value):
        done, total, current = value
        if total:
            self.progress.setValue(int(done * 1000 / total))
            elapsed = max(0.1, time.time() - self._t0)
            speed = done / elapsed
            self.status.setText(f"{human_size(done)} de {human_size(total)} · {human_size(speed)}/s · {current}")

    def _finish(self):
        self.manager.clear_busy(self.name)
        self.task = None
        self.progress.hide()
        self.btn_cancel.hide()
        self._reload()

    def _cancel(self):
        if self.task:
            self.task.cancel()
            self.btn_cancel.setEnabled(False)
            self.status.setText("Cancelando…")

    def reject(self):
        if self.task:
            return  # não fecha no meio de uma cópia
        super().reject()

    # ------------------------------------------------------------------ ações
    def _create(self):
        if self._running():
            error(self, "Backup", "Desligue o celular antes de criar o backup.")
            return
        self._run(self.bm.create, "Criando backup…", self._created, self.name,
                  label=self.label.text().strip(), include_snapshots=self.snap.isChecked())

    def _created(self, b):
        self.label.clear()
        self.status.setText(f"✔ Backup criado: {b.id} ({human_size(b.size)})")

    def _restore(self):
        b = self._selected()
        if not b:
            return
        if self._running():
            error(self, "Restaurar", "Desligue o celular antes de restaurar.")
            return
        text = (f"Os dados atuais de {self.manager.settings.display_name(self.name)} serão substituídos pelo backup de "
                f"{b.created.strftime('%d/%m/%Y %H:%M')}.\n\n"
                "Por segurança, o estado atual será guardado automaticamente como um novo backup "
                "(\"Antes de restaurar\"), para você poder voltar atrás.")
        if not confirm(self, "Restaurar backup", text, "Restaurar", danger=True):
            return
        self._run(self.bm.restore, "Restaurando backup…", self._restored, self.name, b, keep_current=True,
                  sdk=self.manager.paths.sdk)

    def _restored(self, warnings):
        self.status.setText("✔ Backup restaurado. O estado anterior foi guardado como backup automático.")
        if warnings:
            info(self, "Restaurar", "Restauração concluída com avisos:\n\n" + "\n\n".join(warnings))

    def _export(self):
        b = self._selected()
        if not b:
            return
        dest = QFileDialog.getExistingDirectory(self, "Exportar backup para…")
        if not dest:
            return
        self._run(self.bm.export, "Exportando backup…", self._exported, b, dest)

    def _exported(self, path):
        self.status.setText(f"✔ Exportado para {path}")

    def _import(self):
        src = QFileDialog.getExistingDirectory(self, "Escolha a pasta de um backup exportado")
        if not src:
            return
        self._run(self.bm.import_backup, "Importando backup…", self._imported, self.name, src)

    def _imported(self, b):
        self.status.setText(f"✔ Backup importado: {b.id}")

    def _delete(self):
        b = self._selected()
        if not b:
            return
        if not confirm(self, "Excluir backup",
                       f"Excluir definitivamente o backup de {b.created.strftime('%d/%m/%Y %H:%M:%S')} "
                       f"({human_size(b.size)})?\n\nIsso não pode ser desfeito. Os dados do celular não são afetados.",
                       "Excluir", danger=True):
            return
        try:
            self.bm.delete(b)
        except Exception as exc:  # noqa: BLE001
            error(self, "Excluir backup", str(exc))
        self._reload()
