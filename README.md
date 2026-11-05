# duplikat_finder

Ein kleines CLI-Tool zum Finden (und optionalen Löschen) von duplizierten
Bildern und Videos.

## Nutzung

```bash
python3 /home/runner/work/duplikat_finder/duplikat_finder/duplicate_media_finder.py <VERZEICHNIS>
```

Nur anzeigen:

```bash
python3 /home/runner/work/duplikat_finder/duplikat_finder/duplicate_media_finder.py <VERZEICHNIS>
```

Duplikate löschen (je Gruppe bleibt die erste Datei erhalten):

```bash
python3 /home/runner/work/duplikat_finder/duplikat_finder/duplicate_media_finder.py <VERZEICHNIS> --delete
```