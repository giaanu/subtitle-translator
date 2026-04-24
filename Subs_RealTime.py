#!/usr/bin/env python3

import tkinter as tk
from tkinter import font as tkfont
import requests
from deep_translator import GoogleTranslator
import threading
import time
import re

IDIOMA_ORIGEN = "en"
IDIOMA_DESTINO = "es"
SEEK_STEP = 2.0


# ── DATA ─────────────────────────────────────────────

def fetch_captions(video_id):
    url = f"https://fast.wistia.net/embed/captions/{video_id}.json"
    resp = requests.get(url)
    resp.raise_for_status()
    data = resp.json()

    captions_list = data.get("captions", [])
    if not captions_list:
        raise ValueError("El video no tiene captions disponibles")

    for cap in captions_list:
        tag = cap.get("bcp47LanguageTag", "")
        if tag.startswith("en"):
            lines = cap.get("hash", {}).get("lines", [])
            if lines:
                return lines

    lines = captions_list[0].get("hash", {}).get("lines", [])
    if not lines:
        raise ValueError("No se encontraron subtítulos")

    return lines


def translate_all(lines, progress_cb):
    translator = GoogleTranslator(source="en", target="es")
    result = []
    total = len(lines)

    for i, line in enumerate(lines):
        text = " ".join(line.get("text", []))

        try:
            translated = translator.translate(text)
        except:
            translated = text

        result.append({
            "start": line.get("start", 0),
            "end": line.get("end", 0),
            "original": text,
            "translation": translated
        })

        progress_cb(i + 1, total)

    return result


def find_caption(captions, t):
    for c in captions:
        if c["start"] <= t <= c["end"]:
            return c
    return None


# ── APP ─────────────────────────────────────────────

class App:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Subtitles - Tool developed by Gianluca Zarrelli")
        self.root.configure(bg="#0d0d0d")

        self.video_id = None
        self.captions = []
        self.elapsed = 0
        self.running = False

        self.build_input_ui()

    # ── INPUT ────────────────────────────────────────

    def build_input_ui(self):
        self.clear()

        tk.Label(self.root, text="Pegá ID o URL", fg="white", bg="#0d0d0d").pack()

        self.entry = tk.Entry(self.root, width=40, bg="#1c1c1c", fg="white", insertbackground="white")
        self.entry.pack(pady=5)

        tk.Button(self.root, text="Cargar", command=self.start_loading).pack()

    # ── LOADING ──────────────────────────────────────

    def build_loading_ui(self):
        self.clear()

        self.label = tk.Label(self.root, text="Descargando subtítulos...", fg="white", bg="#0d0d0d")
        self.label.pack(pady=10)

        self.canvas = tk.Canvas(self.root, height=10, bg="#333", highlightthickness=0)
        self.canvas.pack(fill="x", padx=20)

        self.bar = self.canvas.create_rectangle(0, 0, 0, 10, fill="#00e87a")

    def update_bar(self, done, total):
        pct = done / total
        w = self.canvas.winfo_width()
        self.canvas.coords(self.bar, 0, 0, w * pct, 10)
        self.label.config(text=f"Traduciendo {done}/{total} ({int(pct*100)}%)")

    def start_loading(self):
        self.video_id = self.extract_id(self.entry.get())

        if not self.video_id:
            self.label_error("ID inválido")
            return

        self.build_loading_ui()
        threading.Thread(target=self.worker, daemon=True).start()

    def worker(self):
        try:
            lines = fetch_captions(self.video_id)

            self.captions = translate_all(
                lines,
                lambda d, t: self.root.after(0, self.update_bar, d, t)
            )

            self.root.after(0, self.build_player_ui)

        except Exception as e:
            self.root.after(0, self.label_error, str(e))

    # ── PLAYER UI ─────────────────────────────────────

    def styled_btn(self, parent, text, cmd):
        return tk.Button(
            parent,
            text=text,
            command=cmd,
            bg="#1c1c1c",
            fg="#00e87a",
            activebackground="#333333",
            activeforeground="#00ff99",
            bd=0,
            padx=10,
            pady=4,
            cursor="hand2"
        )

    def build_player_ui(self):
        self.clear()

        self.root.geometry("800x150")
        self.root.configure(bg="#0d0d0d")

        bar = tk.Frame(self.root, bg="#1c1c1c", height=30)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        self.btn = self.styled_btn(bar, "▶", self.toggle)
        self.btn.pack(side="left")

        self.styled_btn(bar, "◀", lambda: self.seek(-SEEK_STEP)).pack(side="left")
        self.styled_btn(bar, "▶", lambda: self.seek(SEEK_STEP)).pack(side="left")
        self.styled_btn(bar, "↺", self.reset).pack(side="left")

        self.styled_btn(bar, "✕", self.root.destroy).pack(side="right")

        self.lbl = tk.Label(
            self.root,
            text="",
            fg="#ffffff",
            bg="#0d0d0d",
            font=tkfont.Font(family="sans-serif", size=18, weight="bold"),
            wraplength=760,
            justify="center",
            padx=12,
            pady=8
        )
        self.lbl.pack(expand=True, fill="both")

        self.lbl_orig = tk.Label(
            self.root,
            text="",
            fg="#888888",
            bg="#0d0d0d",
            font=tkfont.Font(family="sans-serif", size=10),
            wraplength=760,
            justify="center"
        )
        self.lbl_orig.pack(fill="x")

        self.loop()

    # ── CONTROLES ─────────────────────────────────────

    def toggle(self):
        self.running = not self.running
        self.btn.config(text="⏸" if self.running else "▶")
        self.last = time.time()

    def seek(self, d):
        self.elapsed = max(0, self.elapsed + d)

    def reset(self):
        self.elapsed = 0
        self.running = False
        self.lbl.config(text="")
        self.lbl_orig.config(text="")

    # ── LOOP ──────────────────────────────────────────

    def loop(self):
        if self.running:
            now = time.time()
            self.elapsed += now - self.last
            self.last = now

        cap = find_caption(self.captions, self.elapsed)

        if cap:
            self.lbl.config(text=cap["translation"])
            self.lbl_orig.config(text=f"EN: {cap['original']}")

        self.root.after(50, self.loop)

    # ── UTILS ────────────────────────────────────────

    def extract_id(self, text):
        patrones = [
            r'wistia\.com/medias/([a-z0-9]+)',          # URL directa
            r'wistia\.net/embed/iframe/([a-z0-9]+)',     # iframe embed
            r'wistia_async_([a-z0-9]+)',                 # embed clásico
            r'mediaId["\s:=]+["\']?([a-z0-9]{6,12})',   # atributo mediaId
            r'(?<![a-z0-9])([a-z0-9]{10})(?![a-z0-9])', # ID solo (exactamente 10 chars)
        ]
    for patron in patrones:
        m = re.search(patron, text)
        if m:
            return m.group(1)
    return None

    def label_error(self, msg):
        self.clear()
        tk.Label(self.root, text=f"Error: {msg}", fg="red", bg="#0d0d0d").pack()

    def clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    def run(self):
        self.root.mainloop()


# ── MAIN ─────────────────────────────────────────────

if __name__ == "__main__":
    App().run()