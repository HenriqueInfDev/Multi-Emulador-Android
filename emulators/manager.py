"""Gerenciamento das instâncias do Android Emulator: estado, iniciar, desligar, reiniciar, janela.

O estado de cada celular é obtido de duas fontes independentes:
- processos do emulador em execução (psutil, procurando "-avd <nome>" na linha de comando);
- dispositivos conectados ao ADB (adb devices + "adb emu avd name").
Assim o mesmo celular nunca é iniciado duas vezes, mesmo se foi aberto fora do gerenciador.
"""
from __future__ import annotations

import ctypes
import logging
import shlex
import socket
import subprocess
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from config.settings import SettingsStore, logs_dir, phone_names, phone_number
from emulators.avd import AvdInfo, AvdStore
from services import sdk as sdk_service
from services.adb import Adb, AdbError
from utils import system
from utils.proc import CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW

log = logging.getLogger(__name__)

OFF, BOOTING, ON, STOPPING, STARTING, RESTARTING, BUSY, MISSING, ERROR = (
    "off", "booting", "on", "stopping", "starting", "restarting", "busy", "missing", "error",
)
RUNNING_STATES = {BOOTING, ON, STOPPING, RESTARTING, STARTING}


class EmulatorError(Exception):
    pass


class NotResponding(EmulatorError):
    pass


@dataclass
class ProcInfo:
    pid: int
    name: str
    port: int | None


@dataclass
class PhoneState:
    name: str
    status: str = OFF
    info: AvdInfo | None = None
    serial: str | None = None
    pids: list[int] = field(default_factory=list)
    busy_text: str = ""
    message: str = ""

    @property
    def running(self) -> bool:
        return bool(self.pids)


@dataclass
class Snapshot:
    phones: dict[str, PhoneState]
    others_running: list[str]
    memory: system.MemoryInfo
    adb_error: str = ""


class EmulatorManager:
    def __init__(self, store: SettingsStore):
        self.store = store
        self._lock = threading.RLock()
        self._busy: dict[str, tuple[str, str]] = {}  # nome -> (estado, texto)
        self._serial_names: dict[str, str] = {}
        self._booted: set[str] = set()
        self._launched: dict[str, subprocess.Popen] = {}
        self.reload_paths()

    # ------------------------------------------------------------------ caminhos
    def reload_paths(self) -> None:
        s = self.store.settings
        self.paths = sdk_service.resolve(s)
        from services.deps import find_java

        self.java_home, self.java_version = find_java(s.java_home)
        self.avds = AvdStore(s.avd_home, self.java_home)
        self.adb = Adb(self.paths.adb)
        from backup.backup import BackupManager

        self.backups = BackupManager(s.backup_dir, self.avds)

    @property
    def settings(self):
        return self.store.settings

    def env(self) -> dict:
        return self.avds.env(self.paths.sdk)

    # ------------------------------------------------------------------ ocupado
    def set_busy(self, name: str, state: str, text: str) -> None:
        with self._lock:
            self._busy[name] = (state, text)

    def clear_busy(self, name: str) -> None:
        with self._lock:
            self._busy.pop(name, None)

    def busy(self, name: str) -> tuple[str, str] | None:
        with self._lock:
            return self._busy.get(name)

    # ------------------------------------------------------------------ detecção
    def scan_processes(self) -> dict[str, list[ProcInfo]]:
        found: dict[str, list[ProcInfo]] = {}
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            pname = (p.info.get("name") or "").lower()
            if not (pname.startswith("qemu-system") or pname in ("emulator.exe", "emulator")):
                continue
            cmd = p.info.get("cmdline") or []
            avd, port = None, None
            for i, a in enumerate(cmd):
                if a == "-avd" and i + 1 < len(cmd):
                    avd = cmd[i + 1]
                elif a.startswith("@") and len(a) > 1 and avd is None:
                    avd = a[1:]
                elif a == "-port" and i + 1 < len(cmd):
                    try:
                        port = int(cmd[i + 1])
                    except ValueError:
                        pass
            if avd:
                found.setdefault(avd, []).append(ProcInfo(p.info["pid"], pname, port))
        return found

    def _map_serials(self, devices: dict[str, str]) -> dict[str, str]:
        """nome do AVD -> serial, usando cache de 'adb emu avd name'."""
        for serial in list(self._serial_names):
            if serial not in devices:
                self._serial_names.pop(serial, None)
                self._booted.discard(serial)
        result = {}
        for serial in devices:
            if not serial.startswith("emulator-"):
                continue
            name = self._serial_names.get(serial)
            if not name:
                name = self.adb.avd_name(serial)
                if name:
                    self._serial_names[serial] = name
            if name:
                result[name] = serial
        return result

    def snapshot(self) -> Snapshot:
        names = phone_names()
        procs = self.scan_processes()
        adb_error = ""
        devices: dict[str, str] = {}
        try:
            devices = self.adb.devices()
        except AdbError as exc:
            adb_error = str(exc)
        serials = self._map_serials(devices) if devices else {}
        conflicts = self.avds.check_shared_storage(names)

        phones: dict[str, PhoneState] = {}
        for name in names:
            info = self.avds.read(name)
            st = PhoneState(name=name, info=info)
            plist = procs.get(name, [])
            st.pids = [p.pid for p in plist]
            serial = serials.get(name)
            if not serial:
                port = next((p.port for p in plist if p.port), None)
                if port:
                    serial = f"emulator-{port}"
            st.serial = serial

            if not info.exists:
                st.status = ERROR if info.problem else MISSING
                st.message = info.problem
            elif name in conflicts:
                st.status = ERROR
                st.message = conflicts[name]
            elif st.pids:
                if serial and devices.get(serial) == "device":
                    if serial in self._booted or self.adb.boot_completed(serial):
                        self._booted.add(serial)
                        st.status = ON
                    else:
                        st.status = BOOTING
                else:
                    st.status = BOOTING
            else:
                st.status = OFF

            busy = self.busy(name)
            if busy:
                st.status, st.busy_text = busy
            phones[name] = st

        others = sorted(n for n in procs if n not in names)
        return Snapshot(phones=phones, others_running=others, memory=system.memory(), adb_error=adb_error)

    def phone_state(self, name: str) -> PhoneState:
        return self.snapshot().phones[name]

    def running_count(self) -> int:
        return len(self.scan_processes())

    # ------------------------------------------------------------------ iniciar
    def _port_free(self, port: int, used: set[str]) -> bool:
        if f"emulator-{port}" in used:
            return False
        for p in (port, port + 1):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", p))
                except OSError:
                    return False
        return True

    def _pick_port(self, name: str) -> int:
        try:
            used = set(self.adb.devices())
        except AdbError:
            used = set()
        procs = self.scan_processes()
        used |= {f"emulator-{p.port}" for pl in procs.values() for p in pl if p.port}
        preferred = 5554 + (phone_number(name) - 1) * 2
        candidates = [preferred] + [p for p in range(5554, 5684, 2) if p != preferred]
        for port in candidates:
            if 5554 <= port <= 5682 and self._port_free(port, used):
                return port
        raise EmulatorError("Nenhuma porta livre para o emulador (5554–5682).")

    def headless_for(self, name: str) -> bool:
        opt = self.settings.phones.get(name)
        if opt and opt.headless == "sim":
            return True
        if opt and opt.headless == "nao":
            return False
        return self.settings.headless_default

    def log_path(self, name: str) -> Path:
        return logs_dir() / f"{name}.log"

    def log_tail(self, name: str, lines: int = 15) -> str:
        try:
            text = self.log_path(name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        keep = [l for l in text.splitlines() if l.strip()]
        important = [l for l in keep if any(k in l for k in ("ERROR", "FATAL", "error", "Error"))]
        return "\n".join((important or keep)[-lines:])

    def estimated_bytes(self, name: str) -> int:
        """Memória real que um celular ligado consome (medido: RAM do Android + ~1 GB do emulador/gráficos).

        Imagens com Google Play têm mínimo de 2048 MB: o emulador aumenta sozinho valores menores.
        """
        info = self.avds.read(name)
        ram = info.ram_mb or 2048
        if "playstore" in info.config.get("image.sysdir.1", "") or info.config.get("PlayStore.enabled") == "yes":
            ram = max(ram, 2048)
        return (ram + 1024) * 1024**2

    def start(self, name: str, headless: bool | None = None, check_limit: bool = True,
              check_memory: bool = True) -> str:
        """Inicia o emulador e espera o processo subir. A inicialização do Android é acompanhada pelo status."""
        problems = self.paths.problems()
        if any("emulator" in p.lower() for p in problems):
            raise EmulatorError(problems[0])
        info = self.avds.read(name)
        if not info.exists:
            raise EmulatorError(info.problem or f"{name} ainda não foi criado.")
        conflicts = self.avds.check_shared_storage(phone_names())
        if name in conflicts:
            raise EmulatorError(conflicts[name])
        procs = self.scan_processes()
        if procs.get(name):
            raise EmulatorError(f"{self.settings.display_name(name)} já está em execução.")
        if check_limit and len(procs) >= self.settings.max_running:
            raise EmulatorError(
                f"Limite de {self.settings.max_running} emulador(es) simultâneo(s) atingido. "
                "Desligue um celular ou aumente o limite nas Configurações."
            )
        if check_memory:
            need = self.estimated_bytes(name)
            free = system.memory().available
            if free < need:
                raise EmulatorError(
                    f"Memória insuficiente para ligar {self.settings.display_name(name)} com segurança: "
                    f"precisa de ~{system.human_size(need)}, livre {system.human_size(free)}. "
                    "Desligue outro celular ou feche programas."
                )

        with self._lock:
            if self.busy(name):
                raise EmulatorError("Já existe uma operação em andamento neste celular.")
            self.set_busy(name, STARTING, "Iniciando…")
        try:
            port = self._pick_port(name)
            if headless is None:
                headless = self.headless_for(name)
            opt = self.settings.phones.get(name)
            gpu = (opt.gpu_mode if opt and opt.gpu_mode else self.settings.gpu_mode) or "auto"

            args = [self.paths.emulator, "-avd", name, "-port", str(port)]
            if headless:
                args += ["-no-window"]
            if gpu != "auto":
                args += ["-gpu", gpu]
            if not self.quickboot_for(name):
                args.append("-no-snapshot")  # inicialização completa; todos os dados vêm do disco
            if self.settings.no_boot_anim:
                args.append("-no-boot-anim")
            if self.settings.no_audio or headless:
                args.append("-no-audio")
            if opt and opt.extra_args.strip():
                args += shlex.split(opt.extra_args, posix=False)

            logp = self.log_path(name)
            if logp.exists():
                try:
                    logp.replace(logp.with_suffix(".anterior.log"))
                except OSError:
                    pass
            logf = open(logp, "w", encoding="utf-8", errors="replace")
            logf.write("Comando: " + " ".join(f'"{a}"' if " " in a else a for a in args) + "\n\n")
            logf.flush()
            log.info("Iniciando %s: %s", name, args)
            from utils.proc import reset_dll_directory

            reset_dll_directory()
            try:
                proc = subprocess.Popen(
                    args,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    cwd=str(Path(self.paths.emulator).parent),
                    env=self.env(),
                    creationflags=CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
                    close_fds=True,
                )
            finally:
                logf.close()
            self._launched[name] = proc

            # Espera o processo aparecer e confirma que não morreu logo no início.
            deadline = time.time() + 25
            seen_at = None
            while time.time() < deadline:
                if proc.poll() is not None and not self.scan_processes().get(name):
                    tail = self.log_tail(name)
                    raise EmulatorError(
                        f"O emulador fechou durante a inicialização (código {proc.returncode}).\n\n{tail}".strip()
                    )
                if self.scan_processes().get(name):
                    seen_at = seen_at or time.time()
                    if time.time() - seen_at > 4:
                        break
                time.sleep(1)
            if not self.scan_processes().get(name):
                raise EmulatorError("O processo do emulador não apareceu. Veja o log do celular.\n\n" + self.log_tail(name))
            return f"emulator-{port}"
        finally:
            self.clear_busy(name)

    def wait_boot(self, name: str, timeout: float = 600) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            st = self.phone_state(name)
            if st.status == ON:
                return True
            if not st.running:
                return False
            time.sleep(3)
        return False

    # ------------------------------------------------------------------ desligar
    def _wait_exit(self, name: str, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.scan_processes().get(name):
                return True
            time.sleep(1.5)
        return False

    def quickboot_for(self, name: str) -> bool:
        opt = self.settings.phones.get(name)
        return bool(opt and opt.quickboot)

    def stop(self, name: str, timeout: float = 180) -> None:
        """Desligamento seguro.

        Sem quick boot (padrão): grava o disco (sync) e desliga o Android de verdade (reboot -p),
        que desmonta as partições de forma limpa; o emulador fecha sozinho em seguida.
        Com quick boot: grava o disco e pede ao emulador para salvar o estado e fechar (emu kill).
        Se o Android não desligar sozinho, usa o emu kill como plano B.
        """
        st = self.phone_state(name)
        if not st.running:
            return
        if self.busy(name) and self.busy(name)[0] != STOPPING:
            raise EmulatorError("Aguarde a operação em andamento terminar.")
        self.set_busy(name, STOPPING, "Desligando…")
        try:
            serial = st.serial
            if not serial:
                raise NotResponding("O emulador não está acessível pelo ADB.")
            online = False
            try:
                online = self.adb.devices().get(serial) == "device"
                if online:
                    self.adb.shell(serial, "sync", timeout=60)
            except AdbError as exc:
                log.warning("sync falhou em %s: %s", name, exc)

            if online and not self.quickboot_for(name):
                try:
                    self.adb.shell(serial, "reboot", "-p", timeout=20)
                except AdbError:
                    pass  # a conexão cai durante o desligamento; é esperado
                if self._wait_exit(name, 90):
                    self._booted.discard(serial)
                    return
                log.warning("%s não fechou após reboot -p; usando emu kill", name)

            try:
                self.adb.emu(serial, "kill", timeout=30)
            except AdbError as exc:
                raise NotResponding(f"O console do emulador não respondeu: {exc}") from exc
            if not self._wait_exit(name, timeout):
                raise NotResponding("O emulador não fechou dentro do tempo esperado.")
            self._booted.discard(serial)
        finally:
            self.clear_busy(name)

    def force_stop(self, name: str) -> None:
        """Encerra o processo à força. Pode perder dados ainda não gravados — só com confirmação do usuário."""
        procs = self.scan_processes().get(name, [])
        for p in procs:
            try:
                proc = psutil.Process(p.pid)
                for child in proc.children(recursive=True):
                    child.kill()
                proc.kill()
            except psutil.Error:
                pass
        self._wait_exit(name, 20)
        self.clear_busy(name)

    # ------------------------------------------------------------------ reiniciar
    def restart(self, name: str, timeout: float = 600) -> None:
        st = self.phone_state(name)
        if not st.running:
            raise EmulatorError("O celular está desligado.")
        if not st.serial or st.status not in (ON, BOOTING):
            raise EmulatorError("O celular ainda não está acessível pelo ADB.")
        serial = st.serial
        self.set_busy(name, RESTARTING, "Reiniciando…")
        try:
            self.adb.reboot(serial)
            self._booted.discard(serial)
            # Espera o Android sair do ar...
            t_end = time.time() + 90
            while time.time() < t_end:
                if self.adb.devices().get(serial) != "device" or not self.adb.boot_completed(serial):
                    break
                time.sleep(2)
            # ...e voltar completamente.
            t_end = time.time() + timeout
            while time.time() < t_end:
                if not self.scan_processes().get(name):
                    raise EmulatorError("O emulador fechou durante a reinicialização.")
                if self.adb.devices().get(serial) == "device" and self.adb.boot_completed(serial):
                    self._booted.add(serial)
                    return
                time.sleep(3)
            raise EmulatorError("O Android não terminou de reiniciar no tempo esperado.")
        finally:
            self.clear_busy(name)

    # ------------------------------------------------------------------ janela
    def focus_window(self, name: str) -> bool:
        """Traz a janela do emulador para frente. Retorna False se ele estiver sem janela."""
        found = self.find_windows(name)
        if not found:
            return False
        user32 = ctypes.windll.user32
        for hwnd in found:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        return True

    def arrange_windows(self, names: list[str] | None = None) -> int:
        """Organiza em grade, na área útil da tela principal, as janelas dos celulares ligados.

        Mantém a proporção de cada janela e deixa espaço à direita para a barra lateral do emulador.
        Retorna quantas janelas foram organizadas.
        """
        user32 = ctypes.windll.user32
        names = names or phone_names()
        windows = []
        for n in sorted(names, key=phone_number):
            hw = self.find_windows(n)
            if hw:
                windows.append(hw[0])
        if not windows:
            return 0

        work = wintypes.RECT()
        user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # SPI_GETWORKAREA
        area_w, area_h = work.right - work.left, work.bottom - work.top
        gap, toolbar = 8, 72  # espaço entre janelas e para a barra de botões do emulador

        # proporção média das janelas atuais (largura/altura)
        ratios = []
        for hwnd in windows:
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            if w > 50 and h > 50:
                ratios.append(w / h)
        ratio = sum(ratios) / len(ratios) if ratios else 0.5

        n = len(windows)
        best = None
        for cols in range(1, n + 1):
            rows = -(-n // cols)
            cell_w = (area_w - gap) / cols - gap
            cell_h = (area_h - gap) / rows - gap
            win_h = min(cell_h, (cell_w - toolbar) / ratio)
            if best is None or win_h > best[0]:
                best = (win_h, cols, rows, cell_w, cell_h)
        win_h, cols, rows, cell_w, cell_h = best
        win_h = int(max(200, win_h))
        win_w = int(win_h * ratio)

        # janelas lado a lado (com espaço para a barra lateral), bloco centralizado na tela
        step_x = win_w + toolbar + gap
        step_y = win_h + gap
        used_cols = min(cols, n)
        block_w = used_cols * step_x - gap
        block_h = rows * step_y - gap
        x0 = work.left + max(gap, (area_w - block_w) // 2)
        y0 = work.top + max(gap, (area_h - block_h) // 2)
        for i, hwnd in enumerate(windows):
            r, c = divmod(i, cols)
            x = x0 + c * step_x
            y = y0 + r * step_y
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)
            user32.MoveWindow(hwnd, x, y, win_w, win_h, True)
            user32.SetForegroundWindow(hwnd)
        return len(windows)

    def find_windows(self, name: str) -> list[int]:
        """Janelas principais ("Android Emulator - <nome>:<porta>") do emulador deste celular."""
        pids = set()
        for p in self.scan_processes().get(name, []):
            pids.add(p.pid)
            try:
                pids |= {c.pid for c in psutil.Process(p.pid).children(recursive=True)}
            except psutil.Error:
                pass
        if not pids:
            return []
        user32 = ctypes.windll.user32
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd, _lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in pids and (user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd)):
                length = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value.startswith("Android Emulator"):
                    found.append(hwnd)
            return True

        user32.EnumWindows(enum_proc, 0)
        return found

    # ------------------------------------------------------------------ apps e arquivos
    def require_online(self, name: str) -> str:
        st = self.phone_state(name)
        if st.status != ON or not st.serial:
            raise EmulatorError(f"{self.settings.display_name(name)} precisa estar ligado e com o Android iniciado.")
        return st.serial

    def install_apk(self, name: str, apks: list[str], grant=False, downgrade=False) -> tuple[bool, str]:
        serial = self.require_online(name)
        return self.adb.install(serial, apks, replace=True, grant=grant, downgrade=downgrade)

    def push_files(self, name: str, files: list[str], remote_dir: str = "/sdcard/Download/") -> None:
        serial = self.require_online(name)
        for f in files:
            self.adb.push(serial, f, remote_dir)

    def pull_dir(self, name: str, remote: str, local: str) -> None:
        serial = self.require_online(name)
        self.adb.pull(serial, remote, local)
