"""Configurações gerais do gerenciador."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from config.settings import phone_names
from emulators.avd import default_avd_home
from services import sdk as sdk_service
from ui.common import BaseDialog, button_row, confirm, error, muted, section
from ui.create_dialog import ResolutionPicker
from ui.phone_settings_dialog import GPU_MODES
from ui.workers import run_task
from utils import autostart
from utils.proc import run

IMAGE_SUGGESTIONS = [
    "system-images;android-36;google_apis_playstore;x86_64",
    "system-images;android-35;google_apis_playstore;x86_64",
    "system-images;android-35;google_apis;x86_64",
    "system-images;android-34;google_apis_playstore;x86_64",
    "system-images;android-33;google_apis_playstore;x86_64",
    "system-images;android-30;google_apis_playstore;x86_64",
]


class PathField(QWidget):
    def __init__(self, value: str, placeholder: str = "", folder: bool = False, file_filter: str = ""):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(value)
        self.edit.setPlaceholderText(placeholder)
        b = QPushButton("…")
        b.setFixedWidth(36)
        b.clicked.connect(self._browse)
        lay.addWidget(self.edit, 1)
        lay.addWidget(b)
        self.folder, self.filter = folder, file_filter

    def _browse(self):
        start = self.edit.text() or self.edit.placeholderText() or str(Path.home())
        if self.folder:
            p = QFileDialog.getExistingDirectory(self, "Escolher pasta", start)
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Escolher arquivo", start, self.filter)
        if p:
            self.edit.setText(str(Path(p)))

    def text(self) -> str:
        return self.edit.text().strip()


class SettingsDialog(BaseDialog):
    def __init__(self, parent, manager):
        super().__init__(parent, "Configurações", 720)
        self.manager = manager
        s = manager.settings
        p = manager.paths
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs)

        # ---------------------------------------------------------- SDK
        t = QWidget(); v = QVBoxLayout(t)
        f = QFormLayout()
        self.sdk = PathField(s.sdk_path, p.sdk or "detectar automaticamente", folder=True)
        self.emu = PathField(s.emulator_path, p.emulator or "automático", file_filter="emulator.exe")
        self.adb = PathField(s.adb_path, p.adb or "automático", file_filter="adb.exe")
        self.avdm = PathField(s.avdmanager_path, p.avdmanager or "automático", file_filter="avdmanager.bat")
        f.addRow("Android SDK", self.sdk)
        f.addRow("Android Emulator", self.emu)
        f.addRow("ADB", self.adb)
        f.addRow("avdmanager", self.avdm)
        v.addLayout(f)
        v.addWidget(muted("Deixe em branco para usar a detecção automática (ANDROID_HOME ou %LOCALAPPDATA%\\Android\\Sdk)."))
        self.sdk_status = QLabel("")
        self.sdk_status.setWordWrap(True)
        v.addWidget(self.sdk_status)
        b_deps = QPushButton("Instalar / verificar dependências…")
        b_deps.clicked.connect(self._open_deps)
        v.addWidget(b_deps)
        self._refresh_sdk_status()

        v.addWidget(section("Versões do Android instaladas"))
        self.images = QListWidget()
        self.images.setMaximumHeight(110)
        for img in sdk_service.list_system_images(p.sdk):
            self.images.addItem(img.label)
        if self.images.count() == 0:
            self.images.addItem("Nenhuma imagem do sistema instalada")
        v.addWidget(self.images)
        row = QHBoxLayout()
        self.pkg = QComboBox(); self.pkg.setEditable(True); self.pkg.addItems(IMAGE_SUGGESTIONS)
        b_inst = QPushButton("Baixar e instalar")
        b_inst.clicked.connect(self._install_image)
        row.addWidget(self.pkg, 1); row.addWidget(b_inst)
        v.addLayout(row)
        v.addWidget(muted("Imagens 'google_apis_playstore' trazem a Play Store. O download usa o sdkmanager oficial "
                          "e pode ter vários GB."))
        self.sdk_log = QPlainTextEdit(); self.sdk_log.setReadOnly(True); self.sdk_log.setMaximumHeight(90); self.sdk_log.hide()
        v.addWidget(self.sdk_log)
        v.addStretch(1)
        self.tabs.addTab(t, "Android SDK")

        # ---------------------------------------------------------- novos celulares
        t = QWidget(); v = QVBoxLayout(t)
        d = s.defaults
        f = QFormLayout()
        self.d_image = QComboBox()
        for img in sdk_service.list_system_images(p.sdk):
            self.d_image.addItem(img.label, img.package)
        i = self.d_image.findData(d.system_image)
        if i >= 0:
            self.d_image.setCurrentIndex(i)
        self.d_profile = QLineEdit(d.device_profile)
        self.d_ram = QSpinBox(); self.d_ram.setRange(1024, 16384); self.d_ram.setSingleStep(512); self.d_ram.setSuffix(" MB"); self.d_ram.setValue(d.ram_mb)
        self.d_storage = QSpinBox(); self.d_storage.setRange(2, 256); self.d_storage.setSuffix(" GB"); self.d_storage.setValue(d.storage_gb)
        self.d_res = ResolutionPicker(d.lcd_width, d.lcd_height, d.lcd_density)
        self.d_cores = QSpinBox(); self.d_cores.setRange(1, 8); self.d_cores.setValue(d.cpu_cores)
        f.addRow("Versão do Android", self.d_image)
        f.addRow("Modelo (perfil)", self.d_profile)
        f.addRow("Memória RAM", self.d_ram)
        f.addRow("Armazenamento", self.d_storage)
        f.addRow("Tela", self.d_res)
        f.addRow("Núcleos de CPU", self.d_cores)
        v.addLayout(f)
        v.addWidget(muted("Valores usados como ponto de partida ao criar novos celulares. Cada celular pode ter "
                          "configurações próprias depois (botão Ajustes no card)."))
        v.addStretch(1)
        self.tabs.addTab(t, "Novos celulares")

        # ---------------------------------------------------------- desempenho
        t = QWidget(); v = QVBoxLayout(t)
        f = QFormLayout()
        self.max_run = QSpinBox(); self.max_run.setRange(1, 12); self.max_run.setValue(s.max_running)
        f.addRow("Máximo de emuladores ligados ao mesmo tempo", self.max_run)
        self.ram_alert = QSpinBox(); self.ram_alert.setRange(50, 98); self.ram_alert.setSuffix(" %"); self.ram_alert.setValue(s.ram_alert_percent)
        f.addRow("Alertar quando o uso de RAM passar de", self.ram_alert)
        self.gpu = QComboBox()
        for key, label in GPU_MODES[1:]:
            self.gpu.addItem(label, key)
        self.gpu.setCurrentIndex(max(0, self.gpu.findData(s.gpu_mode)))
        f.addRow("Renderização gráfica", self.gpu)
        v.addLayout(f)
        self.headless = QCheckBox("Iniciar sem janela por padrão (economiza memória e CPU)")
        self.headless.setChecked(s.headless_default)
        self.no_anim = QCheckBox("Pular animação de inicialização do Android")
        self.no_anim.setChecked(s.no_boot_anim)
        self.no_audio = QCheckBox("Desativar áudio dos emuladores")
        self.no_audio.setChecked(s.no_audio)
        for w in (self.headless, self.no_anim, self.no_audio):
            v.addWidget(w)
        ok, msg = getattr(manager, "accel", None) or (
            sdk_service.accel_check(p.emulator) if p.emulator else (False, "emulador não encontrado"))
        v.addWidget(section("Aceleração de hardware"))
        v.addWidget(QLabel(("✔ " if ok else "✖ ") + msg))
        if not ok:
            v.addWidget(muted("Ative 'Plataforma do Hipervisor do Windows' (WHPX) nos Recursos do Windows para "
                              "os emuladores ficarem rápidos."))
        v.addStretch(1)
        self.tabs.addTab(t, "Desempenho")

        # ---------------------------------------------------------- inicialização
        t = QWidget(); v = QVBoxLayout(t)
        self.with_windows = QCheckBox("Abrir o gerenciador quando o Windows iniciar")
        self.with_windows.setChecked(autostart.is_enabled())
        v.addWidget(self.with_windows)
        v.addWidget(section("Ligar automaticamente ao abrir o gerenciador"))
        v.addWidget(muted("Os celulares marcados são ligados um de cada vez, respeitando o limite de emuladores simultâneos."))
        g = QGridLayout()
        self.auto_checks = {}
        for i, name in enumerate(phone_names()):
            cb = QCheckBox(s.display_name(name))
            cb.setChecked(name in s.autostart_phones)
            cb.setEnabled(manager.avds.read(name).exists or name in s.autostart_phones)
            g.addWidget(cb, i // 4, i % 4)
            self.auto_checks[name] = cb
        v.addLayout(g)
        v.addStretch(1)
        self.tabs.addTab(t, "Inicialização")

        # ---------------------------------------------------------- pastas
        t = QWidget(); v = QVBoxLayout(t)
        f = QFormLayout()
        self.avd_home = PathField(s.avd_home, str(default_avd_home()), folder=True)
        self.backup_dir = PathField(s.backup_dir, "", folder=True)
        f.addRow("Pasta dos celulares (AVDs)", self.avd_home)
        f.addRow("Pasta de backups", self.backup_dir)
        v.addLayout(f)
        v.addWidget(muted("As configurações do gerenciador ficam separadas, em %APPDATA%\\AndroidEmulatorManager. "
                          "Mudar a pasta dos celulares NÃO move os existentes: eles deixam de aparecer até você voltar "
                          "a pasta original."))
        v.addStretch(1)
        self.tabs.addTab(t, "Pastas")

        cancel = QPushButton("Cancelar"); cancel.clicked.connect(self.reject)
        save = QPushButton("Salvar"); save.setObjectName("primary"); save.clicked.connect(self._save)
        self.body.addLayout(button_row(cancel, save))

    # ------------------------------------------------------------------
    def _refresh_sdk_status(self):
        problems = self.manager.paths.problems()
        if problems:
            self.sdk_status.setText("✖ " + "\n✖ ".join(problems))
            self.sdk_status.setStyleSheet("color:#ff8f97;")
        else:
            self.sdk_status.setText("✔ Android SDK, Emulator, ADB e avdmanager encontrados.")
            self.sdk_status.setStyleSheet("color:#4ade80;")

    def _open_deps(self):
        from ui.deps_dialog import DepsDialog

        DepsDialog(self, self.manager).exec()
        self._refresh_sdk_status()

    def _install_image(self):
        pkg = self.pkg.currentText().strip()
        sdkm = self.manager.paths.sdkmanager
        if not sdkm:
            error(self, "Instalar imagem", "sdkmanager não encontrado (instale 'Android SDK Command-line Tools').")
            return
        if not pkg.startswith("system-images;"):
            error(self, "Instalar imagem", "Informe um pacote no formato system-images;android-XX;tipo;x86_64")
            return
        if not confirm(self, "Instalar imagem", f"Baixar e instalar:\n{pkg}\n\nO download pode ter vários GB.", "Baixar"):
            return
        self.sdk_log.show()
        self.sdk_log.setPlainText(f"Baixando {pkg}… isso pode levar vários minutos.")

        def work():
            res = run([sdkm, "--install", pkg], timeout=3600, env=self.manager.env())
            return res.returncode, (res.stdout + res.stderr)[-3000:]

        def done(r):
            code, out = r
            if code == 0:
                self.sdk_log.setPlainText("✔ Imagem instalada. Reabra esta janela para vê-la na lista.\n\n" + out[-800:])
            elif "licen" in out.lower():
                self.sdk_log.setPlainText("✖ É preciso aceitar a licença da imagem. Abra um terminal e execute:\n"
                                          f"\"{sdkm}\" --licenses\n\n" + out[-800:])
            else:
                self.sdk_log.setPlainText("✖ Falha na instalação:\n" + out)

        run_task(work, on_done=done, on_error=lambda e: self.sdk_log.setPlainText(f"✖ {e}"))

    def _save(self):
        s = self.manager.settings
        old_home = s.avd_home
        s.sdk_path = self.sdk.text()
        s.emulator_path = self.emu.text()
        s.adb_path = self.adb.text()
        s.avdmanager_path = self.avdm.text()
        s.avd_home = self.avd_home.text()
        s.backup_dir = self.backup_dir.text() or s.backup_dir
        d = s.defaults
        if self.d_image.currentData():
            d.system_image = self.d_image.currentData()
        d.device_profile = self.d_profile.text().strip() or "pixel_6"
        d.ram_mb = self.d_ram.value()
        d.storage_gb = self.d_storage.value()
        d.lcd_width, d.lcd_height, d.lcd_density = self.d_res.values()
        d.cpu_cores = self.d_cores.value()
        s.max_running = self.max_run.value()
        s.ram_alert_percent = self.ram_alert.value()
        s.gpu_mode = self.gpu.currentData()
        s.headless_default = self.headless.isChecked()
        s.no_boot_anim = self.no_anim.isChecked()
        s.no_audio = self.no_audio.isChecked()
        s.autostart_phones = [n for n, c in self.auto_checks.items() if c.isChecked()]
        if old_home != s.avd_home and self.manager.scan_processes():
            error(self, "Configurações", "Desligue todos os emuladores antes de mudar a pasta dos celulares.")
            s.avd_home = old_home
            return
        try:
            if self.with_windows.isChecked() != autostart.is_enabled():
                autostart.set_enabled(self.with_windows.isChecked())
            s.autostart_with_windows = self.with_windows.isChecked()
        except OSError as exc:
            error(self, "Configurações", f"Não foi possível alterar a inicialização com o Windows: {exc}")
        self.manager.store.save()
        self.manager.reload_paths()
        self.accept()
