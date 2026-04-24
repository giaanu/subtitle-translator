#!/usr/bin/env python3
from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", category=Warning, module="urllib3")

import tkinter as tk
from tkinter import font as tkfont, messagebox
import queue
import re
import time
import sys
import subprocess
import requests
from deep_translator import GoogleTranslator
import threading

# ── Configuración ────────────────────────────────────────────────────────────
IDIOMA_ORIGEN  = "en"
IDIOMA_DESTINO = "es"
FUENTE_TAMANO  = 17
SEEK_STEP      = 2.0   # Segundos que avanza/retrocede el ajuste fino
# ─────────────────────────────────────────────────────────────────────────────


def fetch_captions(video_id: str) -> list[dict]:
    """Descarga las captions en inglés desde la API pública de Wistia."""
    url = f"https://fast.wistia.net/embed/captions/{video_id}.json"
    print(f"[INFO] Descargando captions: {url}")
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    captions_list = data.get("captions", [])
    if not captions_list:
        raise ValueError("El video no tiene captions disponibles.")

    # Preferir inglés; si no, usar el primero disponible
    for cap in captions_list:
        tag = cap.get("bcp47LanguageTag", "")
        if tag.startswith("en"):
            lines = cap.get("hash", {}).get("lines", [])
            print(f"[INFO] {len(lines)} segmentos encontrados (en: {tag})")
            return lines

    lines = captions_list[0].get("hash", {}).get("lines", [])
    lang  = captions_list[0].get("bcp47LanguageTag", "?")
    print(f"[INFO] {len(lines)} segmentos encontrados (idioma: {lang})")
    return lines


def translate_all(lines: list[dict], on_progress=None) -> list[dict]:
    """Traduce todos los segmentos. Si se pasa on_progress(done, total) lo llama por segmento."""
    translator = GoogleTranslator(source=IDIOMA_ORIGEN, target=IDIOMA_DESTINO)
    result = []
    total  = len(lines)

    for i, line in enumerate(lines):
        original = " ".join(line["text"])
        try:
            translated = translator.translate(original) or original
        except Exception as e:
            print(f"[WARN] Segmento {i+1} sin traducir: {e}")
            translated = original

        result.append({
            "start":       line["start"],
            "end":         line["end"],
            "original":    original,
            "translation": translated,
        })

        if on_progress:
            on_progress(i + 1, total)
        elif (i + 1) % 15 == 0 or (i + 1) == total:
            print(f"[INFO] Traducidos {i+1}/{total}...")

    return result


def find_caption(captions: list[dict], elapsed: float) -> dict | None:
    """Devuelve el caption activo para el tiempo dado, o None."""
    for cap in captions:
        if cap["start"] <= elapsed <= cap["end"]:
            return cap
    return None


class TraductorApp:
    def __init__(self, captions: list[dict]):
        self.captions        = captions
        self.elapsed         = 0.0
        self.offset          = 0.0   # Ajuste fino de sincronismo
        self.running         = False
        self.last_tick       = None
        self.current_caption = None

        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.root = tk.Tk()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        WIN_W, WIN_H = 780, 110
        pos_x = (sw - WIN_W) // 2
        pos_y = sh - WIN_H - 55

        self.root.title("Subtítulos")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.93)
        self.root.overrideredirect(True)
        self.root.configure(bg="#0d0d0d")
        self.root.geometry(f"{WIN_W}x{WIN_H}+{pos_x}+{pos_y}")

        print(f"[INFO] Pantalla: {sw}x{sh}  →  Ventana: +{pos_x}+{pos_y}")

        # ── Barra de controles ───────────────────────────────────────────────
        bar = tk.Frame(self.root, bg="#1c1c1c", height=30)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        self.btn_play = tk.Label(
            bar, text="▶  Iniciar", fg="#00e87a", bg="#1c1c1c",
            font=("monospace", 11, "bold"), cursor="hand2", padx=10
        )
        self.btn_play.pack(side="left")
        self.btn_play.bind("<Button-1>", self._toggle_play)

        self.lbl_time = tk.Label(
            bar, text="0:00", fg="#555555", bg="#1c1c1c",
            font=("monospace", 11), padx=6
        )
        self.lbl_time.pack(side="left")

        # Ajuste fino de sincronismo
        for symbol, delta, tip in [("◀", -SEEK_STEP, f"−{SEEK_STEP:.0f}s"),
                                    ("▶", +SEEK_STEP, f"+{SEEK_STEP:.0f}s")]:
            lbl = tk.Label(
                bar, text=f"{symbol} {tip}", fg="#888888", bg="#1c1c1c",
                font=("sans-serif", 10), cursor="hand2", padx=6
            )
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, d=delta: self._seek(d))

        btn_reset = tk.Label(
            bar, text="↺ Reset", fg="#888888", bg="#1c1c1c",
            font=("sans-serif", 10), cursor="hand2", padx=8
        )
        btn_reset.pack(side="left")
        btn_reset.bind("<Button-1>", self._reset)

        btn_close = tk.Label(
            bar, text="✕", fg="#555555", bg="#1c1c1c",
            font=("sans-serif", 13), cursor="hand2", padx=10
        )
        btn_close.pack(side="right")
        btn_close.bind("<Button-1>", lambda e: self.root.destroy())

        # Drag por la barra
        bar.bind("<ButtonPress-1>",  self._drag_start)
        bar.bind("<B1-Motion>",      self._drag_move)

        # ── Texto de traducción ──────────────────────────────────────────────
        self.lbl_trans = tk.Label(
            self.root,
            text="Presioná  ▶ Iniciar  exactamente cuando el video empiece",
            fg="#ffffff",
            bg="#0d0d0d",
            font=tkfont.Font(family="sans-serif", size=FUENTE_TAMANO, weight="bold"),
            wraplength=760,
            justify="center",
            padx=10, pady=4,
        )
        self.lbl_trans.pack(fill="both", expand=True)

        # ── Texto original (inglés) ──────────────────────────────────────────
        self.lbl_orig = tk.Label(
            self.root,
            text="",
            fg="#666666",
            bg="#0d0d0d",
            font=tkfont.Font(family="sans-serif", size=10),
            wraplength=760,
            justify="center",
            padx=10, pady=2,
        )
        self.lbl_orig.pack(fill="x")

        # Teclado
        self.root.bind("<space>",  self._toggle_play)
        self.root.bind("<Left>",   lambda e: self._seek(-SEEK_STEP))
        self.root.bind("<Right>",  lambda e: self._seek(+SEEK_STEP))
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self.root.after(100, self._update_loop)

    # ── Controles ────────────────────────────────────────────────────────────

    def _toggle_play(self, e=None):
        if self.running:
            self.running = False
            self.btn_play.config(text="▶  Continuar")
        else:
            self.running  = True
            self.last_tick = time.time()
            self.btn_play.config(text="⏸  Pausar")

    def _seek(self, delta: float):
        self.elapsed = max(0.0, self.elapsed + delta)
        if self.running:
            self.last_tick = time.time()
        self._refresh_caption()

    def _reset(self, e=None):
        self.running  = False
        self.elapsed  = 0.0
        self.last_tick = None
        self.current_caption = None
        self.btn_play.config(text="▶  Iniciar")
        self.lbl_time.config(text="0:00")
        self.lbl_trans.config(
            text="Presioná  ▶ Iniciar  exactamente cuando el video empiece"
        )
        self.lbl_orig.config(text="")

    # ── Loop de actualización ────────────────────────────────────────────────

    def _update_loop(self):
        if self.running:
            now = time.time()
            self.elapsed += now - self.last_tick
            self.last_tick = now

            mins = int(self.elapsed) // 60
            secs = int(self.elapsed) % 60
            self.lbl_time.config(text=f"{mins}:{secs:02d}")

            self._refresh_caption()

        self.root.after(80, self._update_loop)

    def _refresh_caption(self):
        cap = find_caption(self.captions, self.elapsed)
        if cap is self.current_caption:
            return
        self.current_caption = cap
        if cap:
            self.lbl_trans.config(text=cap["translation"])
            self.lbl_orig.config(text=f"EN: {cap['original']}")
        else:
            self.lbl_trans.config(text="")
            self.lbl_orig.config(text="")

    # ── Drag ─────────────────────────────────────────────────────────────────

    def _drag_start(self, e):
        self.root._dx = e.x
        self.root._dy = e.y

    def _drag_move(self, e):
        x = self.root.winfo_x() + e.x - self.root._dx
        y = self.root.winfo_y() + e.y - self.root._dy
        self.root.geometry(f"+{x}+{y}")

    def run(self):
        self.root.mainloop()


# ── Ventana de carga ─────────────────────────────────────────────────────────

class LoadingWindow:
    """Ventana con barra de progreso mientras se descargan y traducen los subs."""

    _BAR_H = 8
    _WIN_W = 440
    _WIN_H = 200

    def __init__(self, video_id: str):
        self.video_id       = video_id
        self.captions       = None
        self.error          = None
        self._queue         = queue.Queue()
        self._indeterminate = False
        self._anim_pos      = 0

        self.root = tk.Tk()
        self.root.title("Cargando subtítulos…")
        self.root.configure(bg="#0d0d0d")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x  = (sw - self._WIN_W) // 2
        y  = (sh - self._WIN_H) // 2
        self.root.geometry(f"{self._WIN_W}x{self._WIN_H}+{x}+{y}")

        self._build_ui()

    def _build_ui(self):
        tk.Label(
            self.root,
            text="Subtítulos Wistia",
            fg="#00e87a", bg="#0d0d0d",
            font=("sans-serif", 13, "bold"),
            pady=20,
        ).pack()

        self.lbl_status = tk.Label(
            self.root,
            text="Iniciando…",
            fg="#cccccc", bg="#0d0d0d",
            font=("sans-serif", 11),
        )
        self.lbl_status.pack()

        bar_outer = tk.Frame(self.root, bg="#0d0d0d")
        bar_outer.pack(fill="x", padx=32, pady=14)

        self.canvas = tk.Canvas(
            bar_outer, height=self._BAR_H,
            bg="#2a2a2a", highlightthickness=0,
        )
        self.canvas.pack(fill="x")
        self.canvas.update_idletasks()

        self._bar = self.canvas.create_rectangle(
            0, 0, 0, self._BAR_H, fill="#00e87a", outline=""
        )

        self.lbl_detail = tk.Label(
            self.root,
            text="",
            fg="#666666", bg="#0d0d0d",
            font=("monospace", 10),
            pady=4,
        )
        self.lbl_detail.pack()

    # ── Progreso ─────────────────────────────────────────────────────────────

    def _set_progress(self, pct: float, detail: str = ""):
        w = self.canvas.winfo_width()
        self.canvas.coords(self._bar, 0, 0, int(w * pct / 100), self._BAR_H)
        if detail:
            self.lbl_detail.config(text=detail)

    def _tick_indeterminate(self):
        if not self._indeterminate:
            return
        w   = max(self.canvas.winfo_width(), 1)
        seg = max(80, w // 4)
        pos = self._anim_pos % (w + seg)
        x0  = pos - seg // 2
        x1  = x0 + seg
        self.canvas.coords(
            self._bar,
            max(0, x0), 0, min(w, x1), self._BAR_H,
        )
        self._anim_pos += 10
        self.root.after(30, self._tick_indeterminate)

    # ── Hilo de fondo ────────────────────────────────────────────────────────

    def _worker(self):
        try:
            self._queue.put(("phase", "download"))
            lines = fetch_captions(self.video_id)

            if not lines:
                raise ValueError("El video no tiene captions en inglés.")

            total = len(lines)
            self._queue.put(("phase", "translate", total))

            def cb(done, tot):
                self._queue.put(("progress", done, tot))

            result = translate_all(lines, on_progress=cb)
            self._queue.put(("done", result))

        except Exception as exc:
            self._queue.put(("error", str(exc)))

    # ── Polling del hilo principal ───────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                tag = msg[0]

                if tag == "phase":
                    if msg[1] == "download":
                        self.lbl_status.config(text="Descargando subtítulos…")
                        self._indeterminate = True
                        self._anim_pos = 0
                        self._tick_indeterminate()
                    elif msg[1] == "translate":
                        total = msg[2]
                        self._indeterminate = False
                        self.lbl_status.config(
                            text=f"Traduciendo {total} segmentos al español…"
                        )
                        self._set_progress(0)

                elif tag == "progress":
                    _, done, total = msg
                    pct = done / total * 100
                    self._set_progress(pct, f"{done} / {total}  ·  {pct:.0f}%")

                elif tag == "done":
                    self.captions = msg[1]
                    self.root.destroy()
                    return

                elif tag == "error":
                    self.error = msg[1]
                    self.root.destroy()
                    return

        except queue.Empty:
            pass

        self.root.after(50, self._poll)

    def run(self) -> list[dict] | None:
        t = threading.Thread(target=self._worker, daemon=True)
        t.start()
        self.root.after(80, self._poll)
        self.root.mainloop()
        return self.captions


# ── Extracción del video ID ───────────────────────────────────────────────────

_WISTIA_PATTERNS = [
    r'wvideo=([a-z0-9]+)',                    # wvideo=drkfzcw2dj
    r'wistia\.net/embed/iframe/([a-z0-9]+)',  # fast.wistia.net/embed/iframe/…
    r'wistia\.net/embed/[^/]+/([a-z0-9]+)',  # cualquier path de embed
    r'wistia\.com/medias/([a-z0-9]+)',        # saasrise.wistia.com/medias/…
]

def extract_video_id(text: str) -> str | None:
    """Extrae el ID de Wistia de un HTML, URL, o ID directo."""
    text = text.strip()
    if re.fullmatch(r'[a-z0-9]{6,13}', text):
        return text
    for pattern in _WISTIA_PATTERNS:
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return None


class _PasteDialog(tk.Tk):
    """Diálogo que acepta HTML, URL o ID y extrae el video ID en tiempo real."""

    def __init__(self):
        super().__init__()
        self.result = None
        self.title("Video — pegá el embed o el ID")
        self.resizable(False, False)
        self.configure(bg="#1c1c1c")

        tk.Label(
            self,
            text="Pegá el bloque HTML del video, la URL del iframe, o el ID directamente:",
            fg="#cccccc", bg="#1c1c1c",
            font=("sans-serif", 11),
            padx=14, pady=10, justify="left",
        ).pack(fill="x")

        self.txt = tk.Text(
            self, height=7, width=64,
            bg="#111111", fg="#dddddd", insertbackground="white",
            font=("monospace", 10), wrap="word",
            padx=6, pady=6, relief="flat",
        )
        self.txt.pack(padx=14, pady=(0, 6))

        self.lbl_id = tk.Label(
            self, text="ID detectado: —",
            fg="#00e87a", bg="#1c1c1c",
            font=("monospace", 12, "bold"),
            padx=14, pady=4, anchor="w",
        )
        self.lbl_id.pack(fill="x")

        btn_frame = tk.Frame(self, bg="#1c1c1c")
        btn_frame.pack(fill="x", padx=14, pady=10)

        # BOTÓN PEGAR (fallback seguro)
        tk.Button(
            btn_frame, text="Pegar", command=self._force_paste,
            bg="#444444", fg="#ffffff",
            font=("sans-serif", 11),
            relief="flat", padx=12, pady=5, cursor="hand2",
        ).pack(side="left")

        tk.Button(
            btn_frame, text="Continuar", command=self._ok,
            bg="#00e87a", fg="#000000",
            font=("sans-serif", 11, "bold"),
            relief="flat", padx=16, pady=5, cursor="hand2",
        ).pack(side="right")

        tk.Button(
            btn_frame, text="Cancelar", command=self.destroy,
            bg="#333333", fg="#cccccc",
            font=("sans-serif", 11),
            relief="flat", padx=16, pady=5, cursor="hand2",
        ).pack(side="right", padx=8)

        # Eventos
        self.txt.bind("<KeyRelease>", self._on_change)
        self.txt.bind("<<Paste>>", lambda e: self.after(10, self._on_change))
        self.txt.bind("<Command-v>", self._force_paste)

        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self.destroy())

        # Posicionar ventana
        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        x = (self.winfo_screenwidth()  - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"+{x}+{y}")

        # 🔥 CLAVE EN MAC
        self.lift()
        self.focus_force()
        self.after(100, lambda: self.txt.focus_force())

    def _force_paste(self, _e=None):
        """Pegado manual desde clipboard para macOS."""
        try:
            self.txt.delete("sel.first", "sel.last")
        except tk.TclError:
            pass

        try:
            text = self.clipboard_get()
            self.txt.insert(tk.INSERT, text)
            self.after(10, self._on_change)
        except tk.TclError:
            print("No se pudo acceder al portapapeles")

        return "break"

    def _on_change(self, _e=None):
        vid = extract_video_id(self.txt.get("1.0", "end"))
        self.lbl_id.config(
            text=f"ID detectado: {vid}" if vid else "ID detectado: —",
            fg="#00e87a" if vid else "#888888",
        )

    def _ok(self):
        vid = extract_video_id(self.txt.get("1.0", "end"))
        if vid:
            self.result = vid
            self.destroy()
        else:
            self.lbl_id.config(
                text="❌ No se encontró un ID de Wistia válido",
                fg="#ff5555"
            )

            
def ask_video_id() -> str:
    dlg = _PasteDialog()
    dlg.mainloop()
    return dlg.result or ""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  Traductor de subtítulos Wistia  (sin OCR)")
    print("=" * 55)

    video_id = ask_video_id()
    if not video_id:
        print("❌ No se ingresó un ID de video.")
        sys.exit(1)

    print(f"\n→ Video ID: {video_id}")

    loader   = LoadingWindow(video_id)
    captions = loader.run()

    if captions is None:
        print(f"❌ {loader.error or 'Error desconocido'}")
        sys.exit(1)

    print(f"✓ Todo listo ({len(captions)} segmentos). Abriendo ventana…\n")
    print("  Controles:")
    print("  · ▶ Iniciar / ⏸ Pausar  (o barra espaciadora)")
    print("  · ◀ / ▶ ajustan ±2s si el texto se desfasa")
    print("  · ↺ Reset reinicia el timer")
    print("  · Arrastrá la ventana desde la barra superior")
    print("  · Esc o ✕ para cerrar\n")

    app = TraductorApp(captions)
    app.run()


if __name__ == "__main__":
    main()
