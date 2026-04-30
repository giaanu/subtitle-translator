#!/usr/bin/env python3

import tkinter as tk
from tkinter import font as tkfont
import requests
from deep_translator import GoogleTranslator
import threading
import time
import re
import os

IDIOMA_ORIGEN  = "en"
IDIOMA_DESTINO = "es"
SEEK_STEP      = 2.0


def fetch_captions(video_id):
    url  = f"https://fast.wistia.net/embed/captions/{video_id}.json"
    resp = requests.get(url, timeout=10)
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
    result     = []
    total      = len(lines)

    for i, line in enumerate(lines):
        text = " ".join(line.get("text", []))
        try:
            translated = translator.translate(text)
        except Exception:
            translated = text

        result.append({
            "start":       line.get("start", 0),
            "end":         line.get("end", 0),
            "original":    text,
            "translation": translated
        })

        progress_cb(i + 1, total)

    return result


def find_caption(captions, t):
    for c in captions:
        if c["start"] <= t <= c["end"]:
            return c
    return None


class App:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Subtitles — Tool developed by Gianluca Zarrelli")
        self.root.configure(bg="#0d0d0d")
        self.root.resizable(False, False)

        self.video_id = None
        self.captions = []
        self.elapsed  = 0.0
        self.running  = False
        self.last     = 0.0

        self.build_input_ui()

   
    def build_input_ui(self):
        self.clear()
        self.root.geometry("480x130")

        tk.Label(
            self.root,
            text="Pegá el ID, URL de Wistia o URL de la lección de SaasRise",
            fg="#aaaaaa", bg="#0d0d0d",
            font=tkfont.Font(family="sans-serif", size=10)
        ).pack(pady=(14, 4))

        frame = tk.Frame(self.root, bg="#0d0d0d")
        frame.pack(padx=20, fill="x")

        self.entry = tk.Entry(
            frame, width=42,
            bg="#1c1c1c", fg="white",
            insertbackground="white",
            relief="flat", bd=4,
            font=tkfont.Font(family="sans-serif", size=11)
        )
        self.entry.pack(side="left", expand=True, fill="x")
        self.entry.bind("<Return>", lambda e: self.start_loading())

        self.styled_btn(frame, "Cargar", self.start_loading).pack(side="left", padx=(8, 0))

        self.lbl_status = tk.Label(
            self.root, text="", fg="#ff4444", bg="#0d0d0d",
            font=tkfont.Font(family="sans-serif", size=10)
        )
        self.lbl_status.pack(pady=(6, 0))


    def build_loading_ui(self, mensaje="Iniciando..."):
        self.clear()
        self.root.geometry("480x100")

        self.lbl_loading = tk.Label(
            self.root, text=mensaje,
            fg="white", bg="#0d0d0d",
            font=tkfont.Font(family="sans-serif", size=11)
        )
        self.lbl_loading.pack(pady=(18, 8))

        self.canvas = tk.Canvas(self.root, height=10, bg="#333333", highlightthickness=0)
        self.canvas.pack(fill="x", padx=24)
        self.bar = self.canvas.create_rectangle(0, 0, 0, 10, fill="#00e87a")

    def update_bar(self, done, total):
        pct = done / total
        w   = self.canvas.winfo_width()
        self.canvas.coords(self.bar, 0, 0, w * pct, 10)
        self.lbl_loading.config(text=f"Traduciendo {done}/{total}  ({int(pct * 100)}%)")


    def start_loading(self):
        raw = self.entry.get().strip()
        if not raw:
            return
        self.build_loading_ui("Procesando...")
        threading.Thread(target=self.worker_with_extract, args=(raw,), daemon=True).start()

    def worker_with_extract(self, raw):
        
        if "saasrise.com" in raw:
            self.root.after(0, lambda: self.lbl_loading.config(
                text="Abriendo Chrome... iniciá sesión si es necesario"
            ))
            video_id = self.extract_id_selenium(raw)
        else:
            video_id = self.extract_id_local(raw)

        if not video_id:
            self.root.after(0, self.label_error, "No se encontró un ID de video válido")
            return

        self.video_id = video_id
        self.root.after(0, lambda: self.lbl_loading.config(
            text=f"Video ID: {video_id} — Descargando subtítulos..."
        ))

        try:
            lines = fetch_captions(self.video_id)
            self.captions = translate_all(
                lines,
                lambda d, t: self.root.after(0, self.update_bar, d, t)
            )
            self.root.after(0, self.build_player_ui)
        except Exception as e:
            self.root.after(0, self.label_error, str(e))


    def extract_id_local(self, text):
        patrones = [
            r'wistia\.com/medias/([a-z0-9]+)',
            r'wistia\.net/embed/iframe/([a-z0-9]+)',
            r'wistia_async_([a-z0-9]+)',
            r'mediaId["\s:=]+["\']?([a-z0-9]{6,12})',
            r'(?<![a-z0-9])([a-z0-9]{10})(?![a-z0-9])',
        ]
        for patron in patrones:
            m = re.search(patron, text)
            if m:
                return m.group(1)
        return None

    def extract_id_selenium(self, url):
        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
        except ImportError:
            self.root.after(0, self.label_error,
                "Falta instalar: pip install selenium webdriver-manager")
            return None

        # Guarda la sesión en AppData para no hacer login cada vez
        session_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "SaasRiseSession"
        )

        options = webdriver.ChromeOptions()
        options.add_argument(f"--user-data-dir={session_dir}")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        driver = None
        try:
            service = Service(ChromeDriverManager().install())
            driver  = webdriver.Chrome(service=service, options=options)
            driver.get(url)

            WebDriverWait(driver, 500).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "iframe[src*='wistia']")
                )
            )

            iframe = driver.find_element(By.CSS_SELECTOR, "iframe[src*='wistia']")
            src    = iframe.get_attribute("src")
            driver.quit()

            return self.extract_id_local(src)

        except Exception as e:
            if driver:
                driver.quit()
            self.root.after(0, self.label_error, f"Selenium: {e}")
            return None


    def build_player_ui(self):
        self.clear()
        self.root.geometry("820x160")
        self.root.resizable(True, False)

        bar = tk.Frame(self.root, bg="#1c1c1c", height=32)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        self.btn_play = self.styled_btn(bar, "▶  Play", self.toggle)
        self.btn_play.pack(side="left", padx=(4, 0))

        self.styled_btn(bar, "−2s", lambda: self.seek(-SEEK_STEP)).pack(side="left")
        self.styled_btn(bar, "+2s", lambda: self.seek(SEEK_STEP)).pack(side="left")
        self.styled_btn(bar, "↺  Reset", self.reset).pack(side="left")

        self.lbl_time = tk.Label(
            bar, text="0:00", fg="#555555", bg="#1c1c1c",
            font=tkfont.Font(family="sans-serif", size=10)
        )
        self.lbl_time.pack(side="left", padx=10)

        self.styled_btn(bar, "✕", self.root.destroy).pack(side="right", padx=4)


        self.lbl = tk.Label(
            self.root, text="Presioná ▶ cuando empiece el video",
            fg="#ffffff", bg="#0d0d0d",
            font=tkfont.Font(family="sans-serif", size=18, weight="bold"),
            wraplength=800, justify="center",
            padx=12, pady=8
        )
        self.lbl.pack(expand=True, fill="both")


        self.lbl_orig = tk.Label(
            self.root, text="",
            fg="#555555", bg="#0d0d0d",
            font=tkfont.Font(family="sans-serif", size=10),
            wraplength=800, justify="center"
        )
        self.lbl_orig.pack(fill="x", pady=(0, 6))

        self.loop()


    def toggle(self):
        self.running = not self.running
        self.btn_play.config(text="⏸  Pause" if self.running else "▶  Play")
        self.last = time.time()

    def seek(self, delta):
        self.elapsed = max(0.0, self.elapsed + delta)

    def reset(self):
        self.elapsed = 0.0
        self.running = False
        self.btn_play.config(text="▶  Play")
        self.lbl.config(text="Presioná ▶ cuando empiece el video")
        self.lbl_orig.config(text="")
        self.lbl_time.config(text="0:00")


    def loop(self):
        if self.running:
            now           = time.time()
            self.elapsed += now - self.last
            self.last     = now

        
        mins = int(self.elapsed) // 60
        secs = int(self.elapsed) % 60
        self.lbl_time.config(text=f"{mins}:{secs:02d}")

        cap = find_caption(self.captions, self.elapsed)
        if cap:
            self.lbl.config(text=cap["translation"])
            self.lbl_orig.config(text=f"EN: {cap['original']}")
        elif self.running:
            self.lbl.config(text="")
            self.lbl_orig.config(text="")

        self.root.after(50, self.loop)


    def styled_btn(self, parent, text, cmd):
        return tk.Button(
            parent, text=text, command=cmd,
            bg="#1c1c1c", fg="#00e87a",
            activebackground="#2a2a2a", activeforeground="#00ff99",
            bd=0, padx=10, pady=4,
            cursor="hand2",
            font=tkfont.Font(family="sans-serif", size=10)
        )

    def label_error(self, msg):
        self.clear()
        self.root.geometry("480x130")
        self.build_input_ui()
        self.lbl_status.config(text=f"⚠  {msg}")

    def clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()