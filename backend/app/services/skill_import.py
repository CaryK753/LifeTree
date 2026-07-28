"""Bounded and path-safe Skill import helpers."""

from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

MAX_SKILL_BYTES = 2 * 1024 * 1024
TEXT_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".json"}


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return not path.is_absolute() and ".." not in path.parts


def _join_parts(parts: list[tuple[str, bytes]]) -> str:
    total = 0
    rendered: list[str] = []
    for name, raw in parts:
        if not _safe_name(name) or Path(name).suffix.lower() not in TEXT_SUFFIXES:
            continue
        total += len(raw)
        if total > MAX_SKILL_BYTES:
            raise ValueError("Skill content exceeds 2 MiB")
        rendered.append(f"# File: {name}\n\n{raw.decode('utf-8', errors='replace')}")
    if not rendered:
        raise ValueError("No supported text files found")
    return "\n\n".join(rendered)


def import_archive(raw: bytes) -> str:
    if len(raw) > MAX_SKILL_BYTES:
        raise ValueError("Archive exceeds 2 MiB")
    parts: list[tuple[str, bytes]] = []
    bio = io.BytesIO(raw)
    if zipfile.is_zipfile(bio):
        with zipfile.ZipFile(bio) as archive:
            for info in archive.infolist():
                if info.is_dir() or not _safe_name(info.filename):
                    continue
                parts.append((info.filename, archive.read(info)))
    else:
        bio.seek(0)
        try:
            with tarfile.open(fileobj=bio, mode="r:*") as archive:
                for member in archive.getmembers():
                    if member.isfile() and _safe_name(member.name) and not member.issym():
                        handle = archive.extractfile(member)
                        if handle:
                            parts.append((member.name, handle.read()))
        except tarfile.TarError as exc:
            raise ValueError("Unsupported archive format") from exc
    return _join_parts(parts)


def import_file_set(files: list[tuple[str, bytes]]) -> str:
    return _join_parts(files)


def import_github(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
        raise ValueError("Only HTTPS GitHub repository URLs are allowed")
    with tempfile.TemporaryDirectory(prefix="lifetree-skill-") as tmp:
        target = Path(tmp) / "repo"
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--filter=blob:none", "--", url, str(target)],
                check=True, capture_output=True, timeout=30,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise ValueError("Unable to shallow-clone repository") from exc
        parts = [
            (str(path.relative_to(target)), path.read_bytes())
            for path in target.rglob("*")
            if path.is_file() and ".git" not in path.parts and path.suffix.lower() in TEXT_SUFFIXES
        ]
        return _join_parts(parts)
