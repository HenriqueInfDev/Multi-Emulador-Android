"""Criação dos celulares (AVDs) com o avdmanager oficial."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QSpinBox, QWidget,
)

from config.settings import phone_names
from services import sdk as sdk_service
from ui.common import BaseDialog, button_row, error, muted, section
from ui.workers import run_task

RESOLUTIONS = [
    ("1080 × 2400 · 420 dpi (Pixel 6)", 1080, 2400, 420),
    ("1080 × 1920 · 420 dpi (Full HD)", 1080, 1920, 420),
    ("720 × 1600 · 320 dpi (econômico)", 720, 1600, 320),
    ("720 × 1280 · 320 dpi (HD, mais leve)", 720, 1280, 320),
    ("1440 × 3120 · 560 dpi (QHD+)", 1440, 3120, 560),
    ("Personalizada", 0, 0, 0),
]


class ResolutionPicker(QWidget):
    def __init__(self, w: int, h: int, d: int):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        for label, *_ in RESOLUTIONS:
            self.combo.addItem(label)
        self.w = QSpinBox(); self.w.setRange(320, 4096); self.w.setSuffix(" px")
        self.h = QSpinBox(); self.h.setRange(320, 4096); self.h.setSuffix(" px")
        self.d = QSpinBox(); self.d.setRange(120, 720); self.d.setSuffix(" dpi")
        lay.addWidget(self.combo, 2)
        for s in (self.w, self.h, self.d):
            lay.addWidget(s, 1)
        self.combo.currentIndexChanged.connect(self._preset)
        self.set_values(w, h, d)

    def set_values(self, w, h, d):
        self.w.setValue(w or 1080); self.h.setValue(h or 2400); self.d.setValue(d or 420)
        idx = next((i for i, r in enumerate(RESOLUTIONS) if r[1:] == (w, h, d)), len(RESOLUTIONS) - 1)
        self.combo.setCurrentIndex(idx)
        self._preset(idx)

    def _preset(self, idx):
        _, w, h, d = RESOLUTIONS[idx]
        custom = w == 0
        for s in (self.w, self.h, self.d):
            s.setVisible(custom)
        if not custom:
            self.w.setValue(w); self.h.setValue(h); self.d.setValue(d)

    def values(self) -> tuple[int, int, int]:
        return self.w.value(), self.h.value(), self.d.value()


class CreateDialog(BaseDialog):
    def __init__(self, parent, manager, preselect: list[str] | None = None):
        super().__init__(parent, "Criar celulares", 640)
        self.manager = manager
        s = manager.settings
        dft = s.defaults
        self.task = None
        self.created: list[str] = []

        self.body.addWidget(section("Quais celulares criar"))
        self.body.addWidget(muted("Somente celulares que ainda não existem aparecem disponíveis. "
                                  "Um celular existente nunca é recriado ou formatado."))
        grid = QGridLayout()
        self.checks: dict[str, QCheckBox] = {}
        for i, name in enumerate(phone_names()):
            info = manager.avds.read(name)
            cb = QCheckBox(s.display_name(name))
            blocked = info.exists or info.ini_path.exists() or info.path.exists()
            cb.setEnabled(not blocked)
            if blocked:
                cb.setToolTip("Já existe" if info.exists else info.problem)
                cb.setText(cb.text() + (" (já existe)" if info.exists else " (verificar)"))
            elif preselect is None or name in preselect:
                cb.setChecked(preselect is not None)
            grid.addWidget(cb, i // 4, i % 4)
            self.checks[name] = cb
        self.body.addLayout(grid)
        sel_row = QHBoxLayout()
        b_all = QPushButton("Marcar todos disponíveis")
        b_all.clicked.connect(lambda: [c.setChecked(True) for c in self.checks.values() if c.isEnabled()])
        b_none = QPushButton("Desmarcar")
        b_none.clicked.connect(lambda: [c.setChecked(False) for c in self.checks.values()])
        sel_row.addWidget(b_all); sel_row.addWidget(b_none); sel_row.addStretch(1)
        self.body.addLayout(sel_row)

        self.body.addWidget(section("Configuração"))
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.image = QComboBox()
        self.images = sdk_service.list_system_images(manager.paths.sdk)
        for img in self.images:
            self.image.addItem(img.label, img.package)
        if dft.system_image:
            i = self.image.findData(dft.system_image)
            if i >= 0:
                self.image.setCurrentIndex(i)
        form.addRow("Versão do Android", self.image)
        if not self.images:
            form.addRow("", muted("Nenhuma imagem do sistema instalada. Instale uma em Configurações → Android SDK."))

        self.profile = QComboBox()
        self.profile.setEditable(True)
        self.profile.addItem(dft.device_profile or "pixel_6")
        form.addRow("Modelo (perfil)", self.profile)
        run_task(sdk_service.list_device_profiles, manager.paths.avdmanager, manager.env(),
                 on_done=self._fill_profiles)

        self.ram = QSpinBox(); self.ram.setRange(1024, 16384); self.ram.setSingleStep(512); self.ram.setSuffix(" MB")
        self.ram.setValue(dft.ram_mb)
        form.addRow("Memória RAM", self.ram)
        self.storage = QSpinBox(); self.storage.setRange(2, 256); self.storage.setSuffix(" GB")
        self.storage.setValue(dft.storage_gb)
        form.addRow("Armazenamento interno", self.storage)
        self.res = ResolutionPicker(dft.lcd_width, dft.lcd_height, dft.lcd_density)
        form.addRow("Tela", self.res)
        self.cores = QSpinBox(); self.cores.setRange(1, 8); self.cores.setValue(dft.cpu_cores)
        form.addRow("Núcleos de CPU", self.cores)
        self.body.addLayout(form)
        self.body.addWidget(muted("Os arquivos do disco crescem conforme o uso; o armazenamento é o limite máximo."))

        self.progress = QProgressBar(); self.progress.hide()
        self.status = QLabel(""); self.status.setWordWrap(True)
        self.body.addWidget(self.progress)
        self.body.addWidget(self.status)

        self.btn_cancel = QPushButton("Fechar")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok = QPushButton("Criar")
        self.btn_ok.setObjectName("primary")
        self.btn_ok.clicked.connect(self._create)
        self.body.addLayout(button_row(self.btn_cancel, self.btn_ok))

    def _fill_profiles(self, profiles):
        current = self.profile.currentText()
        self.profile.clear()
        phones = [p for p in profiles if "pixel" in p.lower() or "phone" in p.lower() or "nexus" in p.lower()]
        self.profile.addItems(phones or profiles or [current])
        i = self.profile.findText(current)
        self.profile.setCurrentIndex(max(0, i))

    def _create(self):
        names = [n for n, c in self.checks.items() if c.isChecked() and c.isEnabled()]
        if not names:
            error(self, "Criar celulares", "Selecione pelo menos um celular.")
            return
        if self.image.currentData() is None:
            error(self, "Criar celulares", "Nenhuma imagem do sistema Android instalada.")
            return
        for c in self.checks.values():
            c.setEnabled(False)
        self.btn_ok.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.progress.setRange(0, len(names))
        self.progress.setValue(0)
        self.progress.show()
        params = dict(
            system_image=self.image.currentData(),
            device_profile=self.profile.currentText().strip(),
            ram_mb=self.ram.value(),
            storage_gb=self.storage.value(),
            lcd=self.res.values(),
            cpu_cores=self.cores.value(),
        )
        m = self.manager

        def work(progress):
            results = []
            for i, name in enumerate(names):
                progress((i, f"Criando {m.settings.display_name(name)}…"))
                try:
                    m.avds.create(name, m.paths.avdmanager, m.paths.sdk, display_name=m.settings.display_name(name), **params)
                    results.append((name, True, ""))
                except Exception as exc:  # noqa: BLE001
                    results.append((name, False, str(exc)))
            return results

        self.task = run_task(work, with_progress=True, on_progress=self._on_progress,
                             on_done=self._done, on_error=self._failed)

    def _on_progress(self, value):
        i, text = value
        self.progress.setValue(i)
        self.status.setText(text)

    def _done(self, results):
        self.progress.setValue(self.progress.maximum())
        ok = [n for n, good, _ in results if good]
        bad = [(n, e) for n, good, e in results if not good]
        self.created = ok
        lines = []
        if ok:
            lines.append(f"✔ Criados: {', '.join(ok)}")
        for n, e in bad:
            lines.append(f"✖ {n}: {e}")
        self.status.setText("\n".join(lines))
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setText("Concluir")
        if bad:
            error(self, "Criar celulares", "Alguns celulares não foram criados.", "\n\n".join(f"{n}: {e}" for n, e in bad))

    def _failed(self, exc):
        self.btn_cancel.setEnabled(True)
        error(self, "Criar celulares", str(exc))
