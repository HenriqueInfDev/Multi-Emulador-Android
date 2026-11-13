"""Instalação de APKs em um ou vários celulares ao mesmo tempo (adb install)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
)

from config.settings import phone_names
from emulators.manager import ON
from ui import theme
from ui.common import BaseDialog, button_row, error, muted, section
from ui.icons import icon
from ui.workers import run_task


class ApkDialog(BaseDialog):
    def __init__(self, parent, manager, snapshot, preselect: list[str] | None = None):
        super().__init__(parent, "Instalar aplicativos (APK)", 680)
        self.manager = manager
        self.files: list[str] = []
        self.pending = 0
        self.rows: dict[str, int] = {}

        self.body.addWidget(section("1. Arquivos"))
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumHeight(90)
        btns = QHBoxLayout()
        b_add = QPushButton("Escolher APK…")
        b_add.setIcon(icon("apk", "#c9cfdb", 16))
        b_add.clicked.connect(self._pick)
        b_clear = QPushButton("Limpar")
        b_clear.clicked.connect(self._clear)
        row.addWidget(self.list, 1)
        col = QGridLayout()
        col.addWidget(b_add, 0, 0)
        col.addWidget(b_clear, 1, 0)
        row.addLayout(col)
        self.body.addLayout(row)
        self.split = QCheckBox("Os arquivos são partes (split APK) do MESMO aplicativo — instalar juntos")
        self.split.setToolTip("Usa 'adb install-multiple'. Desmarcado, cada APK é instalado como um app separado.")
        self.body.addWidget(self.split)
        opts = QHBoxLayout()
        self.grant = QCheckBox("Conceder todas as permissões")
        self.downgrade = QCheckBox("Permitir versão mais antiga (downgrade)")
        opts.addWidget(self.grant); opts.addWidget(self.downgrade); opts.addStretch(1)
        self.body.addLayout(opts)
        self.body.addWidget(muted("Apps já instalados são atualizados mantendo os dados."))

        self.body.addWidget(section("2. Celulares"))
        self.body.addWidget(muted("Só é possível instalar em celulares ligados e com o Android já iniciado."))
        grid = QGridLayout()
        self.checks: dict[str, QCheckBox] = {}
        for i, name in enumerate(phone_names()):
            st = snapshot.phones.get(name) if snapshot else None
            cb = QCheckBox(manager.settings.display_name(name))
            online = bool(st and st.status == ON)
            exists = bool(st and st.info and st.info.exists)
            cb.setEnabled(online)
            if not exists:
                cb.setToolTip("Não criado")
            elif not online:
                cb.setToolTip("Desligado ou ainda inicializando")
            cb.setChecked(online and (preselect is None or name in preselect))
            grid.addWidget(cb, i // 4, i % 4)
            self.checks[name] = cb
        self.body.addLayout(grid)
        sel = QHBoxLayout()
        b_all = QPushButton("Todos os ligados")
        b_all.clicked.connect(lambda: [c.setChecked(True) for c in self.checks.values() if c.isEnabled()])
        b_none = QPushButton("Nenhum")
        b_none.clicked.connect(lambda: [c.setChecked(False) for c in self.checks.values()])
        sel.addWidget(b_all); sel.addWidget(b_none); sel.addStretch(1)
        self.body.addLayout(sel)

        self.body.addWidget(section("3. Progresso"))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Celular", "Resultado"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(140)
        self.body.addWidget(self.table)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.body.addWidget(self.progress)

        self.btn_close = QPushButton("Fechar")
        self.btn_close.clicked.connect(self.reject)
        self.btn_install = QPushButton("Instalar")
        self.btn_install.setObjectName("primary")
        self.btn_install.clicked.connect(self._install)
        self.body.addLayout(button_row(self.btn_close, self.btn_install))

    def _pick(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Escolher APK", str(Path.home() / "Downloads"),
                                                "Aplicativos Android (*.apk)")
        for f in files:
            if f not in self.files:
                self.files.append(f)
                self.list.addItem(Path(f).name)

    def _clear(self):
        self.files.clear()
        self.list.clear()

    def _set_row(self, name: str, text: str, color: str):
        r = self.rows[name]
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        item.setForeground(QColor(color))
        self.table.setItem(r, 1, item)

    def _install(self):
        if not self.files:
            error(self, "Instalar APK", "Escolha pelo menos um arquivo APK.")
            return
        targets = [n for n, c in self.checks.items() if c.isChecked() and c.isEnabled()]
        if not targets:
            error(self, "Instalar APK", "Selecione pelo menos um celular ligado.")
            return
        if self.split.isChecked():
            jobs = [self.files]
        else:
            jobs = [[f] for f in self.files]

        self.table.setRowCount(0)
        self.rows.clear()
        for name in targets:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(self.manager.settings.display_name(name)))
            self.rows[name] = r
            self._set_row(name, "Aguardando…", theme.MUTED)
        self.btn_install.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.pending = len(targets)
        self.progress.setRange(0, len(targets) * len(jobs))
        self.progress.setValue(0)
        grant, downgrade = self.grant.isChecked(), self.downgrade.isChecked()

        for name in targets:
            def work(progress, name=name):
                results = []
                for apks in jobs:
                    label = Path(apks[0]).name if len(apks) == 1 else f"{len(apks)} partes"
                    progress(("run", f"Instalando {label}…"))
                    try:
                        ok, msg = self.manager.install_apk(name, apks, grant=grant, downgrade=downgrade)
                    except Exception as exc:  # noqa: BLE001
                        ok, msg = False, str(exc)
                    results.append((label, ok, msg))
                    progress(("step", f"{label}: {msg}"))
                return results

            run_task(work, with_progress=True,
                     on_progress=lambda v, n=name: self._on_progress(n, v),
                     on_done=lambda res, n=name: self._on_done(n, res),
                     on_error=lambda exc, n=name: self._on_done(n, [("", False, str(exc))]))

    def _on_progress(self, name, value):
        kind, text = value
        self._set_row(name, text, theme.AMBER)
        if kind == "step":
            self.progress.setValue(self.progress.value() + 1)

    def _on_done(self, name, results):
        bad = [r for r in results if not r[1]]
        if bad:
            text = "; ".join(f"{label}: {msg}" if label else msg for label, _, msg in bad)
            self._set_row(name, "✖ " + text, theme.RED)
        else:
            self._set_row(name, f"✔ {len(results)} app(s) instalado(s)", theme.GREEN)
        self.pending -= 1
        if self.pending <= 0:
            self.progress.setValue(self.progress.maximum())
            self.btn_close.setEnabled(True)
            self.btn_install.setEnabled(True)
            self.btn_install.setText("Instalar novamente")
