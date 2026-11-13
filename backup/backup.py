"""Backup e restauração dos celulares.

O backup é uma cópia completa da pasta do AVD (disco de dados, apps, contas, configurações),
feita com o emulador DESLIGADO — é a única forma de garantir uma cópia consistente.

Estrutura:
    <pasta de backups>/<celular>/<AAAA-MM-DD_HH-MM-SS>[_rotulo]/
        manifest.json
        avd.ini
        avd/  (conteúdo da pasta <celular>.avd)

Regras:
- um backup nunca sobrescreve outro (cada um tem pasta própria com data/hora);
- a cópia é feita numa pasta temporária ".incompleto" e só vira backup válido no final;
- a restauração guarda o estado atual como backup automático (por padrão) e desfaz tudo se a cópia falhar.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from config.settings import APP_VERSION
from emulators.avd import AvdStore, read_kv
from utils.system import dir_size, disk_free, human_size

log = logging.getLogger(__name__)

ProgressCb = Callable[[int, int, str], None]
STAMP_FMT = "%Y-%m-%d_%H-%M-%S"
EXCLUDE_DIRS = {"tmpAdbCmds"}
SNAPSHOT_DIR = "snapshots"
CHUNK = 8 * 1024 * 1024


def remove_tree(path: Path, ignore_errors: bool = False) -> None:
    """rmtree que também apaga arquivos somente leitura (o emulador cria alguns, ex.: pstore.bin)."""
    import stat

    def onexc(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            if not ignore_errors:
                raise

    if Path(path).exists():
        shutil.rmtree(path, onexc=onexc)


class BackupError(Exception):
    pass


class Cancelled(BackupError):
    pass


@dataclass
class BackupInfo:
    phone: str
    path: Path
    created: datetime
    label: str = ""
    kind: str = "manual"  # manual | antes_da_restauracao | importado
    size: int = 0
    include_snapshots: bool = False
    android: str = ""
    ram_mb: int = 0

    @property
    def id(self) -> str:
        return self.path.name

    @property
    def kind_text(self) -> str:
        return {
            "manual": "Manual",
            "antes_da_restauracao": "Automático (antes de restaurar)",
            "importado": "Importado",
        }.get(self.kind, self.kind)


def _excluded(rel_parts: tuple[str, ...], include_snapshots: bool) -> bool:
    if not rel_parts:
        return False
    if rel_parts[0] in EXCLUDE_DIRS:
        return True
    if not include_snapshots and rel_parts[0] == SNAPSHOT_DIR:
        return True
    last = rel_parts[-1].lower()
    return last.endswith(".lock") or last.endswith(".tmp")


def _plan_copy(src: Path, include_snapshots: bool = True) -> tuple[list[tuple[Path, Path]], int]:
    files, total = [], 0
    for root, dirs, names in os.walk(src):
        rel_root = Path(root).relative_to(src)
        dirs[:] = [d for d in dirs if not _excluded((rel_root / d).parts, include_snapshots)]
        for n in names:
            rel = rel_root / n
            if _excluded(rel.parts, include_snapshots):
                continue
            p = Path(root) / n
            try:
                size = p.stat().st_size
            except OSError:
                continue
            files.append((p, rel))
            total += size
    return files, total


def _copy_files(files, dst: Path, total: int, progress: ProgressCb | None, cancel: threading.Event | None,
                done_offset: int = 0, grand_total: int | None = None) -> int:
    grand_total = grand_total or total
    done = done_offset
    for src, rel in files:
        if cancel and cancel.is_set():
            raise Cancelled("Operação cancelada.")
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(src, "rb") as fi, open(target, "wb") as fo:
            while True:
                if cancel and cancel.is_set():
                    raise Cancelled("Operação cancelada.")
                buf = fi.read(CHUNK)
                if not buf:
                    break
                fo.write(buf)
                done += len(buf)
                if progress:
                    progress(done, grand_total, str(rel))
        shutil.copystat(src, target)
    return done


def _copy_tree(src: Path, dst: Path, progress, cancel, include_snapshots=True) -> int:
    files, total = _plan_copy(src, include_snapshots)
    _copy_files(files, dst, total, progress, cancel)
    return total


class BackupManager:
    def __init__(self, root: str, avds: AvdStore):
        self.root = Path(root)
        self.avds = avds

    def phone_dir(self, name: str) -> Path:
        return self.root / name

    # ------------------------------------------------------------------ listagem
    def list(self, name: str) -> list[BackupInfo]:
        d = self.phone_dir(name)
        out: list[BackupInfo] = []
        if not d.is_dir():
            return out
        for b in d.iterdir():
            if not b.is_dir() or b.name.endswith(".incompleto"):
                continue
            info = self._read(name, b)
            if info:
                out.append(info)
        out.sort(key=lambda b: b.created, reverse=True)
        return out

    def _read(self, name: str, path: Path) -> BackupInfo | None:
        mf = path / "manifest.json"
        if not mf.is_file() or not (path / "avd" / "config.ini").is_file():
            return None
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(m.get("created_at"))
        except Exception:
            return None
        return BackupInfo(
            phone=name, path=path, created=created, label=m.get("label", ""),
            kind=m.get("kind", "manual"), size=int(m.get("size_bytes", 0)),
            include_snapshots=bool(m.get("include_snapshots")), android=m.get("android", ""),
            ram_mb=int(m.get("ram_mb", 0) or 0),
        )

    def last_backup(self, name: str) -> datetime | None:
        d = self.phone_dir(name)
        if not d.is_dir():
            return None
        best = None
        for b in d.iterdir():
            m = re.match(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", b.name)
            if b.is_dir() and m and not b.name.endswith(".incompleto") and (b / "manifest.json").is_file():
                try:
                    dt = datetime.strptime(m.group(1), STAMP_FMT)
                except ValueError:
                    continue
                best = dt if best is None or dt > best else best
        return best

    def _new_dir(self, name: str, suffix: str = "") -> Path:
        base = datetime.now().strftime(STAMP_FMT)
        safe = re.sub(r"[^\w\-]+", "-", suffix, flags=re.UNICODE).strip("-")[:40]
        stem = f"{base}_{safe}" if safe else base
        d = self.phone_dir(name) / stem
        i = 2
        while d.exists() or d.with_name(d.name + ".incompleto").exists():
            d = self.phone_dir(name) / f"{stem}-{i}"
            i += 1
        return d

    def _write_manifest(self, path: Path, name: str, label: str, kind: str, size: int,
                        include_snapshots: bool, info) -> None:
        manifest = {
            "phone": name,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "label": label,
            "kind": kind,
            "size_bytes": size,
            "include_snapshots": include_snapshots,
            "android": info.android if info else "",
            "api": info.api_level if info else None,
            "ram_mb": info.ram_mb if info else 0,
            "system_image": info.system_image if info else "",
            "source_path": str(info.path) if info else "",
            "manager_version": APP_VERSION,
        }
        (path / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------------ criar
    def create(self, name: str, label: str = "", include_snapshots: bool = False,
               progress: ProgressCb | None = None, cancel: threading.Event | None = None) -> BackupInfo:
        info = self.avds.read(name)
        if not info.exists:
            raise BackupError(f"{name} não existe — nada para copiar.")
        files, total = _plan_copy(info.path, include_snapshots)
        free = disk_free(self.root)
        if free < total * 1.05 + 200 * 1024**2:
            raise BackupError(
                f"Espaço insuficiente na pasta de backups: precisa de {human_size(total)}, livre {human_size(free)}."
            )
        final = self._new_dir(name, label)
        tmp = final.with_name(final.name + ".incompleto")
        tmp.mkdir(parents=True)
        try:
            _copy_files(files, tmp / "avd", total, progress, cancel)
            if info.ini_path.is_file():
                shutil.copy2(info.ini_path, tmp / "avd.ini")
            self._write_manifest(tmp, name, label, "manual", total, include_snapshots, info)
            os.replace(tmp, final)
        except BaseException:
            remove_tree(tmp, ignore_errors=True)
            raise
        log.info("Backup criado: %s (%s)", final, human_size(total))
        return self._read(name, final)

    # ------------------------------------------------------------------ restaurar
    def restore(self, name: str, backup: BackupInfo, keep_current: bool = True,
                progress: ProgressCb | None = None, cancel: threading.Event | None = None,
                sdk: str = "") -> list[str]:
        """Substitui os dados do celular pelo backup. Retorna avisos."""
        warnings: list[str] = []
        src = backup.path / "avd"
        if not (src / "config.ini").is_file():
            raise BackupError("Backup incompleto ou corrompido (avd/config.ini ausente).")
        info = self.avds.read(name)
        current = info.path if info.exists or info.path.exists() else self.avds.default_dir(name)

        need = backup.size or dir_size(src)
        if disk_free(current.parent if current.parent.exists() else self.avds.home) < need * 1.05:
            raise BackupError(f"Espaço insuficiente para restaurar ({human_size(need)} necessários).")

        stamp = datetime.now().strftime(STAMP_FMT)
        holding = current.with_name(f"{current.name}.restaurando-{stamp}")
        moved = False
        if current.exists():
            try:
                os.rename(current, holding)
                moved = True
            except OSError as exc:
                raise BackupError(
                    f"Não foi possível mover os dados atuais (algum arquivo em uso?). Nada foi alterado.\n{exc}"
                ) from exc
        try:
            _copy_tree(src, current, progress, cancel, include_snapshots=True)
        except BaseException:
            remove_tree(current, ignore_errors=True)
            if moved:
                os.rename(holding, current)
            raise

        # .ini do AVD: mantém o atual; se não existir, recria apontando para a pasta atual.
        if not info.ini_path.is_file():
            data = read_kv(backup.path / "avd.ini")
            target = data.get("target", "")
            info.ini_path.write_text(
                f"avd.ini.encoding=UTF-8\npath={current}\npath.rel=avd\\{current.name}\ntarget={target}\n",
                encoding="utf-8",
            )

        # Dados anteriores: viram backup automático ou são removidos (com confirmação prévia na interface).
        if moved:
            if keep_current:
                dest = self._new_dir(name, "antes-da-restauracao")
                try:
                    dest.mkdir(parents=True)
                    shutil.move(str(holding), str(dest / "avd"))
                    self._write_manifest(dest, name, f"Antes de restaurar {backup.id}", "antes_da_restauracao",
                                         dir_size(dest / "avd"), True, info)
                except Exception as exc:
                    log.exception("Falha ao guardar dados anteriores")
                    warnings.append(
                        f"Os dados anteriores não puderam ir para a pasta de backups e ficaram em:\n{holding}\n({exc})"
                    )
            else:
                remove_tree(holding, ignore_errors=True)

        restored = self.avds.read(name)
        sdk_root = sdk or os.environ.get("ANDROID_SDK_ROOT") or ""
        sysdir = restored.config.get("image.sysdir.1", "")
        if sysdir and sdk_root and not (Path(sdk_root) / sysdir).is_dir():
            warnings.append(f"A imagem do sistema usada no backup ({sysdir}) não está instalada no SDK.")
        log.info("Backup %s restaurado em %s", backup.path, current)
        return warnings

    # ------------------------------------------------------------------ exportar / importar / excluir
    def export(self, backup: BackupInfo, dest_dir: str, progress: ProgressCb | None = None,
               cancel: threading.Event | None = None) -> Path:
        dest = Path(dest_dir) / f"{backup.phone}_{backup.id}"
        i = 2
        while dest.exists():  # nunca sobrescreve
            dest = Path(dest_dir) / f"{backup.phone}_{backup.id} ({i})"
            i += 1
        need = backup.size or dir_size(backup.path)
        if disk_free(dest_dir) < need * 1.02:
            raise BackupError(f"Espaço insuficiente no destino ({human_size(need)} necessários).")
        tmp = dest.with_name(dest.name + ".incompleto")
        try:
            _copy_tree(backup.path, tmp, progress, cancel)
            os.replace(tmp, dest)
        except BaseException:
            remove_tree(tmp, ignore_errors=True)
            raise
        return dest

    def import_backup(self, name: str, src_dir: str, progress: ProgressCb | None = None,
                      cancel: threading.Event | None = None) -> BackupInfo:
        src = Path(src_dir)
        if not (src / "manifest.json").is_file() or not (src / "avd" / "config.ini").is_file():
            raise BackupError("A pasta escolhida não é um backup do Android Emulator Manager (falta manifest.json ou avd/).")
        final = self._new_dir(name, "importado")
        tmp = final.with_name(final.name + ".incompleto")
        try:
            _copy_tree(src, tmp, progress, cancel)
            m = json.loads((tmp / "manifest.json").read_text(encoding="utf-8"))
            m["kind"] = "importado"
            m["phone"] = name
            m["created_at"] = datetime.now().isoformat(timespec="seconds")
            m["label"] = (m.get("label") or "") + f" (importado de {src.name})"
            (tmp / "manifest.json").write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, final)
        except BaseException:
            remove_tree(tmp, ignore_errors=True)
            raise
        return self._read(name, final)

    def delete(self, backup: BackupInfo) -> None:
        root = self.root.resolve()
        target = backup.path.resolve()
        if root not in target.parents:
            raise BackupError("Caminho de backup fora da pasta de backups — exclusão recusada.")
        remove_tree(target)
