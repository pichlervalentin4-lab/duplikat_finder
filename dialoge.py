"""Hinweis- und Rückfragefenster im Design der App (statt der grauen System-Fenster).

Benutzung in der App:
    self.meldung = Meldungen(self)
    self.meldung.info("Fertig", "Alles erledigt.")
    if self.meldung.frage("Wirklich?", "Text …", ja="Löschen", gefahr=True): ...
"""

from __future__ import annotations

import customtkinter as ctk

from stil import (APP_NAME, BG, GELB, GELB_HELL, GRAU, KARTE, LILA, LILA_HELL, LILA_HOVER, RAND,
                  ROT, ROT_HELL, ROT_HOVER, TEXT, schrift)

# Art -> (Zeichen im Kreis, Farbe, Hintergrund des Kreises)
_ARTEN = {
    "info": ("i", LILA, LILA_HELL),
    "frage": ("?", LILA, LILA_HELL),
    "warnung": ("!", GELB, GELB_HELL),
    "fehler": ("✕", ROT, ROT_HELL),
}


class Dialog(ctk.CTkToplevel):
    """Ein modales Fenster: blockiert die App, bis man einen Knopf drückt."""

    def __init__(self, eltern, art: str, titel: str, text: str,
                 ja: str = "OK", nein: str | None = None, gefahr: bool = False) -> None:
        super().__init__(eltern, fg_color=KARTE)
        self.ergebnis = False
        self.title(APP_NAME)
        self.resizable(False, False)
        self.transient(eltern)
        self.protocol("WM_DELETE_WINDOW", self._nein)

        zeichen, farbe, kreis = _ARTEN.get(art, _ARTEN["info"])
        rahmen = ctk.CTkFrame(self, fg_color=KARTE)
        rahmen.pack(fill="both", expand=True, padx=26, pady=(24, 20))
        rahmen.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(rahmen, text=zeichen, width=40, height=40, corner_radius=20, fg_color=kreis,
                     text_color=farbe, font=schrift(18, "bold")).grid(row=0, column=0, rowspan=2,
                                                                     sticky="n", padx=(0, 16))
        ctk.CTkLabel(rahmen, text=titel, font=schrift(17, "bold"), text_color=TEXT, anchor="w",
                     justify="left", wraplength=360).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(rahmen, text=text, font=schrift(13), text_color=GRAU, anchor="w",
                     justify="left", wraplength=360).grid(row=1, column=1, sticky="w", pady=(6, 0))

        ctk.CTkFrame(self, fg_color=RAND, height=1, corner_radius=0).pack(fill="x")  # Trennlinie
        knoepfe = ctk.CTkFrame(self, fg_color=KARTE, corner_radius=0)
        knoepfe.pack(fill="x")
        haupt = ctk.CTkButton(knoepfe, text=ja, height=36, corner_radius=8, font=schrift(13, "bold"),
                              fg_color=ROT if gefahr else LILA,
                              hover_color=ROT_HOVER if gefahr else LILA_HOVER, command=self._ja)
        haupt.pack(side="right", padx=(8, 20), pady=14)
        if nein:
            ctk.CTkButton(knoepfe, text=nein, height=36, corner_radius=8, font=schrift(13),
                          fg_color=KARTE, text_color=TEXT, border_width=1, border_color=RAND,
                          hover_color=BG, command=self._nein).pack(side="right", pady=14)

        self.bind("<Return>", lambda _e: self._ja())
        self.bind("<Escape>", lambda _e: self._nein())
        self._zentrieren(eltern)
        # Auf Windows erscheinen neue Fenster sonst manchmal hinter der App
        self.after(20, self._nach_vorne)

    def _zentrieren(self, eltern) -> None:
        self.update_idletasks()
        b, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = eltern.winfo_rootx() + (eltern.winfo_width() - b) // 2
        y = eltern.winfo_rooty() + (eltern.winfo_height() - h) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _nach_vorne(self) -> None:
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except Exception:
            pass

    def _ja(self) -> None:
        self.ergebnis = True
        self.destroy()

    def _nein(self) -> None:
        self.ergebnis = False
        self.destroy()

    def zeigen(self) -> bool:
        self.wait_window()
        return self.ergebnis


class Meldungen:
    def __init__(self, app) -> None:
        self.app = app

    def info(self, titel: str, text: str = "") -> None:
        Dialog(self.app, "info", titel, text).zeigen()

    def warnung(self, titel: str, text: str = "") -> None:
        Dialog(self.app, "warnung", titel, text).zeigen()

    def fehler(self, titel: str, text: str = "") -> None:
        Dialog(self.app, "fehler", titel, text).zeigen()

    def frage(self, titel: str, text: str = "", ja: str = "Ja", nein: str = "Abbrechen",
              gefahr: bool = False) -> bool:
        return Dialog(self.app, "frage", titel, text, ja=ja, nein=nein, gefahr=gefahr).zeigen()
