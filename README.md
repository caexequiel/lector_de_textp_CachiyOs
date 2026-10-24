# 📖 Lector de Libros IA (CachyOS) — Modo Entrenamiento / Gimnasio

Lector inteligente de libros y documentos completos con síntesis de voz neuronal (`Edge-TTS`), respaldo offline local (`Piper TTS`) y **control inalámbrico mediante joystick o mando Bluetooth**.

Diseñado para escuchar libros, artículos y documentos mientras realizas actividades físicas o gimnasia, permitiendo pausar, retroceder y avanzar párrafos o líneas directamente con las teclas de tu mando sin tocar la pantalla o el teclado.

---

## 🌟 Características Principales

1. **Lectura de Documentos Completos:**
   - Soporte nativo para archivos **PDF** (`.pdf`), **EPUB** (`.epub`), **Texto Plano** (`.txt`) y **Markdown** (`.md`).
   - División inteligente en párrafos y oraciones estructuradas.
   - Limpieza automática de encabezados, números de página aislados y marcas de formato para una locución fluida.

2. **Control Inalámbrico con Joystick / Mando:**
   - Compatible con cualquier mando inalámbrico, Bluetooth o USB (como mandos de consola, mandos VR pequeños de una mano, GamepadPlus, etc.).
   - Lee eventos a nivel de kernel mediante `/dev/input/js*` sin necesidad de permisos root.
   - Detección automática en caliente (*hotplug*): enciende tu joystick en cualquier momento durante tu entrenamiento y se conectará solo.
   - Control total:
     - **Pausar / Reanudar:** Botón A / Cruz / Start.
     - **Retroceder Párrafo:** D-Pad Izquierda o L1.
     - **Avanzar Párrafo:** D-Pad Derecha o R1.
     - **Retroceder Línea (5 segundos):** Botón X / Cuadrado.
     - **Avanzar Línea (5 segundos):** Botón Y / Triángulo.
     - **Control de Volumen:** D-Pad Arriba / Abajo.
     - **Control de Velocidad:** Ajustable al vuelo.

3. **On-Screen Display (OSD) y Feedback Visual en Tiempo Real:**
   - Cada pulsación en el joystick inalámbrico o teclado muestra inmediatamente un banner flotante destacado (OSD) en pantalla con colores distintivos e iconos:
     - ⏸️ **PAUSA** (Ámbar)
     - ▶️ **CONTINUAR / REANUDAR** (Verde esmeralda)
     - ⏮️ **RETROCEDER PÁRRAFO** (Azul cielo)
     - ⏭️ **AVANZAR PÁRRAFO** (Azul cielo)
     - ⏪ / ⏩ **RETROCEDER / AVANZAR LÍNEA (5s)** (Índigo)
     - 🔊 / 🔉 **NIVEL DE VOLUMEN** (Púrpura)
     - ⚡ **RITMO DE VELOCIDAD** (Cian)
   - Envía además notificaciones nativas sincronizadas al escritorio Wayland/GNOME de CachyOS (`notify-send`), visible incluso si estás a distancia en el gimnasio o en otro espacio de trabajo.

4. **Explorador de Libros Integrado con CachyOS:**
   - **Selector Nativo de CachyOS:** Usa el diálogo oficial GTK4/GNOME de CachyOS (`zenity`) con tema oscuro, accesos directos, marcadores de carpetas y filtros.
   - **Explorador de Libros del Sistema:** Escanea al instante tus carpetas `~/Descargas` y `~/Documentos`, mostrando distintivos de formato (`[PDF]`, `[EPUB]`, `[TXT]`, `[MD]`), tamaño del archivo, fecha de modificación y botón directo *Abrir y Leer*.
   - **Buscador en Tiempo Real:** Filtra libros por título o nombre de archivo mientras escribes.
   - **Acceso Directo a Nautilus:** Botón para abrir la carpeta actual directamente en el gestor de archivos de CachyOS.

5. **Marcadores y Memoria de Lectura Automática:**
   - Guarda automáticamente el punto exacto de lectura para cada libro que abras en tu biblioteca (`~/.config/ai-reader/library.json`).
   - Al volver a abrir un libro, se reanuda de inmediato donde lo dejaste.

6. **Síntesis Neuronal con Pre-Carga Continua:**
   - Voces neuronales de alta fidelidad en español de Edge-TTS (Tomás, Elena, Jorge, Álvaro, Dalia, etc.).
   - **Pre-síntesis asíncrona:** Mientras escuchas el párrafo actual, el siguiente ya se sintetiza en segundo plano para una transición instantánea sin pausas.
   - **Respaldo Offline (Piper TTS):** Si no tienes internet durante el entrenamiento, utiliza automáticamente el modelo local de Piper (`es_ES-sharvard-medium.onnx`).

7. **Modo Mini Flotante (Gimnasio):**
   - Modo de ventana ultracompacta que se mantiene siempre visible (*Always on Top*) con visor de comandos OSD y botones táctiles gigantes para consultar el progreso mientras entrenas.

---

## 🚀 Instalación y Puesta en Marcha

Para registrar el proyecto en el menú de aplicaciones de GNOME y activar los atajos:

```bash
cd ~/LectorLibrosIA
bash install_desktop.sh
```

### Ejecución
- **Desde el menú de aplicaciones:** Busca `Lector de Libros IA`.
- **Desde consola:**
  ```bash
  ~/LectorLibrosIA/run.sh [ruta_al_libro.epub]
  ```
- **Con atajo global de GNOME:** <kbd>Ctrl</kbd> + <kbd>Alt</kbd> + <kbd>Super</kbd> + <kbd>V</kbd>

---

## 🎮 Guía de Teclas del Joystick

| Acción | Mando / Joystick | Teclado |
| :--- | :--- | :--- |
| **Pausar / Reanudar** | `Botón A` / `Cruz` / `Start` | <kbd>Espacio</kbd> |
| **Retroceder Párrafo** | `D-Pad Izquierda` o `L1` | <kbd>←</kbd> |
| **Avanzar Párrafo** | `D-Pad Derecha` o `R1` | <kbd>→</kbd> |
| **Retroceder Línea (-5s)** | `Botón X` / `Cuadrado` | <kbd>↑</kbd> |
| **Avanzar Línea (+5s)** | `Botón Y` / `Triángulo` | <kbd>↓</kbd> |
| **Subir Volumen** | `D-Pad Arriba` | <kbd>]</kbd> |
| **Bajar Volumen** | `D-Pad Abajo` | <kbd>[</kbd> |
| **Aumentar Velocidad** | `Select + D-Pad Arriba` | <kbd>+</kbd> |
| **Reducir Velocidad** | `Select + D-Pad Abajo` | <kbd>-</kbd> |

> 💡 *Puedes probar y calibrar cualquier tecla de tu mando pulsando el botón verde `🎮 Joystick` en la cabecera de la aplicación.*
