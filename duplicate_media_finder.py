#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from collections import defaultdict
from pathlib import Path


MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".heic",
    ".heif",
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".wmv",
    ".webm",
    ".m4v",
}


def file_hash(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        while chunk := file_handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicates(root: Path) -> dict[str, list[Path]]:
    by_size: dict[int, list[Path]] = defaultdict(list)
    for file_path in root.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in MEDIA_EXTENSIONS:
            by_size[file_path.stat().st_size].append(file_path)

    duplicates: dict[str, list[Path]] = {}
    for files in by_size.values():
        if len(files) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for file_path in files:
            by_hash[file_hash(file_path)].append(file_path)
        for hash_value, grouped_files in by_hash.items():
            if len(grouped_files) > 1:
                duplicates[hash_value] = sorted(grouped_files)
    return duplicates


def delete_duplicates(duplicates: dict[str, list[Path]]) -> int:
    deleted = 0
    for grouped_files in duplicates.values():
        for duplicate in grouped_files[1:]:
            duplicate.unlink()
            deleted += 1
    return deleted


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Findet duplizierte Bilder/Videos und löscht sie optional."
    )
    parser.add_argument(
        "directory",
        type=Path,
        help="Verzeichnis, das rekursiv auf doppelte Medien-Dateien geprüft wird.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Löscht Duplikate (pro Gruppe bleibt die erste Datei erhalten).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = args.directory.resolve()

    if not root.exists() or not root.is_dir():
        parser.error(f"Ungültiges Verzeichnis: {root}")

    duplicates = find_duplicates(root)
    if not duplicates:
        print("Keine Duplikate gefunden.")
        return 0

    duplicate_groups = 0
    duplicate_files = 0
    for grouped_files in duplicates.values():
        duplicate_groups += 1
        duplicate_files += len(grouped_files) - 1
        print("Duplikatgruppe:")
        for file_path in grouped_files:
            print(f"  - {file_path}")

    if args.delete:
        deleted = delete_duplicates(duplicates)
        print(f"\n{deleted} Duplikat-Datei(en) gelöscht.")
    else:
        print("\nNur Anzeige. Für Löschung mit --delete aufrufen.")

    print(
        f"Insgesamt {duplicate_groups} Gruppe(n) mit {duplicate_files} löschbaren Duplikat(en)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
