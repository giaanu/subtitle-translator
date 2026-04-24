# Traductor de subtítulos Wistia en tiempo real

Script Python para traducir subtítulos de videos Wistia embebidos al español, en tiempo real, mostrándolos en una ventana flotante sobre cualquier otra aplicación.

---

## Por qué este enfoque

Los videos de Wistia exponen un endpoint público de captions con timestamps exactos:

```
https://fast.wistia.net/embed/captions/{video_id}.json
```

Esto permite descargar y traducir **todos los subtítulos antes de reproducir el video**, y luego mostrarlos sincronizados mediante un timer simple — sin necesidad de OCR, sin captura de pantalla, sin Tesseract ni scrot.

---

## Requisitos

**Sistema operativo:** Debian 12 / Ubuntu con X11  
**Python:** 3.11+ (con entorno virtual recomendado)

### Dependencias Python

```bash
~/traductor-env/bin/pip install requests deep-translator
```

> El script instala las dependencias automáticamente si no las encuentra.

### Sin dependencias de sistema adicionales

A diferencia de enfoques basados en OCR, este script **no requiere**:
- `tesseract-ocr`
- `scrot`
- `python3-tk` (tkinter viene incluido en Python 3.11 en Debian)

---

## Instalación

```bash
# Crear entorno virtual (si no existe)
python3 -m venv ~/traductor-env

# Instalar dependencias
~/traductor-env/bin/pip install requests deep-translator

# Clonar o copiar el script
cp Subs_RealTime.py ~/Documentos/Script\ translate/
```

---

## Uso

```bash
cd ~/Documentos/Script\ translate
~/traductor-env/bin/python Subs_RealTime.py
```

### Paso 1 — Ingresar el video

Al iniciar aparece un diálogo. Se puede pegar cualquiera de estos formatos:

| Formato | Ejemplo |
|---|---|
| HTML embed completo | `<p><a href="https://cdn.embedly.com/...wvideo=drkfzcw2dj">...` |
| URL del iframe | `https://fast.wistia.net/embed/iframe/drkfzcw2dj` |
| URL de media | `https://saasrise.wistia.com/medias/drkfzcw2dj` |
| ID directo | `drkfzcw2dj` |

El ID se detecta automáticamente y se muestra en verde mientras se escribe o pega.

### Paso 2 — Esperar la traducción

El script descarga los subtítulos en inglés y los traduce todos al español antes de abrir la ventana. En la terminal se ve el progreso:

```
→ Video ID: drkfzcw2dj
[INFO] Descargando captions: https://fast.wistia.net/embed/captions/drkfzcw2dj.json
[INFO] 87 segmentos encontrados (en: en-US)
→ Traduciendo 87 segmentos al español...
[INFO] Traducidos 15/87...
[INFO] Traducidos 30/87...
...
✓ Todo listo. Abriendo ventana...
```

### Paso 3 — Sincronizar con el video

1. Abrí el video en el navegador
2. Presioná **▶ Iniciar** en la ventana flotante **exactamente** cuando el video empiece a reproducirse
3. Los subtítulos en español aparecen sincronizados con el audio

---

## Controles

| Acción | Botón | Teclado |
|---|---|---|
| Iniciar / Pausar | ▶ / ⏸ | `Espacio` |
| Ajustar sincronismo −2s | ◀ −2s | `←` |
| Ajustar sincronismo +2s | ▶ +2s | `→` |
| Reiniciar timer | ↺ Reset | — |
| Cerrar | ✕ | `Esc` |
| Mover ventana | Arrastrar desde la barra superior | — |

> Si el texto se adelanta o atrasa respecto al audio, usá los botones ◀ / ▶ para corregirlo sin reiniciar.

---

## Arquitectura interna

```
main()
 ├── ask_video_id()          → Diálogo tkinter, acepta HTML/URL/ID
 │    └── extract_video_id() → Regex: extrae el ID del texto pegado
 │
 ├── fetch_captions(id)      → GET fast.wistia.net/embed/captions/{id}.json
 │                             Devuelve lista de {start, end, text[]}
 │
 ├── translate_all(lines)    → GoogleTranslator (sin API key, gratuito)
 │                             Devuelve lista de {start, end, original, translation}
 │
 └── TraductorApp(captions)  → Ventana tkinter flotante
      ├── _build_ui()        → Barra de controles + labels de texto
      ├── _update_loop()     → after(80ms): avanza elapsed, llama _refresh_caption
      ├── _refresh_caption() → find_caption(elapsed) → actualiza labels
      ├── _toggle_play()     → inicia/pausa el timer
      ├── _seek(delta)       → ajusta elapsed ±N segundos
      └── _reset()           → elapsed = 0, estado inicial
```

### Sincronización

El timer usa `time.time()` con diferencias de ~80ms entre ticks. No hay hilo secundario: todo corre en el hilo principal de tkinter via `root.after()`, evitando problemas de thread safety.

```python
# Cada 80ms:
elapsed += time.time() - last_tick
last_tick = time.time()
caption = find_caption(captions, elapsed)   # búsqueda lineal O(n)
if caption != current: actualizar_labels()
```

### Extracción del ID

Se prueban cuatro patrones regex en orden de especificidad:

```
wvideo=([a-z0-9]+)                   ← parámetro query más específico
wistia\.net/embed/iframe/([a-z0-9]+) ← URL del iframe
wistia\.net/embed/[^/]+/([a-z0-9]+) ← cualquier embed de Wistia
wistia\.com/medias/([a-z0-9]+)       ← URL de media
```

Si el texto pegado es solo el ID (6–13 caracteres alfanuméricos en minúscula), se usa directamente sin regex.

---

## Configuración

Las constantes al inicio del script permiten ajustes rápidos:

```python
IDIOMA_ORIGEN  = "en"   # Idioma fuente
IDIOMA_DESTINO = "es"   # Idioma destino
FUENTE_TAMANO  = 17     # Tamaño del texto traducido
SEEK_STEP      = 2.0    # Segundos de ajuste por click de ◀ / ▶
```

Para cambiar el idioma de traducción (por ejemplo, a portugués):
```python
IDIOMA_DESTINO = "pt"
```

Los códigos de idioma son los de Google Translate (ISO 639-1).

---

## Limitaciones conocidas

- **Sincronismo manual**: el timer arranca cuando el usuario presiona ▶, no hay detección automática del inicio del video. Si hay un pre-roll o anuncio, hay que compensar con los botones ◀ / ▶.
- **Requiere captions en el video**: si el video de Wistia no tiene captions activados por el creador, el endpoint devuelve lista vacía y el script termina con error.
- **Traducción al inicio**: para videos muy largos (>30 min) la traducción inicial puede tardar 1–2 minutos. El progreso se muestra en terminal.
- **Google Translate gratuito**: usa el servicio sin API key. Para uso intensivo o corporativo considerar la API oficial con clave.

---

## Solución de problemas

**El diálogo no aparece al iniciar**
```bash
echo $DISPLAY   # debe devolver :0 o similar
```
Si está vacío, el entorno X11 no está disponible. Ejecutar desde una terminal gráfica, no SSH sin X forwarding.

**Error `requests.HTTPError: 404`**
El video no tiene captions públicos. Verificar en Wistia que el video tenga subtítulos habilitados.

**La traducción se corta o devuelve el original en inglés**
Google Translate free tiene límite de caracteres por request (~5000). Para segmentos largos el script ya hace fallback al original. Reintentar o usar la API con clave.

**La ventana flotante queda detrás de otras ventanas**
El atributo `-topmost` debería mantenerla al frente. En algunos gestores de ventanas (i3, bspwm) puede ignorarse. Enfocar la ventana manualmente con Alt+Tab.
