"""Aufräumen mit Backup: Duplikate werden nie sofort gelöscht.

Ablauf:
1. Jede zu entfernende Datei wird in einen Backup-Ordner verschoben
   (<gewählter Ordner>\\_Duplikat-Backup\\<Datum_Uhrzeit>\\...), die Unterordner-Struktur bleibt gleich.
2. Vor jeder Verschiebung wird sie in protokoll.jsonl angekündigt, danach bestätigt. So kann
   "Wiederherstellen" alles zurücklegen, auch wenn das Programm mittendrin abstürzt.
   Pfade stehen relativ zum gewählten Ordner drin, ein neuer Laufwerksbuchstabe stört also nicht.
3. Erst wenn du zufrieden bist, kannst du den Backup-Ordner in den Papierkorb schieben.

Sicherheitsregeln:
- Eine Datei wird nur verschoben, wenn sie und das Original der Gruppe seit der Suche
  unverändert sind (Größe und Änderungszeit) und das Original noch existiert.
- Pro Gruppe bleibt immer mindestens eine Datei liegen.
- Es wird nie etwas überschrieben, weder im Backup noch beim Zurücklegen.
- Verknüpfungen (Symlinks) und Dateien außerhalb des gewählten Ordners werden nicht angefasst.
- Wiederherstellen löscht nur leere Ordner und die eigenen Protokoll-Dateien, nie Fotos.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from duplikat_kern import BACKUP_ORDNERNAME

PROTOKOLL = "protokoll.jsonl"
LIESMICH = "LIESMICH.txt"
REGEL_KUERZESTER_PFAD = "kuerzester_pfad"
REGEL_AELTESTE = "aelteste"


def _erstellt(st: os.stat_result) -> float:
    """Erstellzeit der Datei. Eine Kopie bekommt eine neue, das Original behält die alte."""
    geburt = getattr(st, "st_birthtime", None)
    if geburt is not None:
        return geburt
    if sys.platform == "win32":
        return st.st_ctime  # unter Windows vor Python 3.12 = Erstellzeit
    return st.st_mtime


def waehle_original(gruppe: list[Path], regel: str) -> int:
    """Index der Datei, die in der Gruppe bleiben soll."""
    if regel == REGEL_AELTESTE:
        def alter(i: int):
            try:
                st = gruppe[i].stat()
                return (min(_erstellt(st), st.st_mtime), len(str(gruppe[i])))
            except OSError:
                return (float("inf"), 0)
        return min(range(len(gruppe)), key=alter)
    return min(range(len(gruppe)), key=lambda i: (len(str(gruppe[i])), str(gruppe[i]).lower()))


@dataclass
class Eintrag:
    entfernen: Path
    behalten: Path
    stand_entfernen: tuple[int, int] | None = None  # (Größe, mtime_ns) bei der Suche
    stand_behalten: tuple[int, int] | None = None


@dataclass
class Plan:
    basis: Path
    eintraege: list[Eintrag] = field(default_factory=list)

    @property
    def bytes_gesamt(self) -> int:
        summe = 0
        for e in self.eintraege:
            if e.stand_entfernen:
                summe += e.stand_entfernen[0]
            else:
                try:
                    summe += e.entfernen.stat().st_size
                except OSError:
                    pass
        return summe


def erstelle_plan(basis: Path, gruppen: list[list[Path]], behalten_index: list[int],
                  stand: dict[Path, tuple[int, int]] | None = None) -> Plan:
    stand = stand or {}
    plan = Plan(Path(basis))
    for gruppe, idx in zip(gruppen, behalten_index):
        original = gruppe[idx]
        for i, pfad in enumerate(gruppe):
            if i != idx:
                plan.eintraege.append(Eintrag(pfad, original, stand.get(pfad), stand.get(original)))
    return plan


@dataclass
class AufraeumErgebnis:
    backup_ordner: Path
    verschoben: int = 0
    bytes_verschoben: int = 0
    fehler: list[tuple[Path, str]] = field(default_factory=list)


def _absolut(p: Path) -> Path:
    return Path(os.path.abspath(p))  # ohne Verknüpfungen aufzulösen


def _innerhalb(pfad: Path, basis: Path) -> Path | None:
    """Pfad relativ zur Basis, oder None wenn er außerhalb liegt (ohne Groß/Klein unter Windows)."""
    a, b = os.path.normcase(str(pfad)), os.path.normcase(str(basis))
    try:
        if os.path.commonpath([a, b]) != b:
            return None
    except ValueError:  # anderes Laufwerk
        return None
    return Path(os.path.relpath(str(pfad), str(basis)))


def _stand(p: Path) -> tuple[int, int]:
    st = p.lstat()
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValueError("Ist eine Verknüpfung oder keine normale Datei")
    return (st.st_size, st.st_mtime_ns)


def neuer_backup_ordner(basis: Path) -> Path:
    stempel = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    ziel = Path(basis) / BACKUP_ORDNERNAME / stempel
    n = 2
    while ziel.exists():
        ziel = Path(basis) / BACKUP_ORDNERNAME / f"{stempel}_{n}"
        n += 1
    return ziel


def _schreibe(log, daten: dict) -> None:
    log.write(json.dumps(daten, ensure_ascii=True) + "\n")  # ASCII: jeder Dateiname lässt sich speichern
    log.flush()
    os.fsync(log.fileno())


def in_backup_verschieben(plan: Plan, fortschritt: Callable[[int, int], None] | None = None,
                          backup_ordner: Path | None = None) -> AufraeumErgebnis:
    basis = _absolut(plan.basis)
    backup = backup_ordner or neuer_backup_ordner(basis)
    backup.mkdir(parents=True, exist_ok=False)
    (backup / LIESMICH).write_text(
        "Diese Dateien waren Duplikate und wurden vom Duplikat-Finder hierher verschoben.\n"
        "Das Original jeder Datei liegt noch an seinem Platz.\n"
        "Zum Zurücklegen im Programm auf 'Rückgängig machen' bzw. 'Wiederherstellen' klicken.\n"
        "Wenn alles passt, kannst du diesen Ordner löschen.\n", encoding="utf-8")
    ergebnis = AufraeumErgebnis(backup)
    gesamt = len(plan.eintraege)

    with open(backup / PROTOKOLL, "a", encoding="utf-8") as log:
        for nr, e in enumerate(plan.eintraege, 1):
            try:
                quelle, original = _absolut(e.entfernen), _absolut(e.behalten)
                relativ = _innerhalb(quelle, basis)
                if relativ is None:
                    raise ValueError("Liegt außerhalb des gewählten Ordners")
                if os.path.normcase(str(quelle)) == os.path.normcase(str(original)):
                    raise ValueError("Original und Duplikat sind dieselbe Datei")
                if not original.is_file():
                    raise FileNotFoundError(f"Original fehlt: {original}")
                jetzt_q, jetzt_o = _stand(quelle), _stand(original)
                if jetzt_q[0] != jetzt_o[0]:
                    raise ValueError("Original und Duplikat sind nicht mehr gleich groß")
                if (e.stand_entfernen and jetzt_q != e.stand_entfernen) or \
                   (e.stand_behalten and jetzt_o != e.stand_behalten):
                    raise ValueError("Datei hat sich seit der Suche verändert")
                ziel = backup / relativ
                if ziel.exists():
                    raise FileExistsError("Im Backup liegt schon eine Datei mit diesem Namen")
                _schreibe(log, {"art": "geplant", "original": str(relativ), "backup": str(relativ),
                                "behalten": str(_innerhalb(original, basis) or original), "bytes": jetzt_q[0]})
                ziel.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(quelle), str(ziel))
                _schreibe(log, {"art": "erledigt", "original": str(relativ)})
                ergebnis.verschoben += 1
                ergebnis.bytes_verschoben += jetzt_q[0]
            except Exception as ex:  # eine kaputte Datei soll den Rest nicht stoppen
                ergebnis.fehler.append((e.entfernen, str(ex)))
            if fortschritt:
                fortschritt(nr, gesamt)

    if ergebnis.verschoben == 0:
        _aufraeumen_wenn_leer(backup)
    return ergebnis


def _protokoll_lesen(backup_ordner: Path) -> tuple[list[dict], int]:
    """Geplante Verschiebungen aus dem Protokoll und Anzahl kaputter Zeilen."""
    eintraege, kaputt = [], 0
    protokoll = backup_ordner / PROTOKOLL
    if not protokoll.is_file():
        return [], 0
    for zeile in protokoll.read_text(encoding="utf-8", errors="replace").splitlines():
        if not zeile.strip():
            continue
        try:
            d = json.loads(zeile)
        except json.JSONDecodeError:
            kaputt += 1
            continue
        if d.get("art", "geplant") == "geplant" and "original" in d and "backup" in d:
            eintraege.append(d)
    return eintraege, kaputt


def _aufraeumen_wenn_leer(backup_ordner: Path) -> bool:
    """Entfernt eigene Dateien und leere Ordner. Liegt noch irgendetwas anderes drin, bleibt alles."""
    for _wurzel, _ordner, dateien in os.walk(backup_ordner):
        if any(d not in (PROTOKOLL, LIESMICH) for d in dateien) or _wurzel != str(backup_ordner) and dateien:
            return False
    for name in (PROTOKOLL, LIESMICH):
        try:
            (backup_ordner / name).unlink()
        except FileNotFoundError:
            pass
    for wurzel, _ordner, _dateien in sorted(os.walk(backup_ordner), key=lambda t: -len(t[0])):
        try:
            os.rmdir(wurzel)  # rmdir löscht nur leere Ordner
        except OSError:
            pass
    oberordner = backup_ordner.parent
    try:
        if oberordner.name == BACKUP_ORDNERNAME and not any(oberordner.iterdir()):
            oberordner.rmdir()
    except OSError:
        pass
    return not backup_ordner.exists()


@dataclass
class WiederherstellErgebnis:
    wiederhergestellt: int = 0
    fehler: list[tuple[Path, str]] = field(default_factory=list)
    kaputte_zeilen: int = 0


def wiederherstellen(backup_ordner: Path) -> WiederherstellErgebnis:
    backup_ordner = _absolut(backup_ordner)
    basis = backup_ordner.parent.parent  # <Basis>\_Duplikat-Backup\<Datum>
    ergebnis = WiederherstellErgebnis()
    eintraege, ergebnis.kaputte_zeilen = _protokoll_lesen(backup_ordner)
    if not eintraege and not (backup_ordner / PROTOKOLL).is_file():
        ergebnis.fehler.append((backup_ordner / PROTOKOLL, "Kein Protokoll gefunden"))
        return ergebnis
    for d in eintraege:
        quelle = backup_ordner / d["backup"]
        ziel = Path(d["original"])
        if not ziel.is_absolute():
            ziel = basis / ziel
        try:
            if not quelle.exists():
                continue  # nie verschoben worden oder schon zurückgelegt
            if ziel.exists():
                raise FileExistsError("Am alten Platz liegt schon eine andere Datei")
            ziel.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(quelle), str(ziel))
            ergebnis.wiederhergestellt += 1
        except Exception as ex:
            ergebnis.fehler.append((ziel, str(ex)))
    if not ergebnis.fehler and not ergebnis.kaputte_zeilen:
        _aufraeumen_wenn_leer(backup_ordner)
    return ergebnis


@dataclass
class BackupInfo:
    ordner: Path
    anzahl: int
    bytes: int


def backups_auflisten(basis: Path) -> list[BackupInfo]:
    wurzel = Path(basis) / BACKUP_ORDNERNAME
    infos = []
    try:
        ordner_liste = sorted((o for o in wurzel.iterdir() if o.is_dir()), reverse=True)
    except OSError:
        return []
    for ordner in ordner_liste:
        try:
            eintraege, _ = _protokoll_lesen(ordner)
        except OSError:
            continue
        noch_da = [d for d in eintraege if (ordner / d["backup"]).exists()]
        if noch_da:
            infos.append(BackupInfo(ordner, len(noch_da), sum(d.get("bytes", 0) for d in noch_da)))
    return infos


def papierkorb_moeglich(pfad: Path) -> bool:
    """Unter Windows hat nur eine fest eingebaute Festplatte einen Papierkorb.
    Auf USB-Sticks, SD-Karten und Netzlaufwerken würde 'Papierkorb' endgültig löschen."""
    if sys.platform != "win32":
        return True
    import ctypes
    laufwerk = os.path.splitdrive(str(_absolut(pfad)))[0] + "\\"
    if laufwerk.startswith("\\\\"):
        return False  # Netzwerkpfad
    return ctypes.windll.kernel32.GetDriveTypeW(laufwerk) == 3  # DRIVE_FIXED


def backup_in_papierkorb(backup_ordner: Path) -> None:
    from send2trash import send2trash
    backup_ordner = Path(backup_ordner)
    if not papierkorb_moeglich(backup_ordner):
        raise OSError("Dieses Laufwerk hat keinen Papierkorb. Lösch den Backup-Ordner selbst, wenn du sicher bist.")
    send2trash(str(backup_ordner))
    oberordner = backup_ordner.parent
    try:
        if oberordner.name == BACKUP_ORDNERNAME and oberordner.is_dir() and not any(oberordner.iterdir()):
            oberordner.rmdir()
    except OSError:
        pass
