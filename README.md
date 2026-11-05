# Duplikat-Finder

Findet exakt gleiche Fotos und Videos in einem Ordner (inklusive Unterordner) und räumt sie sicher auf.

## Herunterladen

Unter **Releases → Duplikat-Finder (neueste Version)** die Datei `Duplikat-Finder.exe` laden und doppelklicken.
Windows zeigt beim ersten Start eventuell „Der Computer wurde durch Windows geschützt“, weil die App nicht signiert ist:
**Weitere Informationen → Trotzdem ausführen**.

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

Die `.exe` baut GitHub Actions automatisch bei jedem Push auf `main` (`.github/workflows/build.yml`).
Lokal unter Windows geht es auch mit `build_exe.bat`.
