"""Funções auxiliares de sistema: memória, disco, pastas, tamanhos."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass
class MemoryInfo:
    total: int
    available: int
    percent: float


def memory() -> MemoryInfo:
    vm = psutil.virtual_memory()
    return MemoryInfo(vm.total, vm.available, vm.percent)


def disk_free(path: str | Path) -> int:
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free


def same_drive(a: str | Path, b: str | Path) -> bool:
    return Path(a).resolve().drive.lower() == Path(b).resolve().drive.lower()


def human_size(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            if unit in ("B", "KB"):
                return f"{n:.0f} {unit}"
            return f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return f"{n:.1f} TB"


def dir_size(path: str | Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def open_folder(path: str | Path) -> None:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    os.startfile(str(p))  # noqa: S606 - abre no Explorer


def open_file(path: str | Path) -> None:
    os.startfile(str(path))  # noqa: S606


def select_in_explorer(path: str | Path) -> None:
    subprocess.Popen(["explorer", "/select,", str(path)])
