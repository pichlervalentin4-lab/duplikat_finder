import os
import time

from aufraeumen import (REGEL_AELTESTE, REGEL_KUERZESTER_PFAD, backups_auflisten, erstelle_plan,
                        in_backup_verschieben, waehle_original, wiederherstellen)
from duplikat_kern import BACKUP_ORDNERNAME, suche_duplikate


def schreibe(p, daten):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(daten)
    return p


def test_verschieben_und_wiederherstellen(tmp_path):
    inhalt = os.urandom(3000)
    a = schreibe(tmp_path / "a.jpg", inhalt)
    b = schreibe(tmp_path / "Kopien" / "a.jpg", inhalt)
    c = schreibe(tmp_path / "Kopien" / "tief" / "a (1).jpg", inhalt)
    erg = suche_duplikate(tmp_path)
    idx = [waehle_original(g, REGEL_KUERZESTER_PFAD) for g in erg.gruppen]
    plan = erstelle_plan(tmp_path, erg.gruppen, idx)
    assert len(plan.eintraege) == 2 and plan.bytes_gesamt == 6000

    res = in_backup_verschieben(plan)
    assert res.verschoben == 2 and not res.fehler
    assert a.exists() and not b.exists() and not c.exists()
    assert (res.backup_ordner / "Kopien" / "tief" / "a (1).jpg").exists()
    # Backup-Ordner wird bei einer neuen Suche ignoriert
    assert suche_duplikate(tmp_path).gruppen == []
    assert backups_auflisten(tmp_path)[0].anzahl == 2

    w = wiederherstellen(res.backup_ordner)
    assert w.wiederhergestellt == 2 and not w.fehler
    assert a.exists() and b.read_bytes() == inhalt and c.exists()
    assert not (tmp_path / BACKUP_ORDNERNAME).exists()


def test_verschiebt_nichts_wenn_original_fehlt(tmp_path):
    inhalt = os.urandom(1000)
    a = schreibe(tmp_path / "a.png", inhalt)
    b = schreibe(tmp_path / "b.png", inhalt)
    erg = suche_duplikate(tmp_path)
    plan = erstelle_plan(tmp_path, erg.gruppen, [0])
    a.unlink()  # Original verschwindet zwischen Suche und Aufräumen
    res = in_backup_verschieben(plan)
    assert res.verschoben == 0 and len(res.fehler) == 1
    assert b.exists()


def test_verschiebt_nicht_wenn_datei_geaendert(tmp_path):
    inhalt = os.urandom(1000)
    schreibe(tmp_path / "a.png", inhalt)
    b = schreibe(tmp_path / "b.png", inhalt)
    erg = suche_duplikate(tmp_path)
    plan = erstelle_plan(tmp_path, erg.gruppen, [0], erg.stand)
    b.write_bytes(inhalt + b"neu")
    res = in_backup_verschieben(plan)
    assert res.verschoben == 0 and b.exists()


def test_wiederherstellen_ueberschreibt_nichts(tmp_path):
    inhalt = os.urandom(1000)
    schreibe(tmp_path / "a.png", inhalt)
    b = schreibe(tmp_path / "x" / "b.png", inhalt)
    erg = suche_duplikate(tmp_path)
    res = in_backup_verschieben(erstelle_plan(tmp_path, erg.gruppen, [0]))
    b.write_bytes(b"neue Datei mit gleichem Namen")
    w = wiederherstellen(res.backup_ordner)
    assert w.wiederhergestellt == 0 and len(w.fehler) == 1
    assert b.read_bytes() == b"neue Datei mit gleichem Namen"
    assert res.backup_ordner.exists()  # Backup bleibt, weil noch nicht alles zurück ist


def test_aelteste_regel(tmp_path):
    inhalt = os.urandom(500)
    neu = schreibe(tmp_path / "a.jpg", inhalt)
    alt = schreibe(tmp_path / "ganz" / "langer" / "pfad.jpg", inhalt)
    t = time.time()
    os.utime(alt, (t - 10000, t - 10000))
    gruppe = suche_duplikate(tmp_path).gruppen[0]
    assert gruppe[waehle_original(gruppe, REGEL_AELTESTE)] == alt
    assert gruppe[waehle_original(gruppe, REGEL_KUERZESTER_PFAD)] == neu


import json
import shutil
import pytest

from aufraeumen import PROTOKOLL
from duplikat_kern import BACKUP_ORDNERNAME as BN


def _plan(tmp_path):
    erg = suche_duplikate(tmp_path)
    idx = [waehle_original(g, REGEL_KUERZESTER_PFAD) for g in erg.gruppen]
    return erstelle_plan(tmp_path, erg.gruppen, idx, erg.stand)


def test_gleiche_groesse_aber_geaendert_wird_nicht_verschoben(tmp_path):
    inhalt = os.urandom(1000)
    schreibe(tmp_path / "a.png", inhalt)
    b = schreibe(tmp_path / "x" / "b.png", inhalt)
    plan = _plan(tmp_path)
    b.write_bytes(os.urandom(1000))  # gleiche Größe, anderer Inhalt
    os.utime(b, ns=(1, 1))
    res = in_backup_verschieben(plan)
    assert res.verschoben == 0 and b.exists()
    assert not (tmp_path / BN).exists()  # kein leerer Backup-Ordner


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="keine Symlinks")
def test_symlinks_werden_ignoriert(tmp_path):
    aussen = tmp_path / "aussen"
    innen = tmp_path / "innen"
    inhalt = os.urandom(2000)
    ziel = schreibe(aussen / "IMG_0001.JPG", inhalt)
    schreibe(innen / "IMG_0001.JPG", inhalt)
    (innen / "link.jpg").symlink_to(ziel)
    (innen / "ordnerlink").symlink_to(aussen, target_is_directory=True)
    erg = suche_duplikate(innen)
    assert erg.gruppen == []
    assert ziel.exists()


def test_hardlinks_zaehlen_nicht_als_duplikat(tmp_path):
    a = schreibe(tmp_path / "a.jpg", os.urandom(1000))
    os.link(a, tmp_path / "b.jpg")
    assert suche_duplikate(tmp_path).gruppen == []


def test_papierkorb_und_versteckte_ordner_werden_ignoriert(tmp_path):
    inhalt = os.urandom(1000)
    schreibe(tmp_path / "Fotos" / "a.jpg", inhalt)
    schreibe(tmp_path / "$RECYCLE.BIN" / "b.jpg", inhalt)
    schreibe(tmp_path / ".cache" / "c.jpg", inhalt)
    schreibe(tmp_path / "AppData" / "d.jpg", inhalt)
    assert suche_duplikate(tmp_path).gruppen == []


def test_nie_ueberschreiben_im_backup(tmp_path):
    inhalt = os.urandom(1000)
    schreibe(tmp_path / "a.jpg", inhalt)
    b = schreibe(tmp_path / "k" / "b.jpg", inhalt)
    plan = _plan(tmp_path)
    backup = tmp_path / BN / "test"
    schreibe(backup / "k" / "b.jpg", b"schon da")
    shutil.rmtree(backup / "k")
    (backup / "k").mkdir(parents=True)
    (backup / "k" / "b.jpg").write_bytes(b"schon da")
    # Backup-Ordner existiert schon -> mkdir(exist_ok=False) muss scheitern statt zu mischen
    with pytest.raises(FileExistsError):
        in_backup_verschieben(plan, backup_ordner=backup)
    assert b.exists() and (backup / "k" / "b.jpg").read_bytes() == b"schon da"


def test_absturz_nach_ankuendigung_wird_trotzdem_wiederhergestellt(tmp_path):
    inhalt = os.urandom(1000)
    schreibe(tmp_path / "a.jpg", inhalt)
    b = schreibe(tmp_path / "k" / "b.jpg", inhalt)
    res = in_backup_verschieben(_plan(tmp_path))
    # Absturz simulieren: Bestätigungszeile fehlt, letzte Zeile abgeschnitten
    log = res.backup_ordner / PROTOKOLL
    zeilen = log.read_text(encoding="utf-8").splitlines()
    log.write_text(zeilen[0] + "\n" + '{"art": "erled', encoding="utf-8")
    w = wiederherstellen(res.backup_ordner)
    assert w.wiederhergestellt == 1 and w.kaputte_zeilen == 1
    assert b.read_bytes() == inhalt
    # wegen der kaputten Zeile bleibt der (jetzt leere) Backup-Ordner zur Kontrolle stehen
    assert res.backup_ordner.exists()


def test_wiederherstellen_loescht_keine_fremden_dateien(tmp_path):
    inhalt = os.urandom(1000)
    schreibe(tmp_path / "a.jpg", inhalt)
    schreibe(tmp_path / "k" / "b.jpg", inhalt)
    res = in_backup_verschieben(_plan(tmp_path))
    fremd = schreibe(res.backup_ordner / "nicht_im_protokoll.jpg", b"wichtig")
    w = wiederherstellen(res.backup_ordner)
    assert w.wiederhergestellt == 1
    assert fremd.read_bytes() == b"wichtig"


def test_wiederherstellen_nach_ordner_umzug(tmp_path):
    alt = tmp_path / "E_Laufwerk"
    inhalt = os.urandom(1000)
    schreibe(alt / "a.jpg", inhalt)
    schreibe(alt / "k" / "b.jpg", inhalt)
    res = in_backup_verschieben(_plan(alt))
    neu = tmp_path / "F_Laufwerk"
    alt.rename(neu)  # wie ein neuer Laufwerksbuchstabe
    w = wiederherstellen(neu / BN / res.backup_ordner.name)
    assert w.wiederhergestellt == 1 and (neu / "k" / "b.jpg").exists()


def test_protokoll_ist_ascii_auch_bei_umlauten(tmp_path):
    inhalt = os.urandom(1000)
    schreibe(tmp_path / "a.jpg", inhalt)
    schreibe(tmp_path / "Übung ä" / "Bild ß.jpg", inhalt)
    res = in_backup_verschieben(_plan(tmp_path))
    roh = (res.backup_ordner / PROTOKOLL).read_bytes()
    assert roh.isascii()
    assert json.loads(roh.splitlines()[0])["original"].endswith("Bild ß.jpg")
