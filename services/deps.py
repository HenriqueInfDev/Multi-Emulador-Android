"""Detecção e instalação das dependências do gerenciador.

O gerenciador em si é distribuído como .exe (Python e PySide6 já vão embutidos).
O que pode faltar no computador:

  1. Java (JDK 17+)          — exigido pelo avdmanager/sdkmanager do Android SDK
  2. Android SDK Command-line Tools (avdmanager, sdkmanager)
  3. Android SDK Platform-Tools (adb)
  4. Android Emulator
  5. Uma imagem do sistema Android (versão do Android dos celulares)
  6. Aceleração de hardware (Plataforma do Hipervisor do Windows / WHPX)

Tudo é baixado das fontes oficiais (Google e Eclipse Adoptium), com verificação de checksum.
As licenças do Android SDK só são aceitas depois que o usuário as aceita na interface.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from config.settings import tools_dir
from utils.proc import CREATE_NO_WINDOW, run

log = logging.getLogger(__name__)

REPO_BASE = "https://dl.google.com/android/repository/"
REPO_XML = REPO_BASE + "repository2-3.xml"
ADOPTIUM_API = ("https://api.adoptium.net/v3/assets/latest/21/hotspot"
                "?architecture=x64&image_type=jdk&os=windows&vendor=eclipse")
USER_AGENT = "AndroidEmulatorManager/1.0"
DEFAULT_IMAGE = "system-images;android-29;google_apis_playstore;x86_64"
MIN_JAVA = 17

Progress = Callable[[str, int], None]  # (texto, porcentagem 0-100 ou -1 indeterminado)


class DepsError(Exception):
    pass


class Cancelled(DepsError):
    pass


# ---------------------------------------------------------------------- Java
def _java_version(java_exe: str) -> int:
    try:
        res = run([java_exe, "-version"], timeout=20)
    except Exception:
        return 0
    m = re.search(r'version "(\d+)(?:\.(\d+))?', res.stderr + res.stdout)
    if not m:
        return 0
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major


def find_java(saved_home: str = "") -> tuple[str, int]:
    """Retorna (JAVA_HOME, versão) do melhor Java >= 17 encontrado, ou ("", 0)."""
    candidates: list[Path] = []
    if saved_home:
        candidates.append(Path(saved_home))
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]))
    for d in sorted(tools_dir().glob("jdk*"), reverse=True):
        candidates.append(d)
    studio = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Android" / "Android Studio" / "jbr"
    candidates.append(studio)
    which = shutil.which("java")
    if which:
        candidates.append(Path(which).resolve().parent.parent)
    for home in candidates:
        exe = home / "bin" / "java.exe"
        if exe.is_file():
            ver = _java_version(str(exe))
            if ver >= MIN_JAVA:
                return str(home), ver
    return "", 0


# ---------------------------------------------------------------------- estado
@dataclass
class DepStatus:
    key: str
    title: str
    ok: bool
    detail: str
    can_install: bool = True


def check_all(manager) -> list[DepStatus]:
    s = manager.settings
    p = manager.paths
    java_home, java_ver = find_java(s.java_home)
    images = []
    if p.sdk:
        from services.sdk import list_system_images
        images = list_system_images(p.sdk)
    accel = getattr(manager, "accel", None)
    if accel is None and p.emulator:
        from services.sdk import accel_check
        accel = accel_check(p.emulator)
        manager.accel = accel
    accel_ok, accel_msg = accel or (False, "Instale o Android Emulator primeiro")
    return [
        DepStatus("java", "Java (JDK 17 ou mais novo)", bool(java_home),
                  f"Java {java_ver} em {java_home}" if java_home else "Não encontrado — necessário para criar celulares"),
        DepStatus("cmdline", "Android SDK Command-line Tools", bool(p.avdmanager and p.sdkmanager),
                  p.avdmanager or "Não encontrado (avdmanager / sdkmanager)"),
        DepStatus("platform-tools", "Android SDK Platform-Tools (ADB)", bool(p.adb), p.adb or "Não encontrado"),
        DepStatus("emulator", "Android Emulator", bool(p.emulator), p.emulator or "Não encontrado"),
        DepStatus("image", "Imagem do sistema Android", bool(images),
                  ", ".join(f"Android {i.android}" + (" + Play" if i.has_play_store else "") for i in images[:4])
                  if images else "Nenhuma versão do Android instalada"),
        DepStatus("accel", "Aceleração de hardware (WHPX)", accel_ok, accel_msg),
    ]


def default_sdk_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Android" / "Sdk"


# ---------------------------------------------------------------------- download
def download(url: str, dest: Path, progress: Progress | None, label: str,
             cancel: threading.Event | None = None, expected_size: int = 0) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or expected_size or 0)
        done = 0
        while True:
            if cancel and cancel.is_set():
                out.close()
                tmp.unlink(missing_ok=True)
                raise Cancelled("Instalação cancelada.")
            buf = resp.read(1024 * 256)
            if not buf:
                break
            out.write(buf)
            done += len(buf)
            if progress:
                pct = int(done * 100 / total) if total else -1
                progress(f"Baixando {label}: {done / 1024**2:.0f} de {total / 1024**2:.0f} MB" if total
                         else f"Baixando {label}: {done / 1024**2:.0f} MB", pct)
    os.replace(tmp, dest)
    return dest


def _checksum(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract(zip_path: Path, dest: Path, progress: Progress | None, label: str) -> None:
    with zipfile.ZipFile(zip_path) as z:
        members = z.infolist()
        for i, m in enumerate(members):
            z.extract(m, dest)
            if progress and i % 200 == 0:
                progress(f"Extraindo {label}…", int(i * 100 / max(1, len(members))))


# ---------------------------------------------------------------------- instaladores
def install_java(progress: Progress | None = None, cancel: threading.Event | None = None) -> str:
    """Baixa o JDK 21 (Eclipse Temurin) para a pasta do gerenciador. Não precisa de administrador."""
    if progress:
        progress("Consultando a versão mais recente do Java (Eclipse Temurin)…", -1)
    assets = _get_json(ADOPTIUM_API)
    if not assets:
        raise DepsError("Não foi possível encontrar o pacote do Java para Windows.")
    pkg = assets[0]["binary"]["package"]
    name = pkg["name"]
    if not name.endswith(".zip"):
        raise DepsError(f"Pacote do Java inesperado: {name}")
    downloads = tools_dir() / "downloads"
    zip_path = download(pkg["link"], downloads / name, progress, "Java", cancel, pkg.get("size", 0))
    if pkg.get("checksum") and _checksum(zip_path, "sha256") != pkg["checksum"].lower():
        zip_path.unlink(missing_ok=True)
        raise DepsError("O arquivo do Java baixado está corrompido (checksum diferente). Tente novamente.")
    stage = tools_dir() / "_extraindo_jdk"
    shutil.rmtree(stage, ignore_errors=True)
    _extract(zip_path, stage, progress, "Java")
    inner = next((d for d in stage.iterdir() if d.is_dir()), None)
    if not inner or not (inner / "bin" / "java.exe").is_file():
        raise DepsError("O pacote do Java não tem o formato esperado.")
    target = tools_dir() / inner.name
    if target.exists():
        shutil.rmtree(stage, ignore_errors=True)
    else:
        os.replace(inner, target)
        shutil.rmtree(stage, ignore_errors=True)
    zip_path.unlink(missing_ok=True)
    if _java_version(str(target / "bin" / "java.exe")) < MIN_JAVA:
        raise DepsError("O Java instalado não pôde ser executado.")
    return str(target)


def install_cmdline_tools(sdk: Path, progress: Progress | None = None,
                          cancel: threading.Event | None = None) -> None:
    """Baixa o Command-line Tools mais recente direto do repositório oficial do Google."""
    if progress:
        progress("Consultando o repositório do Android SDK…", -1)
    req = urllib.request.Request(REPO_XML, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        root = ET.fromstring(resp.read())
    best = None
    for pkg in root.iter("remotePackage"):
        if pkg.get("path") != "cmdline-tools;latest":
            continue
        channel = pkg.find("channelRef")
        if channel is not None and channel.get("ref") not in (None, "channel-0"):
            continue  # só versões estáveis
        for arch in pkg.iter("archive"):
            if (arch.findtext("host-os") or "") == "windows":
                comp = arch.find("complete")
                best = (comp.findtext("url"), comp.findtext("checksum"), int(comp.findtext("size") or 0))
        if best:
            break
    if not best:
        raise DepsError("Não foi possível localizar o Command-line Tools para Windows no repositório do Google.")
    url, sha1, size = best
    zip_path = download(REPO_BASE + url, tools_dir() / "downloads" / url, progress, "Command-line Tools", cancel, size)
    if sha1 and _checksum(zip_path, "sha1") != sha1.lower():
        zip_path.unlink(missing_ok=True)
        raise DepsError("O arquivo baixado está corrompido (checksum diferente). Tente novamente.")
    stage = sdk / "cmdline-tools" / "_extraindo"
    shutil.rmtree(stage, ignore_errors=True)
    _extract(zip_path, stage, progress, "Command-line Tools")
    inner = stage / "cmdline-tools"
    if not (inner / "bin" / "sdkmanager.bat").is_file():
        raise DepsError("O pacote do Command-line Tools não tem o formato esperado.")
    latest = sdk / "cmdline-tools" / "latest"
    if latest.exists():
        old = sdk / "cmdline-tools" / "latest-antigo"
        shutil.rmtree(old, ignore_errors=True)
        os.replace(latest, old)
    os.replace(inner, latest)
    shutil.rmtree(stage, ignore_errors=True)
    zip_path.unlink(missing_ok=True)


def sdk_env(sdk: Path, java_home: str) -> dict:
    env = dict(os.environ)
    env["ANDROID_SDK_ROOT"] = str(sdk)
    env["ANDROID_HOME"] = str(sdk)
    if java_home:
        env["JAVA_HOME"] = java_home
        env["PATH"] = str(Path(java_home) / "bin") + os.pathsep + env.get("PATH", "")
    return env


def _sdkmanager_stream(sdkmanager: str, args: list[str], env: dict, answer_yes: bool,
                       progress: Progress | None, cancel: threading.Event | None, label: str) -> str:
    proc = subprocess.Popen(
        [sdkmanager, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, creationflags=CREATE_NO_WINDOW, text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    if answer_yes:
        try:
            proc.stdin.write("y\n" * 60)
            proc.stdin.flush()
        except OSError:
            pass
    try:
        proc.stdin.close()
    except OSError:
        pass
    tail: list[str] = []
    buf = ""
    while True:
        if cancel and cancel.is_set():
            proc.kill()
            raise Cancelled("Instalação cancelada.")
        ch = proc.stdout.read(1)
        if not ch:
            break
        if ch in "\r\n":
            line = buf.strip()
            buf = ""
            if not line:
                continue
            tail = (tail + [line])[-40:]
            m = re.search(r"(\d{1,3})%\s*(.*)", line)
            if progress:
                if m:
                    progress(f"{label}: {m.group(2) or 'instalando'}"[:140], min(100, int(m.group(1))))
                elif not line.startswith("["):
                    progress(f"{label}: {line}"[:140], -1)
        else:
            buf += ch
    proc.wait()
    out = "\n".join(tail)
    if proc.returncode != 0:
        raise DepsError(f"sdkmanager falhou ({label}):\n{out[-1500:]}")
    return out


def accept_licenses(sdkmanager: str, sdk: Path, java_home: str, progress: Progress | None = None,
                    cancel: threading.Event | None = None) -> None:
    """Só deve ser chamado depois que o usuário aceitou as licenças na interface."""
    _sdkmanager_stream(sdkmanager, [f"--sdk_root={sdk}", "--licenses"], sdk_env(sdk, java_home), True,
                       progress, cancel, "Licenças")


def install_packages(sdkmanager: str, sdk: Path, java_home: str, packages: list[str],
                     progress: Progress | None = None, cancel: threading.Event | None = None) -> None:
    env = sdk_env(sdk, java_home)
    for pkg in packages:
        _sdkmanager_stream(sdkmanager, [f"--sdk_root={sdk}", "--install", pkg], env, True,
                           progress, cancel, pkg.split(";")[0] if not pkg.startswith("system-images") else "Imagem do Android")


def license_text(sdkmanager: str, sdk: Path, java_home: str) -> str:
    """Texto das licenças ainda não aceitas (para mostrar ao usuário)."""
    try:
        res = run([sdkmanager, f"--sdk_root={sdk}", "--licenses"], timeout=120, env=sdk_env(sdk, java_home),
                  input_text="n\n" * 30)
    except Exception as exc:  # noqa: BLE001
        return f"(Não foi possível obter o texto das licenças: {exc})"
    text = res.stdout
    text = re.sub(r"Review license.*?\(y/N\):?", "", text, flags=re.S | re.I)
    text = re.sub(r"\[=*\s*\]\s*\d+%.*", "", text)
    return text.strip() or "Todas as licenças já foram aceitas."


def enable_whpx() -> bool:
    """Ativa a 'Plataforma do Hipervisor do Windows' (pede permissão de administrador ao usuário)."""
    cmd = ("-NoProfile -Command \"Enable-WindowsOptionalFeature -Online -FeatureName HypervisorPlatform -All "
           "-NoRestart; Write-Host ''; Write-Host 'Concluido. Reinicie o computador para ativar.'; Read-Host 'Enter para fechar'\"")
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", cmd, None, 1)
    return r > 32
