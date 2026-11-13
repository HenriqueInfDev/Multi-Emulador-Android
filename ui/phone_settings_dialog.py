"""Configurações individuais de um celular."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
)

from emulators.avd import AvdError
from ui.common import Banner, BaseDialog, button_row, confirm, error, muted, section
from ui.create_dialog import ResolutionPicker

GPU_MODES = [
    ("", "Usar o padrão geral"),
    ("auto", "Automático"),
    ("host", "Placa de vídeo (host)"),
    ("swiftshader_indirect", "Software (SwiftShader) — mais compatível"),
    ("angle_indirect", "ANGLE (DirectX)"),
]


class PhoneSettingsDialog(BaseDialog):
    def __init__(self, parent, manager, name: str):
        super().__init__(parent, f"Configurações — {manager.settings.display_name(name)}", 560)
        self.manager = manager
        self.name = name
        self.info = manager.avds.read(name)
        self.opt = manager.settings.phone(name)
        running = bool(manager.scan_processes().get(name))

        banner = Banner()
        self.body.addWidget(banner)
        if running:
            banner.show_message("warn", "O celular está ligado. Desligue-o para alterar as configurações do hardware. "
                                        "Nome e opções de inicialização podem ser alterados agora.")

        self.body.addWidget(section("Identificação"))
        form = QFormLayout()
        self.display = QLineEdit(manager.settings.display_name(name))
        form.addRow("Nome exibido", self.display)
        form.addRow("Identificador (AVD)", QLabel(name))
        form.addRow("Pasta de dados", muted(str(self.info.path)))
        self.body.addLayout(form)

        self.body.addWidget(section("Hardware"))
        hw = QFormLayout()
        hw.addRow("Android", QLabel(f"{self.info.android} (API {self.info.api_level}) · {self.info.image_tag}"))
        hw.addRow("", muted("A versão do Android é definida na criação. Trocar a versão de um celular existente "
                            "corromperia os dados, por isso não é feita automaticamente."))
        self.ram = QSpinBox(); self.ram.setRange(1024, 16384); self.ram.setSingleStep(512); self.ram.setSuffix(" MB")
        self.ram.setValue(self.info.ram_mb or 2048)
        hw.addRow("Memória RAM", self.ram)
        cur_gb = max(1, round(self.info.storage_bytes / 1024**3)) if self.info.storage_bytes else 6
        self.storage = QSpinBox(); self.storage.setRange(cur_gb, 512); self.storage.setSuffix(" GB")
        self.storage.setValue(cur_gb)
        self.storage.setToolTip("Só pode ser aumentado. Faça um backup antes de aumentar.")
        hw.addRow("Armazenamento", self.storage)
        w, h, d = self.info.lcd
        self.res = ResolutionPicker(w, h, d)
        hw.addRow("Tela", self.res)
        self.cores = QSpinBox(); self.cores.setRange(1, 8); self.cores.setValue(self.info.cpu_cores or 2)
        hw.addRow("Núcleos de CPU", self.cores)
        self.body.addLayout(hw)
        for wdg in (self.ram, self.storage, self.res, self.cores):
            wdg.setEnabled(not running)

        self.body.addWidget(section("Inicialização"))
        st = QFormLayout()
        self.headless = QComboBox()
        for key, label in (("global", "Usar o padrão geral"), ("nao", "Com janela"), ("sim", "Sem janela (economiza recursos)")):
            self.headless.addItem(label, key)
        self.headless.setCurrentIndex(max(0, self.headless.findData(self.opt.headless)))
        st.addRow("Janela", self.headless)
        self.gpu = QComboBox()
        for key, label in GPU_MODES:
            self.gpu.addItem(label, key)
        self.gpu.setCurrentIndex(max(0, self.gpu.findData(self.opt.gpu_mode)))
        st.addRow("Renderização", self.gpu)
        self.extra = QLineEdit(self.opt.extra_args)
        self.extra.setPlaceholderText("Opcional, ex.: -dns-server 8.8.8.8")
        st.addRow("Argumentos extras", self.extra)
        self.quick = QCheckBox("Inicialização rápida (quick boot)")
        self.quick.setChecked(self.opt.quickboot)
        st.addRow("", self.quick)
        st.addRow("", muted("Desligado (recomendado): o Android desliga e liga por completo e todos os dados ficam "
                            "no disco do celular. Ligado: religa em segundos, mas se o estado salvo ficar "
                            "incompatível (ex.: alternar com/sem janela) o emulador pode voltar a um estado anterior "
                            "e perder alterações recentes."))
        self.body.addLayout(st)

        self.running = running
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Salvar")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        self.body.addLayout(button_row(cancel, save))

    def _save(self):
        s = self.manager.settings
        self.opt.display_name = self.display.text().strip()
        self.opt.headless = self.headless.currentData()
        self.opt.gpu_mode = self.gpu.currentData()
        self.opt.extra_args = self.extra.text().strip()
        if self.quick.isChecked() and not self.opt.quickboot and not confirm(
            self, "Inicialização rápida",
            "Com o quick boot, alterações feitas pouco antes de desligar podem ser perdidas se o estado salvo "
            "ficar incompatível. Ativar mesmo assim?", "Ativar", danger=True,
        ):
            return
        self.opt.quickboot = self.quick.isChecked()
        self.manager.store.save()

        updates = {"avd.ini.displayname": s.display_name(self.name)}
        if not self.running:
            if bool(self.manager.scan_processes().get(self.name)):
                error(self, "Configurações", "O celular foi ligado enquanto a janela estava aberta. Desligue-o e tente de novo.")
                return
            w, h, d = self.res.values()
            new_gb = self.storage.value()
            cur_gb = max(1, round(self.info.storage_bytes / 1024**3)) if self.info.storage_bytes else 0
            if cur_gb and new_gb > cur_gb and not confirm(
                self, "Aumentar armazenamento",
                f"Aumentar o armazenamento de {cur_gb} GB para {new_gb} GB.\n\n"
                "O espaço é ampliado na próxima inicialização. Recomenda-se criar um backup antes.",
                "Aumentar",
            ):
                return
            updates.update({
                "hw.ramSize": str(self.ram.value()),
                "hw.lcd.width": str(w), "hw.lcd.height": str(h), "hw.lcd.density": str(d),
                "hw.cpu.ncore": str(self.cores.value()),
            })
            if new_gb != cur_gb:
                updates["disk.dataPartition.size"] = f"{new_gb}G"
            try:
                self.manager.avds.apply_settings(self.name, updates)
            except (AvdError, OSError) as exc:
                error(self, "Configurações", str(exc))
                return
        self.accept()
