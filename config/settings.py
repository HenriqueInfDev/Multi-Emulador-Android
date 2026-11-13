"""Configurações do gerenciador.

Ficam em %APPDATA%\\AndroidEmulatorManager\\settings.json, separadas dos dados dos
emuladores (que ficam na pasta de AVDs do Android SDK).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_NAME = "AndroidEmulatorManager"
APP_TITLE = "Android Emulator Manager"
APP_VERSION = "1.0.0"
PHONE_COUNT = 12

log = logging.getLogger(__name__)


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tools_dir() -> Path:
    """Ferramentas instaladas pelo assistente (ex.: JDK), em %LOCALAPPDATA%\\AndroidEmulatorManager."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(base) / APP_NAME / "tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def phone_names() -> list[str]:
    return [f"celular_{i:02d}" for i in range(1, PHONE_COUNT + 1)]


def phone_number(name: str) -> int:
    try:
        return int(name.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def default_display_name(name: str) -> str:
    return f"Celular {phone_number(name):02d}"


def default_backup_dir() -> str:
    return str(Path.home() / "AndroidEmulatorManager" / "Backups")


def default_max_running() -> int:
    try:
        import psutil

        total_gb = psutil.virtual_memory().total / 1024**3
        return max(1, min(12, int(total_gb // 4)))
    except Exception:
        return 2


@dataclass
class NewPhoneDefaults:
    system_image: str = ""  # ex.: system-images;android-35;google_apis;x86_64
    device_profile: str = "pixel_6"
    ram_mb: int = 2048
    storage_gb: int = 6
    lcd_width: int = 1080
    lcd_height: int = 2400
    lcd_density: int = 420
    cpu_cores: int = 2


@dataclass
class PhoneOptions:
    display_name: str = ""
    headless: str = "global"  # "global" | "sim" | "nao"
    gpu_mode: str = ""  # "" = usar o padrão global
    extra_args: str = ""
    # Quick boot (snapshot da memória) desligado por padrão: o snapshot pode ficar incompatível
    # (ex.: ao alternar com/sem janela) e o emulador volta a um estado anterior do disco.
    quickboot: bool = False


@dataclass
class Settings:
    sdk_path: str = ""
    emulator_path: str = ""
    adb_path: str = ""
    avdmanager_path: str = ""
    sdkmanager_path: str = ""
    java_home: str = ""  # JDK usado pelo avdmanager/sdkmanager (instalado pelo assistente, se preciso)
    avd_home: str = ""  # vazio = pasta padrão (%USERPROFILE%\.android\avd)
    backup_dir: str = field(default_factory=default_backup_dir)
    max_running: int = field(default_factory=default_max_running)
    headless_default: bool = False
    gpu_mode: str = "auto"
    no_boot_anim: bool = True
    no_audio: bool = False
    ram_alert_percent: int = 85
    autostart_phones: list[str] = field(default_factory=list)
    autostart_with_windows: bool = False
    defaults: NewPhoneDefaults = field(default_factory=NewPhoneDefaults)
    phones: dict[str, PhoneOptions] = field(default_factory=dict)

    def phone(self, name: str) -> PhoneOptions:
        if name not in self.phones:
            self.phones[name] = PhoneOptions()
        return self.phones[name]

    def display_name(self, name: str) -> str:
        opt = self.phones.get(name)
        return (opt.display_name.strip() if opt else "") or default_display_name(name)


def _from_dict(cls, data):
    """Cria o dataclass ignorando chaves desconhecidas e tipos inválidos."""
    if not isinstance(data, dict):
        return cls()
    obj = cls()
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        current = getattr(obj, f.name)
        if f.name == "defaults":
            value = _from_dict(NewPhoneDefaults, value)
        elif f.name == "phones":
            value = {
                str(k): _from_dict(PhoneOptions, v)
                for k, v in (value or {}).items()
                if isinstance(v, dict)
            }
        elif isinstance(current, bool):
            value = bool(value)
        elif isinstance(current, int):
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        elif isinstance(current, list):
            value = [str(x) for x in value] if isinstance(value, list) else current
        elif isinstance(current, str):
            value = "" if value is None else str(value)
        setattr(obj, f.name, value)
    return obj


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (app_data_dir() / "settings.json")
        self._lock = threading.RLock()
        self.settings = self._load()

    def _load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return _from_dict(Settings, data)
        except Exception:
            log.exception("settings.json inválido; guardando cópia e usando padrões")
            try:
                self.path.replace(self.path.with_suffix(".json.invalido"))
            except OSError:
                pass
            return Settings()

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(asdict(self.settings), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
