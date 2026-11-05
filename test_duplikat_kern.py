import os
from pathlib import Path

from duplikat_kern import SCHNELLTEST_BYTES, suche_duplikate


def schreibe(pfad: Path, daten: bytes) -> Path:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(daten)
    return pfad


def test_findet_exakte_duplikate_auch_in_unterordnern(tmp_path):
    inhalt = os.urandom(5000)
    a = schreibe(tmp_path / "a.jpg", inhalt)
    b = schreibe(tmp_path / "Urlaub" / "kopie.JPG", inhalt)
    schreibe(tmp_path / "anders.jpg", os.urandom(5000))
    erg = suche_duplikate(tmp_path)
    assert len(erg.gruppen) == 1
    assert set(erg.gruppen[0]) == {a, b}
    assert erg.gruppen[0][0] == a  # kürzerer Pfad als Original vorgeschlagen
    assert erg.verschwendete_bytes == 5000


def test_gleicher_anfang_aber_anderes_ende_ist_kein_duplikat(tmp_path):
    anfang = os.urandom(SCHNELLTEST_BYTES)
    schreibe(tmp_path / "v1.mp4", anfang + b"A" * 1000)
    schreibe(tmp_path / "v2.mp4", anfang + b"B" * 1000)
    assert suche_duplikate(tmp_path).gruppen == []


def test_ignoriert_andere_dateien_und_leere(tmp_path):
    schreibe(tmp_path / "x.txt", b"gleich")
    schreibe(tmp_path / "y.txt", b"gleich")
    schreibe(tmp_path / "leer1.png", b"")
    schreibe(tmp_path / "leer2.png", b"")
    erg = suche_duplikate(tmp_path)
    assert erg.gruppen == []
    assert erg.gepruefte_dateien == 0


def test_drei_gleiche_videos(tmp_path):
    inhalt = os.urandom(200_000)
    for n in ("1.mov", "2.mov", "sub/3.mov"):
        schreibe(tmp_path / n, inhalt)
    erg = suche_duplikate(tmp_path)
    assert len(erg.gruppen) == 1 and len(erg.gruppen[0]) == 3
    assert erg.verschwendete_bytes == 400_000
