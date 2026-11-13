"""Detecção do Android SDK e das ferramentas oficiais (emulator, adb, avdmanager, sdkmanager)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from utils.proc import run

ANDROID_VERSIONS = {
    21: "5.0", 22: "5.1", 23: "6.0", 24: "7.0", 25: "7.1", 26: "8.0", 27: "8.1",
    28: "9", 29: "10", 30: "11", 31: "12", 32: "12L", 33: "13", 34: "14",
    35: "15", 36: "16", 37: "17",
}


def android_version(api: int | None) -> str:
    if not api:
        return "?"
    return ANDROID_VERSIONS.get(api, f"API {api}")


@dataclass
class SdkPaths:
    sdk: str = ""
    emulator: str = ""
    adb: str = ""
    avdmanager: str = ""
    sdkmanager: str = ""

    def problems(self) -> list[str]:
        out = []
        if not self.sdk or not Path(self.sdk).is_dir():
            out.append("Pasta do Android SDK não encontrada.")
        if not self.emulator or not Path(self.emulator).is_file():
            out.append("Android Emulator (emulator.exe) não encontrado. Instale o pacote 'Android Emulator' no SDK Manager.")
        if not self.adb or not Path(self.adb).is_file():
            out.append("ADB (adb.exe) não encontrado. Instale o pacote 'Android SDK Platform-Tools'.")
        if not self.avdmanager or not Path(self.avdmanager).is_file():
            out.append("avdmanager não encontrado. Instale 'Android SDK Command-line Tools (latest)'. Sem ele não é possível criar celulares.")
        return out


def candidate_sdk_dirs() -> list[Path]:
    cands = []
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(var):
            cands.append(Path(os.environ[var]))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cands.append(Path(local) / "Android" / "Sdk")
    cands += [Path("C:/Android/Sdk"), Path("C:/Android/sdk"), Path.home() / "Android" / "Sdk"]
    return cands


def find_sdk() -> str:
    for c in candidate_sdk_dirs():
        if (c / "emulator").is_dir() or (c / "platform-tools").is_dir():
            return str(c)
    return ""


def _cmdline_tool(sdk: Path, tool: str) -> str:
    latest = sdk / "cmdline-tools" / "latest" / "bin" / f"{tool}.bat"
    if latest.is_file():
        return str(latest)
    ct = sdk / "cmdline-tools"
    if ct.is_dir():
        for d in sorted(ct.iterdir(), reverse=True):
            f = d / "bin" / f"{tool}.bat"
            if f.is_file():
                return str(f)
    legacy = sdk / "tools" / "bin" / f"{tool}.bat"
    return str(legacy) if legacy.is_file() else ""


def resolve(settings) -> SdkPaths:
    """Usa os caminhos salvos e completa os que faltarem a partir da pasta do SDK."""
    sdk = settings.sdk_path or find_sdk()
    sdk_p = Path(sdk) if sdk else None
    paths = SdkPaths(sdk=sdk)

    def pick(saved: str, default: str) -> str:
        if saved and Path(saved).is_file():
            return saved
        return default

    if sdk_p:
        emu = sdk_p / "emulator" / "emulator.exe"
        adb = sdk_p / "platform-tools" / "adb.exe"
        paths.emulator = pick(settings.emulator_path, str(emu) if emu.is_file() else "")
        paths.adb = pick(settings.adb_path, str(adb) if adb.is_file() else "")
        paths.avdmanager = pick(settings.avdmanager_path, _cmdline_tool(sdk_p, "avdmanager"))
        paths.sdkmanager = pick(settings.sdkmanager_path, _cmdline_tool(sdk_p, "sdkmanager"))
    else:
        paths.emulator = settings.emulator_path
        paths.adb = settings.adb_path
        paths.avdmanager = settings.avdmanager_path
        paths.sdkmanager = settings.sdkmanager_path
    return paths


@dataclass
class SystemImage:
    package: str
    api: int
    tag: str
    abi: str
    description: str

    @property
    def android(self) -> str:
        return android_version(self.api)

    @property
    def has_play_store(self) -> bool:
        return "playstore" in self.tag

    @property
    def label(self) -> str:
        store = " + Play Store" if self.has_play_store else ""
        return f"Android {self.android} (API {self.api}) — {self.description or self.tag}{store} [{self.abi}]"


def _read_props(path: Path) -> dict:
    props = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
    except OSError:
        pass
    return props


def list_system_images(sdk: str) -> list[SystemImage]:
    root = Path(sdk) / "system-images" if sdk else None
    images: list[SystemImage] = []
    if not root or not root.is_dir():
        return images
    for platform in root.iterdir():
        for tag in (platform.iterdir() if platform.is_dir() else []):
            for abi in (tag.iterdir() if tag.is_dir() else []):
                if not abi.is_dir():
                    continue
                props = _read_props(abi / "source.properties")
                m = re.search(r"(\d+)", platform.name)
                api = int(props.get("AndroidVersion.ApiLevel", m.group(1) if m else 0) or 0)
                images.append(
                    SystemImage(
                        package=f"system-images;{platform.name};{tag.name};{abi.name}",
                        api=api,
                        tag=tag.name,
                        abi=abi.name,
                        description=props.get("SystemImage.TagDisplay") or props.get("Pkg.Desc", "").split(" System Image")[0],
                    )
                )
    images.sort(key=lambda i: (-i.api, i.tag, i.abi))
    return images


def list_device_profiles(avdmanager: str, env: dict | None = None) -> list[str]:
    if not avdmanager:
        return []
    try:
        res = run([avdmanager, "list", "device", "-c"], timeout=90, env=env)
    except Exception:
        return []
    names = [l.strip() for l in res.stdout.splitlines() if l.strip()]
    return [n for n in names if not n.lower().startswith(("warning", "error", "["))]


def accel_check(emulator: str) -> tuple[bool, str]:
    """Pergunta ao emulador se a aceleração de hardware (WHPX/AEHD) está disponível."""
    if not emulator:
        return False, "Emulador não encontrado"
    try:
        res = run([emulator, "-accel-check"], timeout=30)
    except Exception as exc:
        return False, str(exc)
    text = (res.stdout + res.stderr).strip()
    lines = [l for l in text.splitlines() if l.strip() and l.strip() not in ("accel:", "accel", "0")]
    msg = lines[0].strip() if lines else text
    ok = "usable" in text.lower() and "not" not in msg.lower()
    return ok, msg
