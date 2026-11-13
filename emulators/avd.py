"""Leitura, criação e configuração dos AVDs (Android Virtual Devices).

Regras de segurança:
- um AVD existente NUNCA é recriado nem formatado (avdmanager é chamado sem --force);
- config.ini só é alterado com o emulador desligado, com cópia de segurança e escrita atômica.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from services.sdk import android_version
from utils.proc import CommandError, run

log = logging.getLogger(__name__)


class AvdError(Exception):
    pass


def default_avd_home() -> Path:
    env = os.environ.get("ANDROID_AVD_HOME")
    if env:
        return Path(env)
    return Path(os.environ.get("ANDROID_USER_HOME") or (Path.home() / ".android")) / "avd"


def parse_size(value: str | None) -> int:
    """'6G', '2048M', '512 MB', '6442450944' -> bytes."""
    if not value:
        return 0
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([KMGT]?)B?\s*$", str(value), re.I)
    if not m:
        return 0
    num = float(m.group(1))
    mult = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[m.group(2).upper()]
    return int(num * mult)


def read_kv(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def update_kv(path: Path, updates: dict[str, str]) -> None:
    """Altera chaves preservando o resto do arquivo. Guarda config.ini.bak e grava de forma atômica."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    pending = dict(updates)
    out = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key in pending:
                out.append(f"{key}={pending.pop(key)}")
                continue
        out.append(line)
    out += [f"{k}={v}" for k, v in pending.items()]
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class AvdInfo:
    name: str
    ini_path: Path
    path: Path
    exists: bool = False
    problem: str = ""
    config: dict = field(default_factory=dict)

    @property
    def api_level(self) -> int | None:
        sysdir = self.config.get("image.sysdir.1", "")
        m = re.search(r"android-(\d+)", sysdir)
        if m:
            return int(m.group(1))
        target = read_kv(self.ini_path).get("target", "")
        m = re.search(r"(\d+)", target)
        return int(m.group(1)) if m else None

    @property
    def android(self) -> str:
        return android_version(self.api_level)

    @property
    def image_tag(self) -> str:
        return self.config.get("tag.display") or self.config.get("tag.id", "")

    @property
    def system_image(self) -> str:
        sysdir = self.config.get("image.sysdir.1", "").replace("\\", "/").strip("/")
        return sysdir.replace("/", ";")

    @property
    def ram_mb(self) -> int:
        raw = self.config.get("hw.ramSize", "")
        if raw.isdigit():
            return int(raw)
        return parse_size(raw) // 1024**2

    @property
    def storage_bytes(self) -> int:
        return parse_size(self.config.get("disk.dataPartition.size", ""))

    @property
    def lcd(self) -> tuple[int, int, int]:
        def num(key):
            try:
                return int(self.config.get(key, "0"))
            except ValueError:
                return 0
        return num("hw.lcd.width"), num("hw.lcd.height"), num("hw.lcd.density")

    @property
    def cpu_cores(self) -> int:
        try:
            return int(self.config.get("hw.cpu.ncore", "0"))
        except ValueError:
            return 0

    @property
    def quickboot(self) -> bool:
        return self.config.get("fastboot.forceColdBoot", "no") != "yes"


class AvdStore:
    def __init__(self, avd_home: str = "", java_home: str = ""):
        self.home = Path(avd_home) if avd_home else default_avd_home()
        self.java_home = java_home

    def env(self, sdk: str = "") -> dict:
        from utils.proc import clean_env

        env = clean_env()
        if self.java_home:
            env["JAVA_HOME"] = self.java_home
            env["PATH"] = str(Path(self.java_home) / "bin") + os.pathsep + env.get("PATH", "")
        if self.home != default_avd_home() or "ANDROID_AVD_HOME" in os.environ:
            env["ANDROID_AVD_HOME"] = str(self.home)
        if sdk:
            env["ANDROID_SDK_ROOT"] = sdk
            env["ANDROID_HOME"] = sdk
        return env

    def ini_path(self, name: str) -> Path:
        return self.home / f"{name}.ini"

    def default_dir(self, name: str) -> Path:
        return self.home / f"{name}.avd"

    def read(self, name: str) -> AvdInfo:
        ini = self.ini_path(name)
        path = self.default_dir(name)
        info = AvdInfo(name=name, ini_path=ini, path=path)
        if ini.is_file():
            data = read_kv(ini)
            p = data.get("path")
            if p:
                info.path = Path(p)
            elif data.get("path.rel"):
                info.path = self.home.parent / data["path.rel"]
        if info.path.is_dir() and (info.path / "config.ini").is_file():
            info.exists = True
            info.config = read_kv(info.path / "config.ini")
            if not ini.is_file():
                info.problem = "Arquivo .ini do AVD ausente (a pasta de dados existe). Use 'Reparar' nas configurações do celular."
        elif ini.is_file():
            info.problem = f"O registro do AVD existe, mas a pasta de dados não foi encontrada: {info.path}"
        elif info.path.exists():
            info.problem = f"Existe uma pasta {info.path} sem config.ini. Verifique manualmente antes de criar."
        return info

    def check_shared_storage(self, names: list[str]) -> dict[str, str]:
        """Detecta dois celulares apontando para a mesma pasta de dados."""
        seen: dict[str, str] = {}
        conflicts: dict[str, str] = {}
        for n in names:
            info = self.read(n)
            if not info.exists:
                continue
            key = str(info.path.resolve()).lower()
            if key in seen:
                msg = f"Usa a mesma pasta de dados que {seen[key]} ({info.path}). Inicialização bloqueada."
                conflicts[n] = msg
                conflicts[seen[key]] = msg
            else:
                seen[key] = n
        return conflicts

    def repair_ini(self, name: str, api: int | None) -> None:
        info = self.read(name)
        if not info.exists:
            raise AvdError("Não há pasta de dados para reparar.")
        if info.ini_path.exists():
            return
        rel = f"avd\\{info.path.name}"
        info.ini_path.write_text(
            f"avd.ini.encoding=UTF-8\npath={info.path}\npath.rel={rel}\ntarget=android-{api or ''}\n",
            encoding="utf-8",
        )

    def create(
        self,
        name: str,
        avdmanager: str,
        sdk: str,
        system_image: str,
        device_profile: str,
        ram_mb: int,
        storage_gb: int,
        lcd: tuple[int, int, int],
        cpu_cores: int,
        display_name: str,
    ) -> AvdInfo:
        info = self.read(name)
        if info.exists or info.ini_path.exists() or info.path.exists():
            raise AvdError(f"{name} já existe. Por segurança, um celular existente nunca é recriado.")
        if not avdmanager or not Path(avdmanager).is_file():
            raise AvdError("avdmanager não encontrado. Instale 'Android SDK Command-line Tools' pelo SDK Manager.")
        if not system_image:
            raise AvdError("Escolha uma imagem do sistema Android.")
        self.home.mkdir(parents=True, exist_ok=True)
        path = self.default_dir(name)
        args = [avdmanager, "create", "avd", "-n", name, "-k", system_image, "-p", str(path)]
        if device_profile:
            args += ["-d", device_profile]
        try:
            res = run(args, timeout=300, env=self.env(sdk), input_text="no\n")
        except CommandError as exc:
            raise AvdError(str(exc)) from exc
        info = self.read(name)
        if res.returncode != 0 or not info.exists:
            out = (res.stderr or res.stdout).strip()
            err = next((l for l in out.splitlines() if "Error" in l), out[-600:])
            raise AvdError(f"avdmanager falhou ao criar {name}:\n{err}")

        w, h, d = lcd
        updates = {
            "avd.ini.displayname": display_name,
            "hw.ramSize": str(int(ram_mb)),
            "disk.dataPartition.size": f"{int(storage_gb)}G",
            "hw.keyboard": "yes",
            "hw.gpu.enabled": "yes",
            "hw.gpu.mode": "auto",
            "showDeviceFrame": "no",
            "fastboot.forceColdBoot": "no",
            "fastboot.forceFastBoot": "yes",
        }
        if w and h:
            updates["hw.lcd.width"] = str(w)
            updates["hw.lcd.height"] = str(h)
        if d:
            updates["hw.lcd.density"] = str(d)
        if cpu_cores:
            updates["hw.cpu.ncore"] = str(cpu_cores)
        if "playstore" in system_image:
            updates["PlayStore.enabled"] = "yes"  # avdmanager nem sempre marca; sem isso a Play Store fica oculta
        update_kv(info.path / "config.ini", updates)
        return self.read(name)

    def apply_settings(self, name: str, updates: dict[str, str]) -> AvdInfo:
        info = self.read(name)
        if not info.exists:
            raise AvdError(f"{name} não existe.")
        new_size = updates.get("disk.dataPartition.size")
        if new_size and parse_size(new_size) < info.storage_bytes:
            raise AvdError("Não é possível reduzir o armazenamento de um celular existente (isso apagaria dados).")
        update_kv(info.path / "config.ini", updates)
        return self.read(name)
