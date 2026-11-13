"""Execução de comandos externos sem abrir janelas de console."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200

log = logging.getLogger(__name__)


class CommandError(Exception):
    pass


_STRIP_PREFIXES = ("QT_", "QML", "QML2_", "PYSIDE", "SHIBOKEN", "_PYI", "_MEIPASS", "PYTHONHOME", "PYTHONPATH")


def clean_env(base: dict | None = None) -> dict:
    """Ambiente para programas externos, sem herdar o Qt/PyInstaller do gerenciador.

    O Android Emulator também usa Qt: se herdar QT_PLUGIN_PATH (ou QT_QPA_PLATFORM) e as pastas
    do PySide6 no PATH, ele carrega os plugins Qt errados e fecha ao abrir a janela
    ("no Qt platform plugin could be initialized" / "Broken AVD system path").
    """
    import os
    import sys

    env = dict(base if base is not None else os.environ)
    for key in list(env):
        if key.upper().startswith(_STRIP_PREFIXES):
            env.pop(key, None)
    app_dirs = []
    if getattr(sys, "frozen", False):
        app_dirs.append(str(Path(sys.executable).resolve().parent).lower())
    try:
        import PySide6

        app_dirs.append(str(Path(PySide6.__file__).resolve().parent).lower())
    except Exception:  # noqa: BLE001
        pass
    if app_dirs and "PATH" in env:
        env["PATH"] = os.pathsep.join(
            p for p in env["PATH"].split(os.pathsep)
            if p and not any(p.lower().startswith(d) for d in app_dirs)
        )
    return env


def reset_dll_directory() -> None:
    """O executável do PyInstaller define um diretório de DLLs que os processos filhos herdam."""
    import ctypes
    import sys

    if getattr(sys, "frozen", False):
        try:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        except Exception:  # noqa: BLE001
            pass


def run(
    args,
    timeout: float = 60,
    env: dict | None = None,
    input_text: str | None = None,
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess:
    """Executa e captura a saída. Lança CommandError em timeout ou se o programa não existir."""
    args = [str(a) for a in args]
    reset_dll_directory()
    kwargs = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env if env is not None else clean_env(),
        cwd=str(cwd) if cwd else None,
        creationflags=CREATE_NO_WINDOW,
    )
    if input_text is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = input_text
    try:
        return subprocess.run(args, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise CommandError(
            f"O comando demorou mais de {int(timeout)} s e foi interrompido: {Path(args[0]).name} {' '.join(args[1:4])}"
        ) from exc
    except FileNotFoundError as exc:
        raise CommandError(f"Programa não encontrado: {args[0]}") from exc
    except OSError as exc:
        raise CommandError(f"Falha ao executar {Path(args[0]).name}: {exc}") from exc
