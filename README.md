# Duplikat-Finder

Findet exakt gleiche Fotos und Videos in einem Ordner (inklusive Unterordner) und räumt sie sicher auf.

## Herunterladen

Unter **Releases → Duplikat-Finder (neueste Version)** die passende Datei laden:

| System | Datei | Starten |
|---|---|---|
| Windows 10/11 (64 Bit) | `Duplikat-Finder.exe` | Doppelklick. Bei „Der Computer wurde durch Windows geschützt“: **Weitere Informationen → Trotzdem ausführen**. |
| macOS (Apple Silicon, M1 und neuer) | `Duplikat-Finder-macOS.zip` | Entpacken, `Duplikat-Finder.app` in „Programme“ ziehen. Beim ersten Mal **Rechtsklick → Öffnen** (die App ist nicht von Apple signiert). |
| Linux (64 Bit) | `Duplikat-Finder-Linux.tar.gz` | Entpacken und `./Duplikat-Finder` starten. |

Nur unter Windows: OneDrive-Dateien, die nur in der Cloud liegen, werden erkannt und übersprungen, und vor „Backup in den Papierkorb“ wird geprüft, ob das Laufwerk einen Papierkorb hat.

![Schritt 3: Prüfen](screenshots/3_pruefen.png)

## So funktioniert es

1. **Ordner** wählen.
2. **Suchen:** zuerst nach Dateigröße, dann die ersten 64 KB, dann der ganze Inhalt (SHA-256). Nur exakt gleiche Dateien zählen.
   Dateien, die nur in der OneDrive-Cloud liegen, werden übersprungen, damit nichts heruntergeladen wird.
3. **Prüfen:** pro Gruppe festlegen, welche Datei bleibt (kürzester Pfad, älteste Datei oder selbst wählen).
4. **Aufräumen:** Duplikate werden nicht gelöscht, sondern nach `_Duplikat-Backup\<Datum_Uhrzeit>` im gewählten Ordner verschoben.
   Es wird nie etwas überschrieben. „Rückgängig machen“ legt alles zurück. Erst wenn alles passt, das Backup in den Papierkorb schieben.

## Entwickeln

```
pip install -r requirements.txt pytest
python -m pytest
python app.py
```

Die Apps für Windows, macOS und Linux baut GitHub Actions automatisch bei jedem Push auf `main` (`.github/workflows/build.yml`) und testet vorher alles auf allen drei Systemen.
Lokal unter Windows geht es auch mit `build_exe.bat`.
