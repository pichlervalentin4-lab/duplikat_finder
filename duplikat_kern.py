"""Kern des Duplikat-Finders: findet exakt gleiche Foto- und Videodateien.

Ablauf (schnell, auch bei vielen Dateien):
1. Ordner rekursiv durchsuchen, nur Foto-/Videodateien.
2. Nach Dateigröße gruppieren. Unterschiedlich große Dateien können nie gleich sein.
3. Bei gleicher Größe zuerst nur die ersten 64 KB hashen (Schnelltest).
4. Erst wenn das auch gleich ist: ganze Datei mit SHA-256 hashen.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

FOTO_ENDUNGEN = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp",
    ".heic", ".heif", ".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng",
    ".jfif", ".avif", ".orf", ".rw2", ".raf",
}
VIDEO_ENDUNGEN = {
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".m4v", ".3gp", ".mts", ".m2ts", ".webm",
    ".mpg", ".mpeg", ".flv",
}
MEDIEN_ENDUNGEN = FOTO_ENDUNGEN | VIDEO_ENDUNGEN

SCHNELLTEST_BYTES = 64 * 1024
BACKUP_ORDNERNAME = "_Duplikat-Backup"  # wird beim Suchen nie durchsucht
# Ordner, in denen nie gesucht wird (Papierkorb, System, Caches). Vergleich ohne Groß/Klein.
AUSGESCHLOSSENE_ORDNER = {BACKUP_ORDNERNAME.lower(), "$recycle.bin", "system volume information", "appdata"}
# Nur direkt auf dem Laufwerk (z. B. C:\\Windows), damit ein eigener Ordner "Windows" nicht fehlt
AUSGESCHLOSSEN_AUF_LAUFWERK = {"windows", "program files", "program files (x86)", "programdata",
                               "$windows.~bt", "$windows.~ws", "recovery"}
BLOCKGROESSE = 1024 * 1024

# Windows-Attribute für OneDrive-Dateien, die nur in der Cloud liegen.
# Würden wir sie lesen, lädt Windows sie erst komplett herunter.
_ATTR_OFFLINE = 0x1000
_ATTR_RECALL_ON_DATA_ACCESS = 0x400000
_ATTR_RECALL_ON_OPEN = 0x40000
_ATTR_HIDDEN = 0x2
_ATTR_SYSTEM = 0x4

# Fortschritt: (Phase, erledigt, gesamt)
Fortschritt = Callable[[str, int, int], None]


@dataclass
class Ergebnis:
    gruppen: list[list[Path]] = field(default_factory=list)  # jede Gruppe: gleiche Dateien
    gepruefte_dateien: int = 0
    # Stand jeder Datei bei der Suche: (Größe, Änderungszeit in ns). Vor dem Aufräumen wird verglichen.
    stand: dict[Path, tuple[int, int]] = field(default_factory=dict)
    uebersprungen_cloud: list[Path] = field(default_factory=list)
    fehler: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def verschwendete_bytes(self) -> int:
        """Speicher, der frei würde, wenn pro Gruppe nur eine Datei bleibt."""
        summe = 0
        for g in self.gruppen:
            try:
                summe += g[0].stat().st_size * (len(g) - 1)
            except OSError:
                pass
        return summe


def ist_nur_in_cloud(st: os.stat_result) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)  # gibt es nur unter Windows
    return bool(attrs & (_ATTR_OFFLINE | _ATTR_RECALL_ON_DATA_ACCESS | _ATTR_RECALL_ON_OPEN))


def _ordner_ueberspringen(pfad: Path) -> bool:
    name = pfad.name.lower()
    if name in AUSGESCHLOSSENE_ORDNER or name.startswith("."):
        return True
    if name in AUSGESCHLOSSEN_AUF_LAUFWERK and pfad.parent == Path(pfad.anchor):
        return True
    try:
        if pfad.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(pfad)):
            return True  # Verknüpfungen nie folgen, sonst landen fremde Ordner im Ergebnis
        attrs = getattr(pfad.lstat(), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attrs & (_ATTR_HIDDEN | _ATTR_SYSTEM))


def finde_medien(ordner: Path, cloud_ueberspringen: bool, ergebnis: Ergebnis) -> Iterable[tuple[Path, int]]:
    """Liefert (Pfad, Größe) für jede Foto-/Videodatei im Ordner und allen Unterordnern."""
    gesehen: set[tuple[int, int]] = set()  # (Laufwerk, Datei-ID): Hardlinks nur einmal zählen
    for wurzel, unterordner, dateien in os.walk(ordner, onerror=lambda e: ergebnis.fehler.append((Path(e.filename or ""), str(e)))):
        unterordner[:] = [u for u in unterordner if not _ordner_ueberspringen(Path(wurzel) / u)]
        for name in dateien:
            pfad = Path(wurzel) / name
            if pfad.suffix.lower() not in MEDIEN_ENDUNGEN:
                continue
            try:
                st = pfad.lstat()  # lstat: Verknüpfungen nicht folgen
            except OSError as e:
                ergebnis.fehler.append((pfad, str(e)))
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_size == 0:
                continue  # Symlinks, leere Dateien usw.
            if cloud_ueberspringen and ist_nur_in_cloud(st):
                ergebnis.uebersprungen_cloud.append(pfad)
                continue
            if st.st_ino:
                schluessel = (st.st_dev, st.st_ino)
                if schluessel in gesehen:
                    continue  # gleiche Datei unter zweitem Namen (Hardlink), belegt keinen Extra-Platz
                gesehen.add(schluessel)
            ergebnis.stand[pfad] = (st.st_size, st.st_mtime_ns)
            yield pfad, st.st_size


def _hash(pfad: Path, max_bytes: int | None = None) -> str:
    h = hashlib.sha256()
    gelesen = 0
    with open(pfad, "rb") as f:
        while True:
            menge = BLOCKGROESSE if max_bytes is None else min(BLOCKGROESSE, max_bytes - gelesen)
            if menge <= 0:
                break
            block = f.read(menge)
            if not block:
                break
            h.update(block)
            gelesen += len(block)
    return h.hexdigest()


def _gruppieren(kandidaten: list[list[Path]], hashfunktion, phase: str,
                fortschritt: Fortschritt | None, ergebnis: Ergebnis) -> list[list[Path]]:
    gesamt = sum(len(g) for g in kandidaten)
    erledigt = 0
    neue_gruppen: list[list[Path]] = []
    for gruppe in kandidaten:
        nach_hash: dict[str, list[Path]] = defaultdict(list)
        for pfad in gruppe:
            try:
                nach_hash[hashfunktion(pfad)].append(pfad)
            except OSError as e:
                ergebnis.fehler.append((pfad, str(e)))
            erledigt += 1
            if fortschritt:
                fortschritt(phase, erledigt, gesamt)
        neue_gruppen.extend(g for g in nach_hash.values() if len(g) > 1)
    return neue_gruppen


def suche_duplikate(ordner: str | Path, cloud_ueberspringen: bool = True,
                    fortschritt: Fortschritt | None = None) -> Ergebnis:
    ordner = Path(ordner)
    if not ordner.is_dir():
        raise NotADirectoryError(f"Kein Ordner: {ordner}")

    ergebnis = Ergebnis()

    # 1 + 2: Dateien sammeln und nach Größe gruppieren
    nach_groesse: dict[int, list[Path]] = defaultdict(list)
    for pfad, groesse in finde_medien(ordner, cloud_ueberspringen, ergebnis):
        nach_groesse[groesse].append(pfad)
        ergebnis.gepruefte_dateien += 1
        if fortschritt and ergebnis.gepruefte_dateien % 200 == 0:
            fortschritt("Dateien suchen", ergebnis.gepruefte_dateien, 0)
    kandidaten = [g for g in nach_groesse.values() if len(g) > 1]

    # 3: Schnelltest mit den ersten 64 KB
    kandidaten = _gruppieren(kandidaten, lambda p: _hash(p, SCHNELLTEST_BYTES),
                             "Schnelltest", fortschritt, ergebnis)
    # 4: Ganze Datei vergleichen
    gruppen = _gruppieren(kandidaten, _hash, "Vollständiger Vergleich", fortschritt, ergebnis)

    for g in gruppen:
        g.sort(key=lambda p: (len(str(p)), str(p).lower()))  # kürzester Pfad zuerst = Vorschlag "Original"
    def _platz(g: list[Path]) -> int:
        try:
            return g[0].stat().st_size * (len(g) - 1)
        except OSError:
            return 0
    gruppen.sort(key=_platz, reverse=True)  # größte Platzfresser zuerst
    ergebnis.gruppen = gruppen
    return ergebnis


def _menschlich(bytes_: int) -> str:
    wert = float(bytes_)
    for einheit in ("B", "KB", "MB", "GB"):
        if wert < 1024:
            return f"{wert:.1f} {einheit}"
        wert /= 1024
    return f"{wert:.1f} TB"


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Aufruf: python duplikat_kern.py <Ordner>")
        sys.exit(1)
    erg = suche_duplikate(sys.argv[1], fortschritt=lambda ph, a, b: print(f"\r{ph}: {a}/{b or '?'}", end=""))
    print()
    print(f"{erg.gepruefte_dateien} Dateien geprüft, {len(erg.gruppen)} Duplikat-Gruppen, "
          f"{_menschlich(erg.verschwendete_bytes)} doppelt belegt.")
    for i, g in enumerate(erg.gruppen, 1):
        print(f"\nGruppe {i}:")
        for p in g:
            print(f"  {p}")
    if erg.uebersprungen_cloud:
        print(f"\n{len(erg.uebersprungen_cloud)} Dateien übersprungen (nur in OneDrive-Cloud).")
    if erg.fehler:
        print(f"\n{len(erg.fehler)} Dateien konnten nicht gelesen werden.")
