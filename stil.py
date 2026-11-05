"""Farben und Schrift aus Design C, gemeinsam für Hauptfenster und Dialoge."""

import customtkinter as ctk

APP_NAME = "Duplikat-Finder"

BG = "#f7f8fc"
KARTE = "#ffffff"
RAND = "#e6e8f0"
TEXT = "#1a1d29"
GRAU = "#5c6178"
HELLGRAU = "#8a8fa3"
LILA = "#6c5ce7"
LILA_HOVER = "#5a4bd6"
LILA_HELL = "#e7e4fd"
SCHIENE = "#dfe2ec"
ROT = "#d63c4a"
ROT_HOVER = "#b8303c"
ROT_HELL = "#fde8ea"
GELB = "#b7791f"
GELB_HELL = "#fdf3e1"
GRUEN = "#1f9d61"


def schrift(groesse: int = 13, gewicht: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family="Segoe UI", size=groesse, weight=gewicht)
