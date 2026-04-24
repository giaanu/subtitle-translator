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

    # 🔥 buscar inglés primero (como tu script original)
    for cap in captions_list:
        tag = cap.get("bcp47LanguageTag", "")
        if tag.startswith("en"):
            lines = cap.get("hash", {}).get("lines", [])
            if lines:
                return lines

    # 🔥 fallback seguro
    lines = captions_list[0].get("hash", {}).get("lines", [])
    if not lines:
        raise ValueError("No se encontraron líneas de subtítulos")

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
        self.root.title("Subtitles")

        self.video_id = None
        self.captions = []
        self.elapsed = 0
        self.running = False

        self.build_input_ui()

    # ── INPUT ────────────────────────────────────────

    def build_input_ui(self):
        self.clear()

        tk.Label(self.root, text="Pegá ID o URL").pack()

        self.entry = tk.Entry(self.root, width=40)
        self.entry.pack()

        tk.Button(self.root, text="Cargar", command=self.start_loading).pack()

    # ── LOADING ──────────────────────────────────────

    def build_loading_ui(self):
        self.clear()

        self.label = tk.Label(self.root, text="Descargando subtítulos...")
        self.label.pack(pady=10)

        self.canvas = tk.Canvas(self.root, height=10, bg="#333")
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
            # ✅ FIX correcto (sin lambda rota)
            self.root.after(0, self.label_error, str(e))

    # ── PLAYER ───────────────────────────────────────

    def build_player_ui(self):
        self.clear()

        self.root.geometry("800x150")

        bar = tk.Frame(self.root)
        bar.pack(fill="x")

        self.btn = tk.Button(bar, text="▶", command=self.toggle)
        self.btn.pack(side="left")

        tk.Button(bar, text="<<", command=lambda: self.seek(-SEEK_STEP)).pack(side="left")
        tk.Button(bar, text=">>", command=lambda: self.seek(SEEK_STEP)).pack(side="left")

        tk.Button(bar, text="Reset", command=self.reset).pack(side="left")

        tk.Button(bar, text="X", command=self.root.destroy).pack(side="right")

        self.lbl = tk.Label(
            self.root,
            font=tkfont.Font(size=16, weight="bold"),
            wraplength=760,
            justify="center"
        )
        self.lbl.pack(expand=True, fill="both")

        self.loop()

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

    def loop(self):
        if self.running:
            now = time.time()
            self.elapsed += now - self.last
            self.last = now

        cap = find_caption(self.captions, self.elapsed)

        if cap:
            self.lbl.config(text=cap["translation"])

        self.root.after(50, self.loop)

    # ── UTILS ────────────────────────────────────────

    def extract_id(self, text):
        m = re.search(r'([a-z0-9]{6,12})', text)
        return m.group(1) if m else None

    def label_error(self, msg):
        self.clear()
        tk.Label(self.root, text=f"Error: {msg}", fg="red").pack()

    def clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    def run(self):
        self.root.mainloop()


# ── MAIN ─────────────────────────────────────────────

if __name__ == "__main__":
    App().run()