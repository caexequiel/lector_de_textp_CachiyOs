"""
Configuraciones globales, rutas de persistencia y constantes del Lector de Libros IA.
"""

import os
import re
import json
import subprocess

# Directorios de configuración y caché
CONFIG_DIR = os.path.expanduser("~/.config/ai-reader")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LIBRARY_FILE = os.path.join(CONFIG_DIR, "library.json")
CACHE_DIR = "/tmp/ai_reader_cache"

SOCKET_FILE = "/tmp/mpv_reader_socket"

# Rutas de Piper TTS offline
PIPER_BIN = os.path.expanduser("~/.local/bin/piper")
PIPER_MODEL = os.path.expanduser("~/.local/share/piper/es_ES-sharvard-medium.onnx")
PIPER_AVAILABLE = os.path.exists(PIPER_BIN) and os.path.exists(PIPER_MODEL)

# Voces neuronales de Edge-TTS y Piper
VOICES = {
    "🇦🇷 Tomás (Argentina - Natural)": "es-AR-TomasNeural",
    "🇦🇷 Elena (Argentina - Femenino)": "es-AR-ElenaNeural",
    "🇪🇸 Álvaro (España - Formal / Neutro)": "es-ES-AlvaroNeural",
    "🇪🇸 Elvira (España - Femenino)": "es-ES-ElviraNeural",
    "🇪🇸 Abríl (España - Suave)": "es-ES-AbrilNeural",
    "🇲🇽 Jorge (México - Clásico / Loquendo)": "es-MX-JorgeNeural",
    "🇲🇽 Dalia (México - Expresivo)": "es-MX-DaliaNeural",
    "🇨🇴 Gonzalo (Colombia - Claro)": "es-CO-GonzaloNeural",
    "🇨🇴 Salome (Colombia - Femenino)": "es-CO-SalomeNeural",
    "🇨🇱 Lorenzo (Chile - Neutro)": "es-CL-LorenzoNeural",
    "🇺🇸 Alonso (Latinoamérica / EE.UU.)": "es-US-AlonsoNeural",
    "🇺🇸 Paloma (Latinoamérica / EE.UU.)": "es-US-PalomaNeural",
}

if PIPER_AVAILABLE:
    VOICES["⚡ Piper (Español - Offline Local)"] = "piper:es_ES-sharvard-medium"

# Mapeo por defecto de botones de joystick/gamepad a acciones
DEFAULT_JOYSTICK_MAP = {
    # Botones principales (A, B, X, Y / Cruz, Círculo, Cuadrado, Triángulo)
    "btn_0": "PLAY_PAUSE",       # A / Cruz
    "btn_1": "STOP",             # B / Círculo
    "btn_2": "PREV_LINE",        # X / Cuadrado (Retroceder línea / 5s)
    "btn_3": "NEXT_LINE",        # Y / Triángulo (Avanzar línea / 5s)

    # Bumpers y Triggers (L1, R1, L2, R2)
    "btn_4": "PREV_PARAGRAPH",   # L1 (Retroceder párrafo)
    "btn_5": "NEXT_PARAGRAPH",   # R1 (Avanzar párrafo)
    "btn_6": "SPEED_DOWN",       # L2 / Select
    "btn_7": "SPEED_UP",         # R2 / Start
    "btn_8": "PLAY_PAUSE",       # Select / Back
    "btn_9": "PLAY_PAUSE",       # Start
    "btn_10": "PLAY_PAUSE",      # Botón central / Mode
    "btn_11": "PLAY_PAUSE",      # L3 (Stick izq)
    "btn_12": "PLAY_PAUSE",      # R3 (Stick der)

    # D-Pad / Cruceta (ejes o botones según el mando)
    "axis_x_neg": "PREV_PARAGRAPH", # D-Pad Izquierda
    "axis_x_pos": "NEXT_PARAGRAPH", # D-Pad Derecha
    "axis_y_neg": "VOL_UP",         # D-Pad Arriba (o Stick Arriba)
    "axis_y_pos": "VOL_DOWN",       # D-Pad Abajo (o Stick Abajo)
}


def load_config():
    """Carga la configuración del usuario con valores por defecto."""
    default_config = {
        "voice": list(VOICES.keys())[0],
        "speed": 1.25,
        "volume": 100,
        "auto_resume": True,
        "pre_synthesis": True,
        "joystick_map": dict(DEFAULT_JOYSTICK_MAP),
        "last_opened_file": None,
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if saved.get("voice") in VOICES:
                    default_config["voice"] = saved["voice"]
                if "speed" in saved:
                    default_config["speed"] = float(saved["speed"])
                if "volume" in saved:
                    default_config["volume"] = int(saved["volume"])
                if "auto_resume" in saved:
                    default_config["auto_resume"] = bool(saved["auto_resume"])
                if "pre_synthesis" in saved:
                    default_config["pre_synthesis"] = bool(saved["pre_synthesis"])
                if "joystick_map" in saved and isinstance(saved["joystick_map"], dict):
                    default_config["joystick_map"].update(saved["joystick_map"])
                if "last_opened_file" in saved:
                    default_config["last_opened_file"] = saved["last_opened_file"]
    except Exception:
        pass
    return default_config


def save_config(config_data):
    """Guarda la configuración del usuario en disco."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=4)
    except Exception:
        pass


def get_pipewire_sinks():
    """Detecta las salidas de audio en PipeWire y cuál es la predeterminada."""
    sinks = {}
    default_label = None
    try:
        res = subprocess.run(["wpctl", "status"], capture_output=True, text=True, timeout=2)
        in_sinks = False
        for line in res.stdout.splitlines():
            if "Sinks:" in line:
                in_sinks = True
                continue
            if in_sinks:
                if "Sources:" in line or "Filters:" in line or "Streams:" in line:
                    break
                match = re.search(r'([*]?)\s*(\d+)\.\s+(.+?)\s+\[vol:', line)
                if match:
                    is_default = (match.group(1) == '*')
                    sink_id = match.group(2)
                    name = match.group(3).strip()
                    label = f"{name} (ID: {sink_id})"
                    sinks[label] = sink_id
                    if is_default:
                        default_label = label
    except Exception:
        pass
    return sinks, default_label


def get_sink_volume_and_mute(sink_id="@DEFAULT_AUDIO_SINK@"):
    """Consulta volumen y estado de silencio en PipeWire."""
    try:
        res = subprocess.run(["wpctl", "get-volume", str(sink_id)], capture_output=True, text=True, timeout=1)
        is_muted = "MUTED" in res.stdout
        match = re.search(r'Volume:\s+([0-9.]+)', res.stdout)
        vol = float(match.group(1)) if match else 1.0
        return vol, is_muted
    except Exception:
        return 1.0, False


def unmute_sink(sink_id="@DEFAULT_AUDIO_SINK@"):
    """Desmutea la salida de audio."""
    try:
        subprocess.run(["wpctl", "set-mute", str(sink_id), "0"], check=False, timeout=1)
    except Exception:
        pass
