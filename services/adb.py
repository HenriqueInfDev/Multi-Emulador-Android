"""Comunicação com os emuladores via ADB (Android Debug Bridge)."""
from __future__ import annotations

import logging
import threading

from utils.proc import CommandError, run

log = logging.getLogger(__name__)


class AdbError(Exception):
    pass


class Adb:
    def __init__(self, path: str):
        self.path = path
        self._server_lock = threading.Lock()

    def _run(self, args, timeout=30, serial: str | None = None):
        if not self.path:
            raise AdbError("ADB não configurado. Verifique o caminho nas Configurações.")
        cmd = [self.path]
        if serial:
            cmd += ["-s", serial]
        cmd += list(args)
        try:
            return run(cmd, timeout=timeout)
        except CommandError as exc:
            raise AdbError(str(exc)) from exc

    def start_server(self) -> None:
        with self._server_lock:
            self._run(["start-server"], timeout=30)

    def devices(self) -> dict[str, str]:
        """serial -> estado ('device', 'offline', 'unauthorized'...)."""
        res = self._run(["devices"], timeout=20)
        if res.returncode != 0:
            # Servidor ADB caído ou travado: tenta subir de novo uma vez.
            self.start_server()
            res = self._run(["devices"], timeout=20)
            if res.returncode != 0:
                raise AdbError((res.stderr or res.stdout).strip() or "adb devices falhou")
        out = {}
        for line in res.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
        return out

    def emu(self, serial: str, *args, timeout=20) -> str:
        """Comando no console do emulador (adb emu ...)."""
        res = self._run(["emu", *args], timeout=timeout, serial=serial)
        return (res.stdout + res.stderr).strip()

    def avd_name(self, serial: str) -> str | None:
        try:
            out = self.emu(serial, "avd", "name", timeout=10)
        except AdbError:
            return None
        first = out.splitlines()[0].strip() if out else ""
        if not first or first.upper().startswith(("KO", "ERROR")) or "error" in first.lower():
            return None
        return first

    def shell(self, serial: str, *args, timeout=30) -> str:
        res = self._run(["shell", *args], timeout=timeout, serial=serial)
        if res.returncode != 0:
            raise AdbError((res.stderr or res.stdout).strip() or f"adb shell {' '.join(args)} falhou")
        return res.stdout.strip()

    def boot_completed(self, serial: str) -> bool:
        """Android iniciado E armazenamento do usuário montado (antes disso /sdcard aparece vazio)."""
        try:
            out = self.shell(
                serial,
                'echo "$(getprop sys.boot_completed)|$(getprop sys.user.0.ce_available)|$(getprop ro.build.version.sdk)'
                '|$(grep -c " /storage/emulated fuse" /proc/mounts)"',
                timeout=8,
            ).strip()
        except AdbError:
            return False
        boot, ce, sdk, fuse = (out.split("|") + ["", "", "", ""])[:4]
        if boot != "1":
            return False
        api = int(sdk) if sdk.isdigit() else 0
        if api >= 30 and fuse.strip() in ("", "0"):
            return False  # Android 11+: /sdcard só fica disponível após o FUSE montar
        if ce == "true":
            return True
        # Android 6 ou anterior não tem criptografia por usuário (sem ce_available).
        return 0 < api < 24

    def reboot(self, serial: str) -> None:
        res = self._run(["reboot"], timeout=30, serial=serial)
        if res.returncode != 0:
            raise AdbError((res.stderr or res.stdout).strip() or "adb reboot falhou")

    def install(self, serial: str, apks: list[str], replace=True, grant=False, downgrade=False,
                timeout=600) -> tuple[bool, str]:
        cmd = ["install-multiple" if len(apks) > 1 else "install"]
        if replace:
            cmd.append("-r")
        if grant:
            cmd.append("-g")
        if downgrade:
            cmd.append("-d")
        cmd += apks
        res = self._run(cmd, timeout=timeout, serial=serial)
        text = (res.stdout + "\n" + res.stderr).strip()
        ok = res.returncode == 0 and "Success" in text
        if ok:
            return True, "Instalado com sucesso"
        failure = next((l.strip() for l in text.splitlines() if "Failure" in l or "error" in l.lower()), "")
        return False, failure or text or "Falha desconhecida"

    def push(self, serial: str, local: str, remote: str, timeout=1800) -> None:
        res = self._run(["push", local, remote], timeout=timeout, serial=serial)
        if res.returncode != 0:
            raise AdbError((res.stderr or res.stdout).strip())

    def pull(self, serial: str, remote: str, local: str, timeout=1800) -> None:
        res = self._run(["pull", remote, local], timeout=timeout, serial=serial)
        if res.returncode != 0:
            raise AdbError((res.stderr or res.stdout).strip())
