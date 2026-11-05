"""Duplikat-Finder: Fenster im Assistent-Stil (Design C).

Schritt 1 Ordner -> 2 Suchen -> 3 Prüfen -> 4 Aufräumen
Start:  python app.py
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image, ImageOps

from aufraeumen import (REGEL_AELTESTE, REGEL_KUERZESTER_PFAD, backup_in_papierkorb,
                        backups_auflisten, erstelle_plan, in_backup_verschieben,
                        papierkorb_moeglich, waehle_original, wiederherstellen)
from dialoge import Meldungen
from duplikat_kern import FOTO_ENDUNGEN, Ergebnis, suche_duplikate
from stil import (APP_NAME, BG, GRAU, GRUEN, HELLGRAU, KARTE, LILA, LILA_HELL, LILA_HOVER, RAND,
                  ROT, ROT_HOVER, SCHIENE, TEXT, schrift)

GRUPPEN_PRO_SEITE = 12
SCHRITTE = ["1  Ordner", "2  Suchen", "3  Prüfen", "4  Aufräumen"]


def groesse_text(b: float) -> str:
    for einheit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.0f} {einheit}" if einheit == "B" else f"{b:.1f} {einheit}".replace(".", ",")
        b /= 1024
    return f"{b:.1f} TB".replace(".", ",")


def zahl(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def ordner_oeffnen(pfad: Path) -> None:
    if sys.platform == "win32":
        os.startfile(pfad)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(pfad)])
    else:
        subprocess.Popen(["xdg-open", str(pfad)])


class Abgebrochen(Exception):
    pass


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__(fg_color=BG)
        ctk.set_appearance_mode("light")
        self.title(APP_NAME)
        self.geometry("920x660")
        self.minsize(820, 600)

        self.f = schrift
        self.meldung = Meldungen(self)

        self.ordner: Path | None = None
        self.cloud_ueberspringen = ctk.BooleanVar(value=True)
        self.ergebnis: Ergebnis | None = None
        self.behalten: list[int] = []
        self.regel = ctk.StringVar(value=REGEL_KUERZESTER_PFAD)
        self.seite_nr = 0
        self.letztes_backup: Path | None = None
        self._queue: queue.Queue = queue.Queue()
        self._abbrechen = threading.Event()
        self._such_id = 0          # jede Suche hat eine eigene Nummer, alte Ergebnisse werden verworfen
        self._raeumt_auf = False
        self.protocol("WM_DELETE_WINDOW", self._schliessen)
        self._bilder: list[ctk.CTkImage] = []  # Referenzen halten, sonst verschwinden Vorschauen

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._baue_schrittleiste()
        self.inhalt = ctk.CTkFrame(self, fg_color=BG)
        self.inhalt.grid(row=1, column=0, sticky="nsew", padx=28, pady=(18, 0))
        self._baue_navigation()
        self.zeige_schritt(0)

    def _schliessen(self) -> None:
        if self._raeumt_auf:
            self.meldung.warnung("Aufräumen läuft noch",
                                 "Bitte warte, bis das Aufräumen fertig ist. Sonst bleiben Dateien halb verschoben.")
            return
        self._abbrechen.set()
        self.destroy()

    # ---------- Rahmen ----------
    def _baue_schrittleiste(self) -> None:
        leiste = ctk.CTkFrame(self, fg_color=BG)
        leiste.grid(row=0, column=0, sticky="ew", padx=28, pady=(16, 0))
        self.schritt_teile = []
        for i, name in enumerate(SCHRITTE):
            leiste.grid_columnconfigure(i, weight=1, uniform="s")
            balken = ctk.CTkProgressBar(leiste, height=4, corner_radius=2, fg_color=SCHIENE, progress_color=LILA)
            balken.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            text = ctk.CTkLabel(leiste, text=name, font=self.f(12), text_color=HELLGRAU, anchor="w")
            text.grid(row=1, column=i, sticky="w", padx=(0 if i == 0 else 8, 0), pady=(4, 0))
            self.schritt_teile.append((balken, text))

    def _baue_navigation(self) -> None:
        nav = ctk.CTkFrame(self, fg_color=KARTE, corner_radius=0, border_width=0, height=64)
        nav.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        nav.grid_columnconfigure(1, weight=1)
        self.zurueck_btn = ctk.CTkButton(nav, text="← Zurück", width=110, height=38, fg_color="transparent",
                                         text_color=GRAU, hover_color=BG, font=self.f(13), command=self.zurueck)
        self.zurueck_btn.grid(row=0, column=0, padx=28, pady=13)
        self.weiter_btn = ctk.CTkButton(nav, text="Weiter →", height=38, corner_radius=8, fg_color=LILA,
                                        hover_color=LILA_HOVER, font=self.f(13, "bold"), command=self.weiter)
        self.weiter_btn.grid(row=0, column=2, padx=28, pady=13)

    def zeige_schritt(self, nr: int) -> None:
        self.schritt = nr
        for i, (balken, text) in enumerate(self.schritt_teile):
            balken.set(1 if i < nr else (0.6 if i == nr else 0))
            text.configure(text_color=LILA if i == nr else (TEXT if i < nr else HELLGRAU),
                           font=self.f(12, "bold" if i == nr else "normal"))
        for w in self.inhalt.winfo_children():
            w.destroy()
        self._bilder.clear()
        self.zurueck_btn.configure(text="← Zurück", command=self.zurueck)
        [self._seite_ordner, self._seite_suchen, self._seite_pruefen, self._seite_aufraeumen][nr]()

    def _titel(self, eltern, titel: str, text: str) -> None:
        ctk.CTkLabel(eltern, text=titel, font=self.f(22, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(eltern, text=text, font=self.f(13), text_color=GRAU, anchor="w", justify="left",
                     wraplength=760).pack(anchor="w", pady=(4, 16))

    def _nav(self, zurueck: bool, weiter_text: str | None, weiter_aktiv: bool = True, gefahr: bool = False) -> None:
        self.zurueck_btn.configure(state="normal" if zurueck else "disabled",
                                   text_color=GRAU if zurueck else SCHIENE)
        if weiter_text is None:
            self.weiter_btn.grid_remove()
        else:
            self.weiter_btn.grid()
            self.weiter_btn.configure(text=weiter_text, state="normal" if weiter_aktiv else "disabled",
                                      fg_color=ROT if gefahr else LILA,
                                      hover_color=ROT_HOVER if gefahr else LILA_HOVER)

    def zurueck(self) -> None:
        if self.schritt == 1:
            self._abbrechen.set()
            self._such_id += 1
        self.zeige_schritt(max(0, self.schritt - 1 if self.schritt != 2 else 0))

    def weiter(self) -> None:
        if self.schritt == 3:
            self._starte_aufraeumen()
        elif self.schritt == 4:
            pass
        else:
            self.zeige_schritt(self.schritt + 1)

    # ---------- Schritt 1: Ordner ----------
    def _seite_ordner(self) -> None:
        s = self.inhalt
        self._titel(s, "Welchen Ordner willst du prüfen?",
                    "Alle Unterordner werden mit durchsucht. Es werden nur Fotos und Videos verglichen, "
                    "und nur Dateien mit exakt gleichem Inhalt zählen als doppelt.")
        karte = ctk.CTkFrame(s, fg_color=KARTE, border_color=RAND, border_width=1, corner_radius=12)
        karte.pack(fill="x")
        karte.grid_columnconfigure(0, weight=1)
        self.pfad_label = ctk.CTkLabel(karte, text=str(self.ordner) if self.ordner else "Noch kein Ordner gewählt",
                                       font=self.f(14, "bold" if self.ordner else "normal"),
                                       text_color=TEXT if self.ordner else HELLGRAU, anchor="w")
        self.pfad_label.grid(row=0, column=0, sticky="ew", padx=18, pady=18)
        ctk.CTkButton(karte, text="Ordner wählen…", height=38, corner_radius=8, fg_color=LILA_HELL,
                      text_color=LILA, hover_color="#d9d4fb", font=self.f(13, "bold"),
                      command=self._ordner_waehlen).grid(row=0, column=1, padx=18)

        ctk.CTkCheckBox(s, text="Dateien überspringen, die nur in der OneDrive-Cloud liegen (sonst werden sie heruntergeladen)",
                        variable=self.cloud_ueberspringen, font=self.f(13), text_color=TEXT,
                        fg_color=LILA, hover_color=LILA_HOVER, border_color="#b8bccc").pack(anchor="w", pady=(16, 0))

        if self.ordner:
            backups = backups_auflisten(self.ordner)
            if backups:
                b = backups[0]
                info = ctk.CTkFrame(s, fg_color=LILA_HELL, corner_radius=10)
                info.pack(fill="x", pady=(20, 0))
                ctk.CTkLabel(info, text=f"In diesem Ordner gibt es {len(backups)} Backup(s). Das neueste: "
                                        f"{b.ordner.name}, {zahl(b.anzahl)} Dateien, {groesse_text(b.bytes)}.",
                             font=self.f(13), text_color=TEXT, anchor="w").pack(side="left", padx=14, pady=10)
                ctk.CTkButton(info, text="Wiederherstellen", width=130, fg_color=LILA, hover_color=LILA_HOVER,
                              command=lambda: self._wiederherstellen(b.ordner)).pack(side="right", padx=10, pady=8)
        self._nav(False, "Suche starten →", self.ordner is not None)

    def _ordner_waehlen(self) -> None:
        start = str(self.ordner) if self.ordner else str(Path.home() / "Pictures")
        gewaehlt = filedialog.askdirectory(title="Ordner mit Fotos und Videos wählen", initialdir=start)
        if gewaehlt:
            self.ordner = Path(gewaehlt)
            self.zeige_schritt(0)

    # ---------- Schritt 2: Suchen ----------
    def _seite_suchen(self) -> None:
        s = self.inhalt
        self._titel(s, "Suche läuft…", f"Ordner: {self.ordner}")
        karte = ctk.CTkFrame(s, fg_color=KARTE, border_color=RAND, border_width=1, corner_radius=12)
        karte.pack(fill="x")
        self.phase_label = ctk.CTkLabel(karte, text="Dateien suchen", font=self.f(15, "bold"), text_color=TEXT, anchor="w")
        self.phase_label.pack(anchor="w", padx=18, pady=(18, 6))
        self.balken = ctk.CTkProgressBar(karte, height=10, corner_radius=5, fg_color=SCHIENE, progress_color=LILA,
                                         mode="indeterminate")
        self.balken.pack(fill="x", padx=18)
        self.balken.start()
        self.zaehler_label = ctk.CTkLabel(karte, text="", font=self.f(12), text_color=GRAU, anchor="w")
        self.zaehler_label.pack(anchor="w", padx=18, pady=(6, 18))
        ctk.CTkLabel(s, text="Zuerst wird nach Dateigröße sortiert, dann die ersten 64 KB verglichen und erst "
                             "zum Schluss der ganze Inhalt (SHA-256). Darum geht es meistens schnell.",
                     font=self.f(12), text_color=HELLGRAU, wraplength=760, justify="left").pack(anchor="w", pady=(12, 0))
        self._nav(True, "Weiter →", False)
        self.zurueck_btn.configure(text="Abbrechen")

        self._abbrechen.set()                 # eine eventuell noch laufende alte Suche stoppen
        self._abbrechen = abbrechen = threading.Event()
        self._such_id += 1
        such_id = self._such_id
        ordner, cloud = self.ordner, self.cloud_ueberspringen.get()

        def melden(phase: str, a: int, b: int) -> None:
            if abbrechen.is_set():
                raise Abgebrochen()
            self._queue.put((such_id, "fortschritt", phase, a, b))

        def arbeit() -> None:
            try:
                self._queue.put((such_id, "fertig", suche_duplikate(ordner, cloud, melden)))
            except Abgebrochen:
                self._queue.put((such_id, "abgebrochen"))
            except Exception as ex:
                self._queue.put((such_id, "fehler", str(ex)))

        threading.Thread(target=arbeit, daemon=True).start()
        self.after(100, self._queue_lesen)

    def _queue_lesen(self) -> None:
        try:
            while True:
                such_id, *nachricht = self._queue.get_nowait()
                art = nachricht[0]
                if self.schritt != 1 or such_id != self._such_id:
                    continue  # Nachricht einer alten, abgebrochenen Suche
                if art == "fortschritt":
                    _, phase, a, b = nachricht
                    self.phase_label.configure(text=phase)
                    if b:
                        if self.balken.cget("mode") != "determinate":
                            self.balken.stop()
                            self.balken.configure(mode="determinate")
                        self.balken.set(a / b)
                        self.zaehler_label.configure(text=f"{zahl(a)} von {zahl(b)} Dateien")
                    else:
                        self.zaehler_label.configure(text=f"{zahl(a)} Fotos und Videos gefunden")
                elif art == "fertig":
                    self._suche_fertig(nachricht[1])
                    return
                elif art == "fehler":
                    self.meldung.fehler("Die Suche ist fehlgeschlagen", str(nachricht[1]))
                    self.zeige_schritt(0)
                    return
                elif art == "abgebrochen":
                    return
        except queue.Empty:
            pass
        if self.schritt == 1:
            self.after(100, self._queue_lesen)

    def _suche_fertig(self, ergebnis: Ergebnis) -> None:
        self.ergebnis = ergebnis
        self.balken.stop()
        self.balken.configure(mode="determinate")
        self.balken.set(1)
        self.zurueck_btn.configure(text="← Zurück")
        self.behalten = [waehle_original(g, self.regel.get()) for g in ergebnis.gruppen]
        self.seite_nr = 0
        if ergebnis.gruppen:
            self.phase_label.configure(text=f"Fertig: {zahl(len(ergebnis.gruppen))} Duplikat-Gruppen gefunden")
            self.zaehler_label.configure(text=f"{zahl(ergebnis.gepruefte_dateien)} Dateien geprüft, "
                                              f"{groesse_text(ergebnis.verschwendete_bytes)} doppelt belegt")
            self._nav(True, "Weiter zum Prüfen →")
        else:
            self.phase_label.configure(text="Keine Duplikate gefunden")
            self.zaehler_label.configure(text=f"{zahl(ergebnis.gepruefte_dateien)} Dateien geprüft, alles ist nur einmal da.")
            self._nav(True, None)
        if ergebnis.fehler:
            self.zaehler_label.configure(text=self.zaehler_label.cget("text") +
                                         f" · {zahl(len(ergebnis.fehler))} Dateien nicht lesbar")

    # ---------- Schritt 3: Prüfen ----------
    def _seite_pruefen(self) -> None:
        s = self.inhalt
        erg = self.ergebnis
        oben = ctk.CTkFrame(s, fg_color=BG)
        oben.pack(fill="x")
        oben.grid_columnconfigure(0, weight=3)
        oben.grid_columnconfigure(1, weight=2)

        links = ctk.CTkFrame(oben, fg_color=BG)
        links.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        self._titel(links, "Welche Datei soll bleiben?",
                    f"Gilt für alle {zahl(len(erg.gruppen))} Gruppen. Unten kannst du einzelne Gruppen ändern.")
        optionen = [(REGEL_KUERZESTER_PFAD, "Kürzester Pfad", "Meist der richtige Ordner, nicht „Kopie von…“"),
                    (REGEL_AELTESTE, "Älteste Datei", "Nach Änderungsdatum"),
                    ("selbst", "Ich wähle selbst", "Unten bei jeder Gruppe anklicken")]
        for wert, titel, text in optionen:
            ctk.CTkRadioButton(links, text=f"{titel}   ·   {text}", variable=self.regel, value=wert,
                               font=self.f(13), text_color=TEXT, fg_color=LILA, hover_color=LILA_HOVER,
                               border_color="#b8bccc", command=self._regel_geaendert).pack(anchor="w", pady=4)

        self.summe = ctk.CTkFrame(oben, fg_color=KARTE, border_color=RAND, border_width=1, corner_radius=12)
        self.summe.grid(row=0, column=1, sticky="nsew")
        self._summe_zeichnen()

        self.liste = ctk.CTkScrollableFrame(s, fg_color=KARTE, border_color=RAND, border_width=1, corner_radius=12)
        self.liste.pack(fill="both", expand=True, pady=(14, 0))
        self._liste_zeichnen()
        self._nav(True, "Weiter zum Aufräumen →")

    def _plan(self):
        return erstelle_plan(self.ordner, self.ergebnis.gruppen, self.behalten, self.ergebnis.stand)

    def _summe_zeichnen(self) -> None:
        for w in self.summe.winfo_children():
            w.destroy()
        erg = self.ergebnis
        plan = self._plan()
        ctk.CTkLabel(self.summe, text=groesse_text(plan.bytes_gesamt), font=self.f(34, "bold"),
                     text_color=LILA, anchor="w").pack(anchor="w", padx=18, pady=(16, 0))
        ctk.CTkLabel(self.summe, text="können frei werden", font=self.f(13), text_color=GRAU).pack(anchor="w", padx=18)
        for k, v in [("Geprüfte Dateien", zahl(erg.gepruefte_dateien)),
                     ("Duplikat-Gruppen", zahl(len(erg.gruppen))),
                     ("Zu entfernen", f"{zahl(len(plan.eintraege))} Dateien"),
                     ("Nur in OneDrive (übersprungen)", zahl(len(erg.uebersprungen_cloud)))]:
            zeile = ctk.CTkFrame(self.summe, fg_color=KARTE)
            zeile.pack(fill="x", padx=18, pady=(6, 0))
            ctk.CTkLabel(zeile, text=k, font=self.f(12), text_color=GRAU).pack(side="left")
            ctk.CTkLabel(zeile, text=v, font=self.f(12, "bold"), text_color=TEXT).pack(side="right")
        ctk.CTkFrame(self.summe, fg_color=KARTE, height=12).pack()

    def _regel_geaendert(self) -> None:
        if self.regel.get() != "selbst":
            self.behalten = [waehle_original(g, self.regel.get()) for g in self.ergebnis.gruppen]
            self._liste_zeichnen()
            self._summe_zeichnen()

    def _vorschau(self, pfad: Path) -> ctk.CTkImage | None:
        if pfad.suffix.lower() not in FOTO_ENDUNGEN:
            return None
        try:
            with Image.open(pfad) as bild:
                bild.draft("RGB", (160, 120))  # bei JPEG viel schneller
                bild = ImageOps.exif_transpose(bild).convert("RGB")
                bild = ImageOps.fit(bild, (112, 80))
            img = ctk.CTkImage(light_image=bild, size=(56, 40))
            self._bilder.append(img)
            return img
        except Exception:
            return None

    def _liste_zeichnen(self) -> None:
        for w in self.liste.winfo_children():
            w.destroy()
        self._bilder.clear()
        gruppen = self.ergebnis.gruppen
        seiten = max(1, -(-len(gruppen) // GRUPPEN_PRO_SEITE))
        self.seite_nr = min(self.seite_nr, seiten - 1)
        start = self.seite_nr * GRUPPEN_PRO_SEITE
        for gi in range(start, min(start + GRUPPEN_PRO_SEITE, len(gruppen))):
            self._gruppe_zeichnen(gi, gruppen[gi])
        if seiten > 1:
            fuss = ctk.CTkFrame(self.liste, fg_color=KARTE)
            fuss.pack(fill="x", pady=8)
            ctk.CTkButton(fuss, text="‹ Vorherige", width=100, fg_color=BG, text_color=TEXT, hover_color=SCHIENE,
                          state="normal" if self.seite_nr > 0 else "disabled",
                          command=lambda: self._blaettern(-1)).pack(side="left", padx=8)
            ctk.CTkLabel(fuss, text=f"Gruppen {start + 1}–{min(start + GRUPPEN_PRO_SEITE, len(gruppen))} "
                                    f"von {zahl(len(gruppen))}", font=self.f(12), text_color=GRAU).pack(side="left", expand=True)
            ctk.CTkButton(fuss, text="Nächste ›", width=100, fg_color=BG, text_color=TEXT, hover_color=SCHIENE,
                          state="normal" if self.seite_nr < seiten - 1 else "disabled",
                          command=lambda: self._blaettern(1)).pack(side="right", padx=8)

    def _blaettern(self, richtung: int) -> None:
        self.seite_nr += richtung
        self._liste_zeichnen()
        self.liste._parent_canvas.yview_moveto(0)

    def _gruppe_zeichnen(self, gi: int, gruppe: list[Path]) -> None:
        box = ctk.CTkFrame(self.liste, fg_color=KARTE)
        box.pack(fill="x", padx=6, pady=(8, 2))
        try:
            je = groesse_text(gruppe[0].stat().st_size)
        except OSError:
            je = "?"
        ctk.CTkLabel(box, text=f"Gruppe {gi + 1}  ·  {len(gruppe)} gleiche Dateien  ·  {je} je Datei",
                     font=self.f(12, "bold"), text_color=GRAU).pack(anchor="w", padx=4)
        wahl = ctk.IntVar(value=self.behalten[gi])
        for fi, pfad in enumerate(gruppe):
            bleibt = fi == self.behalten[gi]
            zeile = ctk.CTkFrame(box, fg_color=LILA_HELL if bleibt else BG, corner_radius=8)
            zeile.pack(fill="x", pady=2)
            ctk.CTkRadioButton(zeile, text="", width=24, variable=wahl, value=fi, fg_color=LILA,
                               hover_color=LILA_HOVER, border_color="#b8bccc",
                               command=lambda gi=gi, wahl=wahl: self._manuell(gi, wahl.get())).pack(side="left", padx=(10, 0))
            bild = self._vorschau(pfad)
            ctk.CTkLabel(zeile, text="" if bild else ("▶" if pfad.suffix.lower() not in FOTO_ENDUNGEN else "Foto"),
                         image=bild, width=56, height=40, fg_color=SCHIENE if not bild else "transparent",
                         corner_radius=4, text_color=GRAU).pack(side="left", padx=8, pady=6)
            texte = ctk.CTkFrame(zeile, fg_color="transparent")
            texte.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(texte, text=pfad.name, font=self.f(13, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
            try:
                ort = str(pfad.parent.relative_to(self.ordner)) or "."
            except ValueError:
                ort = str(pfad.parent)
            ctk.CTkLabel(texte, text=ort, font=self.f(11), text_color=GRAU, anchor="w").pack(anchor="w")
            ctk.CTkLabel(zeile, text="bleibt" if bleibt else "wird entfernt", font=self.f(11, "bold"),
                         text_color=GRUEN if bleibt else ROT).pack(side="right", padx=12)

    def _manuell(self, gi: int, fi: int) -> None:
        self.behalten[gi] = fi
        self.regel.set("selbst")
        self._liste_zeichnen()
        self._summe_zeichnen()

    # ---------- Schritt 4: Aufräumen ----------
    def _seite_aufraeumen(self) -> None:
        s = self.inhalt
        plan = self._plan()
        self._titel(s, "Bereit zum Aufräumen",
                    "Es wird nichts gelöscht. Die Duplikate werden in einen Backup-Ordner verschoben, "
                    "das Original jeder Gruppe bleibt an seinem Platz. Mit „Rückgängig machen“ kommt alles zurück.")
        karte = ctk.CTkFrame(s, fg_color=KARTE, border_color=RAND, border_width=1, corner_radius=12)
        karte.pack(fill="x")
        self.auf_titel = ctk.CTkLabel(karte, text=f"{zahl(len(plan.eintraege))} Dateien ({groesse_text(plan.bytes_gesamt)}) "
                                                  f"werden verschoben nach:", font=self.f(15, "bold"), text_color=TEXT)
        self.auf_titel.pack(anchor="w", padx=18, pady=(18, 4))
        self.auf_ziel = ctk.CTkLabel(karte, text=str(self.ordner / "_Duplikat-Backup" / "<Datum_Uhrzeit>"),
                                     font=ctk.CTkFont(family="Consolas", size=12), text_color=GRAU)
        self.auf_ziel.pack(anchor="w", padx=18)
        self.auf_balken = ctk.CTkProgressBar(karte, height=10, corner_radius=5, fg_color=SCHIENE, progress_color=LILA)
        self.auf_balken.set(0)
        self.auf_balken.pack(fill="x", padx=18, pady=(14, 4))
        self.auf_info = ctk.CTkLabel(karte, text="", font=self.f(12), text_color=GRAU)
        self.auf_info.pack(anchor="w", padx=18, pady=(0, 16))
        self.nachher = ctk.CTkFrame(s, fg_color=BG)
        self.nachher.pack(fill="x", pady=(16, 0))
        self._nav(True, "Jetzt aufräumen", bool(plan.eintraege), gefahr=True)

    def _starte_aufraeumen(self) -> None:
        plan = self._plan()
        self._nav(False, "Läuft…", False, gefahr=True)
        self._raeumt_auf = True

        def melden(a: int, b: int) -> None:
            self._queue.put(("aufraeumen", "auf", a, b))

        def arbeit() -> None:
            try:
                self._queue.put(("aufraeumen", "auf_fertig", in_backup_verschieben(plan, melden)))
            except Exception as ex:
                self._queue.put(("aufraeumen", "auf_fehler", str(ex)))

        threading.Thread(target=arbeit, daemon=False).start()
        self.after(100, self._auf_queue)

    def _auf_queue(self) -> None:
        try:
            while True:
                n = self._queue.get_nowait()
                if n[0] != "aufraeumen":
                    continue  # alte Such-Nachricht
                n = n[1:]
                if n[0] == "auf":
                    self.auf_balken.set(n[1] / max(n[2], 1))
                    self.auf_info.configure(text=f"{zahl(n[1])} von {zahl(n[2])} Dateien")
                elif n[0] == "auf_fertig":
                    self._raeumt_auf = False
                    self._aufraeumen_fertig(n[1])
                    return
                elif n[0] == "auf_fehler":
                    self._raeumt_auf = False
                    self.meldung.fehler("Aufräumen ist fehlgeschlagen",
                                        f"{n[1]}\n\nBereits verschobene Dateien liegen sicher im Backup-Ordner.")
                    self._nav(True, "Jetzt aufräumen", True, gefahr=True)
                    return
        except queue.Empty:
            pass
        self.after(100, self._auf_queue)

    def _aufraeumen_fertig(self, res) -> None:
        self.letztes_backup = res.backup_ordner
        self.auf_balken.set(1)
        self.auf_titel.configure(text=f"Fertig: {zahl(res.verschoben)} Dateien verschoben, "
                                      f"{groesse_text(res.bytes_verschoben)} aufgeräumt")
        self.auf_ziel.configure(text=str(res.backup_ordner))
        text = "Schau in deine Ordner, ob alles passt. Erst danach das Backup in den Papierkorb schieben."
        if res.fehler:
            text = f"{zahl(len(res.fehler))} Dateien wurden zur Sicherheit nicht verschoben (z. B. weil sich etwas geändert hat). " + text
        self.auf_info.configure(text=text, wraplength=760, justify="left")
        for w in self.nachher.winfo_children():
            w.destroy()
        knopf = dict(height=38, corner_radius=8, font=self.f(13))
        ctk.CTkButton(self.nachher, text="Backup-Ordner öffnen", fg_color=LILA_HELL, text_color=LILA,
                      hover_color="#d9d4fb", command=lambda: ordner_oeffnen(res.backup_ordner), **knopf).pack(side="left")
        ctk.CTkButton(self.nachher, text="Rückgängig machen", fg_color=KARTE, text_color=TEXT, border_color=RAND,
                      border_width=1, hover_color=BG, command=lambda: self._wiederherstellen(res.backup_ordner),
                      **knopf).pack(side="left", padx=10)
        ctk.CTkButton(self.nachher, text="Backup in den Papierkorb", fg_color=KARTE, text_color=ROT, border_color=RAND,
                      border_width=1, hover_color=BG, command=lambda: self._backup_wegwerfen(res.backup_ordner),
                      **knopf).pack(side="left")
        self._nav(False, None)
        self.zurueck_btn.configure(state="normal", text="Neue Suche", text_color=LILA,
                                   command=self._neu)

    def _neu(self) -> None:
        self.ergebnis = None
        self.zeige_schritt(0)

    def _wiederherstellen(self, backup: Path) -> None:
        if not self.meldung.frage("Alles zurücklegen?",
                                  "Alle Dateien aus diesem Backup kommen wieder an ihren alten Platz.",
                                  ja="Wiederherstellen"):
            return
        self.configure(cursor="watch")
        self.update()
        try:
            res = wiederherstellen(backup)
        except Exception as ex:
            self.meldung.fehler("Wiederherstellen hat nicht geklappt",
                                f"{ex}\n\nDie Dateien liegen weiter sicher in:\n{backup}")
            return
        finally:
            self.configure(cursor="")
        if res.kaputte_zeilen:
            self.meldung.warnung("Protokoll teilweise beschädigt",
                                 f"{zahl(res.kaputte_zeilen)} Zeilen im Protokoll waren beschädigt. "
                                 f"Schau im Backup-Ordner nach, ob dort noch Dateien liegen:\n{backup}")
        if res.fehler:
            self.meldung.warnung(f"{zahl(res.wiederhergestellt)} Dateien zurückgelegt",
                                 f"{zahl(len(res.fehler))} konnten nicht zurückgelegt werden und bleiben im "
                                 f"Backup-Ordner, z. B.:\n{res.fehler[0][0]}\n{res.fehler[0][1]}")
        else:
            self.meldung.info("Wiederhergestellt",
                              f"{zahl(res.wiederhergestellt)} Dateien sind wieder an ihrem Platz.")
        self._neu()

    def _backup_wegwerfen(self, backup: Path) -> None:
        if not papierkorb_moeglich(backup):
            self.meldung.warnung("Kein Papierkorb auf diesem Laufwerk",
                                 "USB-Sticks, SD-Karten und Netzlaufwerke haben keinen Papierkorb. "
                                 "Lösch den Backup-Ordner selbst, wenn du sicher bist:\n" + str(backup))
            return
        if not self.meldung.frage("Backup in den Papierkorb?",
                                  "Danach geht Rückgängig nur noch über den Papierkorb.",
                                  ja="In den Papierkorb", gefahr=True):
            return
        try:
            backup_in_papierkorb(backup)
            self.meldung.info("Backup ist im Papierkorb",
                              "Wenn du den Papierkorb leerst, ist der Platz wirklich frei.")
            self._neu()
        except Exception as ex:
            self.meldung.fehler("Das hat nicht geklappt", str(ex))


if __name__ == "__main__":
    App().mainloop()
