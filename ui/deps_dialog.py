"""Assistente de instalação das dependências (Java, Android SDK, Emulator, ADB, imagem, WHPX)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout,
)

from services import deps
from ui import theme
from ui.common import BaseDialog, confirm, error, info, muted, section
from ui.icons import icon
from ui.workers import run_task

IMAGES = [
    ("Android 10 com Play Store (mais leve — recomendado para muitos celulares)",
     "system-images;android-29;google_apis_playstore;x86_64"),
    ("Android 11 com Play Store", "system-images;android-30;google_apis_playstore;x86_64"),
    ("Android 13 com Play Store", "system-images;android-33;google_apis_playstore;x86_64"),
    ("Android 14 com Play Store", "system-images;android-34;google_apis_playstore;x86_64"),
    ("Android 15 com Play Store", "system-images;android-35;google_apis_playstore;x86_64"),
    ("Android 16 com Play Store", "system-images;android-36;google_apis_playstore;x86_64"),
    ("Android 15 sem Play Store (Google APIs)", "system-images;android-35;google_apis;x86_64"),
]
SDK_TERMS_URL = "https://developer.android.com/studio/terms"


class DepsDialog(BaseDialog):
    def __init__(self, parent, manager):
        super().__init__(parent, "Instalar dependências", 720)
        self.manager = manager
        self.task = None
        self.rows: dict[str, tuple[QLabel, QLabel, QPushButton]] = {}
        self.status: dict[str, deps.DepStatus] = {}

        self.body.addWidget(section("Dependências do Android Emulator Manager"))
        self.body.addWidget(muted(
            "O gerenciador usa as ferramentas oficiais do Android. O que faltar pode ser instalado daqui, "
            "baixando direto das fontes oficiais (Google e Eclipse Adoptium). Não é preciso instalar o Android Studio."))

        panel = QFrame()
        panel.setObjectName("panel")
        grid = QGridLayout(panel)
        grid.setContentsMargins(14, 10, 14, 10)
        grid.setVerticalSpacing(10)
        grid.setHorizontalSpacing(12)
        for i, key in enumerate(["java", "cmdline", "platform-tools", "emulator", "image", "accel"]):
            ic = QLabel()
            ic.setFixedWidth(22)
            box = QVBoxLayout()
            box.setSpacing(2)
            title = QLabel("…")
            title.setStyleSheet("font-weight:600;")
            detail = QLabel("")
            detail.setObjectName("muted")
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            box.addWidget(title)
            box.addWidget(detail)
            btn = QPushButton("Ativar" if key == "accel" else "Instalar")
            btn.clicked.connect(lambda _=False, k=key: self._install([k]))
            grid.addWidget(ic, i, 0, Qt.AlignmentFlag.AlignTop)
            grid.addLayout(box, i, 1)
            grid.addWidget(btn, i, 2, Qt.AlignmentFlag.AlignTop)
            self.rows[key] = (ic, title, detail, btn)
        grid.setColumnStretch(1, 1)
        self.body.addWidget(panel)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("Versão do Android a instalar:"))
        self.image = QComboBox()
        for label, pkg in IMAGES:
            self.image.addItem(label, pkg)
        opts.addWidget(self.image, 1)
        self.body.addLayout(opts)

        self.sdk_dir = Path(manager.paths.sdk) if manager.paths.sdk else deps.default_sdk_dir()
        self.body.addWidget(muted(f"Pasta do Android SDK: {self.sdk_dir}"))

        lic = QHBoxLayout()
        self.accept = QCheckBox("Li e aceito os termos de licença do Android SDK")
        b_lic = QPushButton("Ver licenças")
        b_lic.clicked.connect(self._show_licenses)
        lic.addWidget(self.accept, 1)
        lic.addWidget(b_lic)
        self.body.addLayout(lic)
        self.body.addWidget(muted(f"Termos: {SDK_TERMS_URL}. O Java (Eclipse Temurin) é distribuído sob a licença GPLv2 com Classpath Exception."))

        prow = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.hide()
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.hide()
        self.btn_cancel.clicked.connect(self._cancel)
        prow.addWidget(self.progress, 1)
        prow.addWidget(self.btn_cancel)
        self.body.addLayout(prow)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        self.lbl.setObjectName("muted")
        self.body.addWidget(self.lbl)

        bottom = QHBoxLayout()
        self.btn_close = QPushButton("Fechar")
        self.btn_close.clicked.connect(self.reject)
        self.btn_all = QPushButton("Instalar tudo que falta")
        self.btn_all.setObjectName("primary")
        self.btn_all.setIcon(icon("download", "white", 16))
        self.btn_all.clicked.connect(lambda: self._install(None))
        bottom.addStretch(1)
        bottom.addWidget(self.btn_close)
        bottom.addWidget(self.btn_all)
        self.body.addLayout(bottom)

        self._refresh()

    # ------------------------------------------------------------------
    def _refresh(self):
        self.lbl.setText("Verificando…")

        def done(items):
            self.status = {d.key: d for d in items}
            for d in items:
                ic, title, detail, btn = self.rows[d.key]
                color = theme.GREEN if d.ok else theme.RED
                ic.setPixmap(icon("check" if d.ok else "error", color, 18).pixmap(18, 18))
                title.setText(d.title)
                detail.setText(d.detail)
                btn.setVisible(not d.ok)
            missing = [d for d in items if not d.ok]
            self.btn_all.setEnabled(bool(missing) and self.task is None)
            self.lbl.setText("✔ Tudo pronto." if not missing else f"Faltam {len(missing)} item(ns).")

        run_task(deps.check_all, self.manager, on_done=done,
                 on_error=lambda e: self.lbl.setText(f"Falha ao verificar: {e}"))

    def _show_licenses(self):
        sdkm = self.manager.paths.sdkmanager
        if not sdkm or not self.manager.java_home:
            info(self, "Licenças", "O texto completo das licenças aparece depois que o Java e o Command-line Tools "
                                   f"forem instalados. Os termos estão em:\n{SDK_TERMS_URL}")
            return
        self.lbl.setText("Carregando o texto das licenças…")

        def show(text):
            self.lbl.setText("")
            dlg = BaseDialog(self, "Licenças do Android SDK", 720)
            t = QPlainTextEdit(text)
            t.setReadOnly(True)
            t.setMinimumHeight(420)
            dlg.body.addWidget(t)
            b = QPushButton("Fechar")
            b.clicked.connect(dlg.accept)
            dlg.body.addWidget(b)
            dlg.exec()

        run_task(deps.license_text, sdkm, self.sdk_dir, self.manager.java_home, on_done=show,
                 on_error=lambda e: self.lbl.setText(str(e)))

    def _busy(self, busy: bool):
        self.btn_all.setEnabled(not busy)
        self.btn_close.setEnabled(not busy)
        for _ic, _t, _d, b in self.rows.values():
            b.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.btn_cancel.setVisible(busy)
        self.btn_cancel.setEnabled(True)

    def _cancel(self):
        if self.task:
            self.task.cancel()
            self.btn_cancel.setEnabled(False)
            self.lbl.setText("Cancelando…")

    def reject(self):
        if self.task:
            return
        super().reject()

    def _install(self, keys: list[str] | None):
        missing = [k for k, d in self.status.items() if not d.ok]
        keys = [k for k in (keys or missing) if k in missing]
        if not keys:
            return
        sdk_keys = [k for k in keys if k in ("platform-tools", "emulator", "image", "cmdline")]
        if sdk_keys and not self.accept.isChecked():
            error(self, "Licenças", "Para instalar componentes do Android SDK, marque que você leu e aceita os termos "
                                    "de licença do Android SDK.")
            return
        install_keys = [k for k in keys if k != "accel"]
        want_accel = "accel" in keys
        # a imagem e o emulador exigem o sdkmanager, que exige Java
        if any(k in install_keys for k in ("platform-tools", "emulator", "image")):
            for dep in ("cmdline", "java"):
                if dep in missing and dep not in install_keys:
                    install_keys.insert(0, dep)
        if "cmdline" in install_keys and "java" in missing and "java" not in install_keys:
            install_keys.insert(0, "java")
        order = ["java", "cmdline", "platform-tools", "emulator", "image"]
        install_keys = [k for k in order if k in install_keys]

        if install_keys:
            self._run_install(install_keys, want_accel)
        elif want_accel:
            self._enable_accel()

    def _run_install(self, keys: list[str], then_accel: bool):
        m = self.manager
        sdk = self.sdk_dir
        image = self.image.currentData()
        java_home = m.java_home

        def work(progress, cancel):
            def prog(text, pct):
                progress((text, pct))

            result = {"java_home": java_home}
            jh = java_home
            if "java" in keys:
                jh = deps.install_java(prog, cancel)
                result["java_home"] = jh
            sdk.mkdir(parents=True, exist_ok=True)
            if "cmdline" in keys:
                deps.install_cmdline_tools(sdk, prog, cancel)
            pkgs = []
            if "platform-tools" in keys:
                pkgs.append("platform-tools")
            if "emulator" in keys:
                pkgs.append("emulator")
            if "image" in keys:
                pkgs.append(image)
            if pkgs:
                sdkm = sdk / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat"
                if not sdkm.is_file():
                    sdkm = Path(m.paths.sdkmanager) if m.paths.sdkmanager else sdkm
                if not sdkm.is_file():
                    raise deps.DepsError("sdkmanager não encontrado. Instale o Command-line Tools primeiro.")
                prog("Registrando o aceite das licenças do Android SDK…", -1)
                deps.accept_licenses(str(sdkm), sdk, jh, prog, cancel)
                deps.install_packages(str(sdkm), sdk, jh, pkgs, prog, cancel)
            return result

        def on_prog(v):
            text, pct = v
            self.lbl.setText(text)
            if pct < 0:
                self.progress.setRange(0, 0)
            else:
                self.progress.setRange(0, 100)
                self.progress.setValue(pct)

        def done(result):
            self.task = None
            self._busy(False)
            s = m.settings
            if result.get("java_home"):
                s.java_home = result["java_home"]
            if not s.sdk_path:
                s.sdk_path = str(sdk)
            m.store.save()
            m.reload_paths()
            m.accel = None
            self._refresh()
            self.lbl.setText("✔ Instalação concluída.")
            if then_accel:
                self._enable_accel()

        def failed(exc):
            self.task = None
            self._busy(False)
            self._refresh()
            if isinstance(exc, deps.Cancelled):
                self.lbl.setText("Instalação cancelada.")
            else:
                text = str(exc)
                first, _, rest = text.partition("\n")
                error(self, "Instalar dependências", first, rest)

        self._busy(True)
        self.progress.setRange(0, 0)
        self.task = run_task(work, with_progress=True, with_cancel=True, on_progress=on_prog,
                             on_done=done, on_error=failed)

    def _enable_accel(self):
        if not confirm(self, "Aceleração de hardware",
                       "Vai ser ativado o recurso do Windows 'Plataforma do Hipervisor do Windows' (WHPX), que deixa os "
                       "emuladores muito mais rápidos.\n\nO Windows vai pedir permissão de administrador e depois será "
                       "preciso reiniciar o computador. A virtualização (SVM/VT-x) também precisa estar ativa na BIOS.",
                       "Ativar"):
            return
        if deps.enable_whpx():
            info(self, "Aceleração de hardware", "Siga a janela do PowerShell que abriu. Quando terminar, reinicie o "
                                                 "computador e abra o gerenciador de novo.")
        else:
            error(self, "Aceleração de hardware", "A ativação foi cancelada ou não pôde ser iniciada.")
