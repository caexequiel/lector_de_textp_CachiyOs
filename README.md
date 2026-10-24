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

3. **Marcadores y Memoria de Lectura Automática:**
   - Guarda automáticamente el punto exacto de lectura para cada libro que abras en tu biblioteca (`~/.config/ai-reader/library.json`).
   - Al volver a abrir un libro, se reanuda de inmediato donde lo dejaste.

4. **Síntesis Neuronal con Pre-Carga Continua:**
   - Voces neuronales de alta fidelidad en español de Edge-TTS (Tomás, Elena, Jorge, Álvaro, Dalia, etc.).
   - **Pre-síntesis asíncrona:** Mientras escuchas el párrafo actual, el siguiente ya se sintetiza en segundo plano para una transición instantánea sin pausas.
   - **Respaldo Offline (Piper TTS):** Si no tienes internet durante el entrenamiento, utiliza automáticamente el modelo local de Piper (`es_ES-sharvard-medium.onnx`).

5. **Modo Mini Flotante (Gimnasio):**
   - Modo de ventana ultracompacta que se mantiene siempre visible (*Always on Top*) con botones gigantes para consultar el progreso mientras usas otras aplicaciones o cronómetros.

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
