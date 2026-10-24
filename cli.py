#!/home/exequiel/.local/bin/.venv/bin/python
"""
Versión por consola del Lector de Libros IA con soporte para control de lectura.
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.document_parser import DocumentParser
from src.tts_engine import TTSEngine
from src.player import BookPlayer
from src.joystick_manager import JoystickManager
from src.config import load_config


def main():
    if len(sys.argv) < 2:
        print("Uso: python cli.py <ruta_archivo_o_texto>")
        sys.exit(1)

    target = sys.argv[1]
    if os.path.exists(target):
        doc = DocumentParser.load_file(target)
    else:
        text = " ".join(sys.argv[1:])
        doc = DocumentParser.from_text(text)

    cfg = load_config()
    tts = TTSEngine()
    player = BookPlayer(tts)
    player.voice_label = cfg.get("voice", "🇦🇷 Tomás (Argentina - Natural)")
    player.speed = float(cfg.get("speed", 1.25))
    player.volume = int(cfg.get("volume", 100))
    player.start_monitor()

    # Joystick
    joy = JoystickManager(cfg.get("joystick_map"))
    joy.on_action = lambda act: (
        player.toggle_pause() if act == "PLAY_PAUSE" else
        player.prev_paragraph() if act == "PREV_PARAGRAPH" else
        player.next_paragraph() if act == "NEXT_PARAGRAPH" else
        player.prev_line() if act == "PREV_LINE" else
        player.next_line() if act == "NEXT_LINE" else
        player.step_volume(5) if act == "VOL_UP" else
        player.step_volume(-5) if act == "VOL_DOWN" else None
    )
    joy.start()

    player.on_paragraph_change = lambda idx: print(f"\n[Párrafo {idx+1}/{doc.total_paragraphs}]: {doc.get_paragraph(idx)[:80]}...")
    player.load_document(doc)
    player.play(0)

    print(f"📖 Leyendo '{doc.title}' ({doc.total_paragraphs} párrafos)...")
    print("Controles de consola: [Espacio] Pausa | [n] Siguiente | [p] Anterior | [q] Salir")

    try:
        while True:
            cmd = input().strip().lower()
            if cmd == "q":
                break
            elif cmd in (" ", ""):
                player.toggle_pause()
            elif cmd == "n":
                player.next_paragraph()
            elif cmd == "p":
                player.prev_paragraph()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        player.stop()
        player.stop_monitor()
        joy.stop()


if __name__ == "__main__":
    main()
