"""Janela principal: painel com os 12 celulares."""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QProgressBar, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from config.settings import APP_TITLE, APP_VERSION, phone_names
from emulators.manager import MISSING, OFF, ON, NotResponding, Snapshot
from services import sdk as sdk_service
from ui import common
from ui.apk_dialog import ApkDialog
from ui.backup_dialog import BackupDialog
from ui.create_dialog import CreateDialog
from ui.deps_dialog import DepsDialog
from ui.device_card import DeviceCard
from ui.files_dialog import FilesDialog
from ui.icons import app_icon, icon
from ui.phone_settings_dialog import PhoneSettingsDialog
from ui.settings_dialog import SettingsDialog
from ui.workers import run_task
from utils.system import human_size

log = logging.getLogger(__name__)
POLL_MS = 2500
CARD_MIN_W = 300


class MainWindow(QMainWindow):
    def __init__(self, store, manager):
        super().__init__()
        self.store = store
        self.manager = manager
        self.snapshot: Snapshot | None = None
        self.last_backups: dict = {}
        self.local_busy: dict[str, str] = {}
        self._polling = False
        self._autostart_done = False
        self._force_close = False
        self._deps_prompted = False
        self._columns = 0

        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(app_icon())
        self.resize(1360, 900)
        self.setMinimumSize(720, 560)

        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 18, 22, 10)
        root.setSpacing(12)

        # ---------------------------------------------------------- cabeçalho
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel(APP_TITLE)
        t.setObjectName("title")
        sub = QLabel("12 celulares Android independentes · Android Emulator + ADB oficiais")
        sub.setObjectName("subtitle")
        titles.addWidget(t)
        titles.addWidget(sub)
        header.addLayout(titles, 1)

        res = QFrame()
        res.setObjectName("panel")
        rl = QGridLayout(res)
        rl.setContentsMargins(14, 10, 14, 10)
        rl.setHorizontalSpacing(14)
        rl.setVerticalSpacing(4)
        k1 = QLabel("Memória do PC"); k1.setObjectName("infoKey")
        self.ram_bar = QProgressBar(); self.ram_bar.setObjectName("ram"); self.ram_bar.setFixedWidth(180)
        self.ram_bar.setTextVisible(False); self.ram_bar.setFixedHeight(8)
        self.ram_text = QLabel("—"); self.ram_text.setObjectName("infoVal")
        k2 = QLabel("Em execução"); k2.setObjectName("infoKey")
        self.run_text = QLabel("—"); self.run_text.setObjectName("infoVal")
        k3 = QLabel("Aceleração"); k3.setObjectName("infoKey")
        self.accel_text = QLabel("verificando…"); self.accel_text.setObjectName("infoVal")
        rl.addWidget(k1, 0, 0); rl.addWidget(self.ram_bar, 0, 1); rl.addWidget(self.ram_text, 0, 2)
        rl.addWidget(k2, 1, 0); rl.addWidget(self.run_text, 1, 1, 1, 2)
        rl.addWidget(k3, 2, 0); rl.addWidget(self.accel_text, 2, 1, 1, 2)
        header.addWidget(res)
        root.addLayout(header)

        self.banner = common.Banner()
        self.banner.action_clicked.connect(self._banner_action)
        self._banner_kind = ""
        root.addWidget(self.banner)

        # ---------------------------------------------------------- barra de ações
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_create = self._tool("Criar celulares", "add", self._create, primary=True)
        self.btn_start_sel = self._tool("Iniciar selecionados", "play", self._start_selected)
        self.btn_stop_sel = self._tool("Desligar selecionados", "power", self._stop_selected)
        self.btn_apk = self._tool("Instalar APK", "apk", lambda: self._apk(None))
        self.btn_arrange = self._tool("Organizar janelas", "grid", self._arrange)
        self.btn_arrange.setToolTip("Distribui na tela, em grade, as janelas de todos os celulares ligados")
        self.btn_select = self._tool("Selecionar todos", "selectall", self._toggle_select)
        self.btn_settings = self._tool("Configurações", "settings", self._settings)
        for b in (self.btn_create, self.btn_start_sel, self.btn_stop_sel, self.btn_apk, self.btn_arrange,
                  self.btn_select):
            bar.addWidget(b)
        self.sel_label = QLabel("")
        self.sel_label.setObjectName("muted")
        bar.addWidget(self.sel_label)
        bar.addStretch(1)
        bar.addWidget(self.btn_settings)
        root.addLayout(bar)

        # ---------------------------------------------------------- grade de cards
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        self.grid = QGridLayout(container)
        self.grid.setContentsMargins(0, 0, 4, 0)
        self.grid.setSpacing(14)
        self.cards: dict[str, DeviceCard] = {}
        for name in phone_names():
            c = DeviceCard(name)
            c.action.connect(self._card_action)
            c.selection_changed.connect(self._update_selection)
            self.cards[name] = c
        self.scroll.setWidget(container)
        root.addWidget(self.scroll, 1)
        self._relayout(force=True)

        self.statusBar().showMessage(f"Versão {APP_VERSION} · iniciando…")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(POLL_MS)
        QTimer.singleShot(50, self._poll)
        run_task(sdk_service.accel_check, manager.paths.emulator, on_done=self._accel_done)
        self._update_selection()

    # ------------------------------------------------------------------ util
    def _tool(self, text, ic, slot, primary=False):
        b = QPushButton(text)
        b.setIcon(icon(ic, "white" if primary else "#c9cfdb", 16))
        b.setIconSize(QSize(16, 16))
        if primary:
            b.setObjectName("primary")
        b.clicked.connect(slot)
        return b

    def _name(self, name):
        return self.manager.settings.display_name(name)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._relayout)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, lambda: self._relayout(force=True))

    def _relayout(self, force=False):
        width = self.scroll.width() - 16
        cols = max(1, min(4, (width + 14) // (CARD_MIN_W + 14)))
        if cols == self._columns and not force:
            return
        self._columns = cols
        for c in self.cards.values():
            self.grid.removeWidget(c)
        for i, name in enumerate(phone_names()):
            self.grid.addWidget(self.cards[name], i // cols, i % cols, Qt.AlignmentFlag.AlignTop)
        for col in range(4):
            self.grid.setColumnStretch(col, 1 if col < cols else 0)
        self.grid.setRowStretch(12, 1)

    def _accel_done(self, r):
        ok, msg = r
        self.manager.accel = r
        self.accel_text.setText(("WHPX ativa" if "WHPX" in msg else "ativa") if ok else "indisponível")
        self.accel_text.setToolTip(msg)
        self.accel_text.setStyleSheet("color:#4ade80;" if ok else "color:#ff8f97;")

    # ------------------------------------------------------------------ atualização de estado
    def _poll(self):
        if self._polling:
            return
        self._polling = True
        m = self.manager

        def work():
            snap = m.snapshot()
            backups = {n: m.backups.last_backup(n) for n in phone_names()}
            return snap, backups

        def done(r):
            self._polling = False
            self.snapshot, self.last_backups = r
            self._apply()

        def failed(exc):
            self._polling = False
            log.exception("Falha ao atualizar estado", exc_info=exc)
            self.statusBar().showMessage(f"Falha ao ler o estado dos emuladores: {exc}")

        run_task(work, on_done=done, on_error=failed)

    def _apply(self):
        snap = self.snapshot
        s = self.manager.settings
        for name, card in self.cards.items():
            st = snap.phones[name]
            busy = self.local_busy.get(name, "")
            if busy and st.busy_text:
                busy = ""  # o gerenciador já informa o estado
            card.update_state(st, self._name(name), self.last_backups.get(name), busy)

        mem = snap.memory
        self.ram_bar.setValue(int(mem.percent))
        level = "crit" if mem.percent >= 95 else "warn" if mem.percent >= s.ram_alert_percent else "ok"
        if self.ram_bar.property("level") != level:
            self.ram_bar.setProperty("level", level)
            self.ram_bar.style().unpolish(self.ram_bar)
            self.ram_bar.style().polish(self.ram_bar)
        self.ram_text.setText(f"{human_size(mem.total - mem.available)} de {human_size(mem.total)}")
        running = [n for n, st in snap.phones.items() if st.running]
        total_running = len(running) + len(snap.others_running)
        extra = f" (+{len(snap.others_running)} outro{'s' if len(snap.others_running) > 1 else ''})" if snap.others_running else ""
        self.run_text.setText(f"{len(running)} de {s.max_running} permitidos{extra}")
        self.run_text.setStyleSheet("color:#f5b544;" if total_running >= s.max_running else "")

        # avisos, do mais grave para o menos grave
        problems = self.manager.paths.problems()
        if not self.manager.java_home:
            problems.append("Java (JDK 17+) não encontrado — necessário para criar celulares.")
        if problems:
            self._banner("error", "Faltam dependências: " + " ".join(problems), "Instalar dependências", "deps")
            if not self._deps_prompted:
                self._deps_prompted = True
                QTimer.singleShot(300, self._deps)
        elif snap.adb_error:
            self._banner("warn", f"Falha de comunicação com o ADB: {snap.adb_error}. Tentando novamente…", "", "adb")
        elif mem.percent >= s.ram_alert_percent:
            self._banner("warn", f"A memória do computador está em {mem.percent:.0f}%. Evite ligar mais celulares; "
                                 "desligue algum se o sistema ficar lento.", "", "ram")
        elif snap.others_running:
            self._banner("info", "Outros emuladores fora do gerenciador estão ligados ("
                         + ", ".join(snap.others_running) + ") e também contam no limite de simultâneos.", "", "others")
        else:
            self.banner.hide()
            self._banner_kind = ""

        on = sum(1 for st in snap.phones.values() if st.status == ON)
        created = sum(1 for st in snap.phones.values() if st.info and st.info.exists)
        self.statusBar().showMessage(
            f"{created} de 12 celulares criados · {on} ligado(s) · ADB: {self.manager.paths.adb or 'não encontrado'}"
        )
        self._update_selection()

        if not self._autostart_done:
            self._autostart_done = True
            self._autostart()

    def _banner(self, kind, text, action, key):
        self._banner_kind = key
        self.banner.show_message(kind, text, action)

    def _banner_action(self):
        if self._banner_kind == "deps":
            self._deps()

    def _deps(self):
        DepsDialog(self, self.manager).exec()
        self._poll()

    # ------------------------------------------------------------------ seleção
    def _selected(self) -> list[str]:
        return [n for n, c in self.cards.items() if c.is_selected()]

    def _update_selection(self):
        sel = self._selected()
        self.sel_label.setText(f"{len(sel)} selecionado(s)" if sel else "")
        snap = self.snapshot
        if snap:
            self.btn_start_sel.setEnabled(any(snap.phones[n].status == OFF for n in sel))
            self.btn_stop_sel.setEnabled(any(snap.phones[n].running for n in sel))
        else:
            self.btn_start_sel.setEnabled(False)
            self.btn_stop_sel.setEnabled(False)
        existing = [c for c in self.cards.values() if c.check.isEnabled()]
        all_sel = existing and all(c.is_selected() for c in existing)
        self.btn_select.setText("Limpar seleção" if all_sel else "Selecionar todos")

    def _toggle_select(self):
        existing = [c for c in self.cards.values() if c.check.isEnabled()]
        target = not all(c.is_selected() for c in existing)
        for c in existing:
            c.set_selected(target)

    # ------------------------------------------------------------------ ações dos cards
    def _card_action(self, action: str, name: str):
        handlers = {
            "start": self._start, "stop": self._stop, "restart": self._restart, "window": self._window,
            "apk": lambda n: self._apk([n]), "settings": self._phone_settings, "files": self._files,
            "backup": self._backup, "create": lambda n: self._create([n]),
        }
        handlers[action](name)

    def _busy(self, name, text):
        if text:
            self.local_busy[name] = text
        else:
            self.local_busy.pop(name, None)
        if self.snapshot:
            self._apply()

    def _done_refresh(self, name, message=""):
        self._busy(name, "")
        if message:
            self.statusBar().showMessage(message, 6000)
        QTimer.singleShot(200, self._poll)

    def _total_running(self) -> int:
        snap = self.snapshot
        if not snap:
            return 0
        return sum(1 for st in snap.phones.values() if st.running) + len(snap.others_running)

    def _check_resources(self, names: list[str]) -> list[str] | None:
        """Aplica o limite de simultâneos e avisa se faltar memória. Retorna os nomes a iniciar."""
        s = self.manager.settings
        free_slots = s.max_running - self._total_running()
        if free_slots <= 0:
            common.warn(self, "Limite atingido",
                        f"Já há {self._total_running()} emulador(es) ligado(s), o limite configurado é {s.max_running}.\n\n"
                        "Desligue um celular ou aumente o limite em Configurações → Desempenho.")
            return None
        if len(names) > free_slots:
            if not common.confirm(self, "Limite de simultâneos",
                                  f"Só é possível ligar mais {free_slots} celular(es) agora (limite de {s.max_running}).\n\n"
                                  f"Ligar apenas: {', '.join(self._name(n) for n in names[:free_slots])}?", "Ligar esses"):
                return None
            names = names[:free_slots]
        self._mem_override = False
        from utils.system import memory

        free = memory().available
        need = sum(self.manager.estimated_bytes(n) for n in names)
        if free < need:
            fit, acc = 0, 0
            for n in names:
                acc += self.manager.estimated_bytes(n)
                if acc > free:
                    break
                fit += 1
            if len(names) > 1 and fit > 0:
                if not common.confirm(self, "Pouca memória livre",
                                      f"Memória livre: {human_size(free)}. Cada celular com Play Store usa cerca de "
                                      f"{human_size(self.manager.estimated_bytes(names[0]))}.\n\n"
                                      f"Cabem com segurança só {fit}: {', '.join(self._name(n) for n in names[:fit])}. "
                                      "Ligar esses?", "Ligar esses"):
                    return None
                return names[:fit]
            if not common.confirm(self, "Pouca memória livre",
                                  f"Memória livre: {human_size(free)}. Este celular precisa de cerca de "
                                  f"{human_size(need)}.\n\nO computador vai ficar lento (usando o disco como memória) "
                                  "e outros programas podem fechar. Ligar mesmo assim?", "Ligar mesmo assim", danger=True):
                return None
            self._mem_override = True
        return names

    def _start(self, name, headless=None):
        names = self._check_resources([name])
        if not names:
            return
        self._busy(name, "Iniciando…")
        run_task(self.manager.start, name, headless=headless, check_memory=not self._mem_override,
                 on_done=lambda _: self._done_refresh(name, f"{self._name(name)} iniciado. O Android está carregando…"),
                 on_error=lambda e: self._start_failed(name, e))

    def _start_failed(self, name, exc):
        self._done_refresh(name)
        text = str(exc)
        log.error("Falha ao iniciar %s: %s", name, text)
        first, _, rest = text.partition("\n\n")
        common.error(self, f"Iniciar {self._name(name)}", first, rest)

    def _start_selected(self):
        snap = self.snapshot
        names = [n for n in self._selected() if snap.phones[n].status == OFF]
        names = self._check_resources(names) if names else None
        if not names:
            return
        self._start_many(names)

    def _start_many(self, names: list[str], quiet: bool = False):
        for n in names:
            self._busy(n, "Na fila para iniciar…")
        m = self.manager

        def work(progress):
            errors = []
            for i, n in enumerate(names):
                progress(("start", n))
                try:
                    m.start(n)
                except Exception as exc:  # noqa: BLE001
                    errors.append((n, str(exc)))
                progress(("done", n))
                if i < len(names) - 1:
                    time.sleep(6)  # espaçamento para não sobrecarregar disco e CPU
            return errors

        def prog(v):
            kind, n = v
            self._busy(n, "Iniciando…" if kind == "start" else "")
            QTimer.singleShot(200, self._poll)

        def done(errors):
            for n in names:
                self.local_busy.pop(n, None)
            for n, e in errors:
                log.error("Falha ao iniciar %s: %s", n, e)
            self._poll()
            if errors and not quiet:
                common.error(self, "Iniciar celulares", "Alguns celulares não iniciaram.",
                             "\n\n".join(f"{self._name(n)}: {e}" for n, e in errors))
            elif errors:
                self.statusBar().showMessage("Falha ao iniciar: " + ", ".join(self._name(n) for n, _ in errors), 10000)

        run_task(work, with_progress=True, on_progress=prog, on_done=done)

    def _stop(self, name):
        self._busy(name, "Desligando…")
        run_task(self.manager.stop, name,
                 on_done=lambda _: self._done_refresh(name, f"{self._name(name)} desligado. Dados salvos."),
                 on_error=lambda e: self._stop_failed(name, e))

    def _stop_failed(self, name, exc):
        self._done_refresh(name)
        if isinstance(exc, NotResponding):
            if common.confirm(self, "O emulador não respondeu",
                              f"{self._name(name)} não respondeu ao pedido de desligamento.\n\n{exc}\n\n"
                              "Forçar o encerramento? Dados ainda não gravados pelo Android (dos últimos segundos) "
                              "podem ser perdidos. Se preferir, aguarde e tente desligar de novo.",
                              "Forçar encerramento", danger=True):
                self._busy(name, "Encerrando…")
                run_task(self.manager.force_stop, name,
                         on_done=lambda _: self._done_refresh(name, f"{self._name(name)} encerrado à força."),
                         on_error=lambda e: (self._done_refresh(name), common.error(self, "Encerrar", str(e))))
        else:
            common.error(self, f"Desligar {self._name(name)}", str(exc))

    def _stop_selected(self):
        names = [n for n in self._selected() if self.snapshot.phones[n].running]
        for n in names:
            self._stop(n)

    def _restart(self, name):
        self._busy(name, "Reiniciando…")
        run_task(self.manager.restart, name,
                 on_done=lambda _: self._done_refresh(name, f"{self._name(name)} reiniciado."),
                 on_error=lambda e: (self._done_refresh(name), common.error(self, f"Reiniciar {self._name(name)}", str(e))))

    def _window(self, name):
        if self.manager.focus_window(name):
            return
        st = self.snapshot.phones[name] if self.snapshot else None
        if st and st.status != ON:
            common.info(self, "Janela", "A janela do emulador ainda está abrindo. Tente de novo em alguns segundos.")
            return
        if common.confirm(self, "Celular sem janela",
                          f"{self._name(name)} foi ligado sem janela (modo econômico).\n\n"
                          "Para mostrar a tela é preciso desligá-lo e ligá-lo de novo com janela. Os dados são mantidos.",
                          "Religar com janela"):
            self._busy(name, "Religando com janela…")
            m = self.manager

            def work():
                m.stop(name)
                m.start(name, headless=False, check_limit=False)

            run_task(work, on_done=lambda _: self._done_refresh(name),
                     on_error=lambda e: self._stop_failed(name, e) if isinstance(e, NotResponding)
                     else self._start_failed(name, e))

    def _arrange(self):
        sel = [n for n in self._selected() if self.snapshot and self.snapshot.phones[n].running]
        count = self.manager.arrange_windows(sel or None)
        if count:
            self.statusBar().showMessage(f"{count} janela(s) organizada(s).", 5000)
        else:
            common.info(self, "Organizar janelas",
                        "Nenhum celular ligado com janela visível. Celulares ligados sem janela (modo econômico) "
                        "não aparecem na tela.")

    def _apk(self, names):
        ApkDialog(self, self.manager, self.snapshot, names).exec()

    def _phone_settings(self, name):
        if PhoneSettingsDialog(self, self.manager, name).exec():
            self._poll()

    def _files(self, name):
        st = self.snapshot.phones[name].status if self.snapshot else OFF
        FilesDialog(self, self.manager, name, st).exec()

    def _backup(self, name):
        BackupDialog(self, self.manager, name).exec()
        self._poll()

    def _create(self, names=None):
        if self.manager.paths.problems() or not self.manager.java_home:
            if common.confirm(self, "Criar celulares", "Faltam dependências para criar celulares (Android SDK e/ou Java).\n\n"
                              "Abrir o assistente de instalação?", "Instalar dependências"):
                self._deps()
            return
        CreateDialog(self, self.manager, names).exec()
        self._poll()

    def _settings(self):
        if SettingsDialog(self, self.manager).exec():
            self._poll()

    # ------------------------------------------------------------------ inicialização automática
    def _autostart(self):
        s = self.manager.settings
        snap = self.snapshot
        names = [n for n in s.autostart_phones if snap.phones.get(n) and snap.phones[n].status == OFF]
        if not names:
            return
        free = s.max_running - self._total_running()
        if free <= 0:
            self.statusBar().showMessage("Inicialização automática ignorada: limite de emuladores atingido.", 10000)
            return
        skipped = names[free:]
        names = names[:free]
        if skipped:
            self.statusBar().showMessage(
                "Limite de simultâneos: não foram ligados automaticamente " + ", ".join(self._name(n) for n in skipped), 15000)
        self._start_many(names, quiet=True)

    # ------------------------------------------------------------------ fechar
    def closeEvent(self, e: QCloseEvent):
        if self._force_close:
            e.accept()
            return
        running = [n for n, st in (self.snapshot.phones.items() if self.snapshot else []) if st.running]
        if not running:
            e.accept()
            return
        choice = common.choose(
            self, "Fechar o gerenciador",
            f"{len(running)} celular(es) ainda ligado(s): {', '.join(self._name(n) for n in running)}.\n\n"
            "Eles podem continuar ligados (você os verá aqui ao abrir o gerenciador de novo) "
            "ou ser desligados com segurança agora.",
            ["Deixar ligados e sair", "Desligar todos e sair", "Cancelar"], default=0)
        if choice == 0:
            e.accept()
        elif choice == 1:
            e.ignore()
            self._shutdown_all(running)
        else:
            e.ignore()

    def _shutdown_all(self, names):
        self.centralWidget().setEnabled(False)
        self.timer.stop()
        self.statusBar().showMessage("Desligando todos os celulares com segurança…")
        m = self.manager

        def work():
            from concurrent.futures import ThreadPoolExecutor
            errors = []
            with ThreadPoolExecutor(max_workers=len(names)) as ex:
                futures = {ex.submit(m.stop, n): n for n in names}
                for f, n in futures.items():
                    try:
                        f.result()
                    except Exception as exc:  # noqa: BLE001
                        errors.append((n, str(exc)))
            return errors

        def done(errors):
            if errors:
                self.centralWidget().setEnabled(True)
                self.timer.start(POLL_MS)
                common.error(self, "Desligar", "Alguns celulares não desligaram. Tente desligá-los individualmente.",
                             "\n".join(f"{self._name(n)}: {e}" for n, e in errors))
                return
            self._force_close = True
            self.close()

        run_task(work, on_done=done, on_error=lambda e: done([("?", str(e))]))
