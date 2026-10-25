#!/home/exequiel/.local/bin/.venv/bin/python
"""
Punto de entrada principal para el Lector de Libros IA.
"""

import sys
import os
import subprocess
import customtkinter as ctk

# Asegurar que el directorio del proyecto esté en sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from src.gui import LectorLibrosGUI, DragDropCTk


def main():
    initial_file = None
    initial_text = None

    # 1. Comprobar si se pasó un archivo como argumento
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if os.path.exists(arg) and os.path.isfile(arg):
            initial_file = os.path.abspath(arg)
        else:
            initial_text = " ".join(sys.argv[1:])

    # 2. Comprobar si se envió texto por tubería stdin
    if not initial_file and not initial_text:
        if not sys.stdin.isatty():
            try:
                stdin_text = sys.stdin.read().strip()
                if stdin_text:
                    initial_text = stdin_text
            except Exception:
                pass

    # 3. Comprobar portapapeles o selección primaria de Wayland si no se especificó archivo
    if not initial_file and not initial_text:
        try:
            # Captura rápida de selección primaria si existe
            res = subprocess.run(["wl-paste", "--primary"], capture_output=True, text=True, timeout=0.3)
            clip = res.stdout.strip()
            if clip and len(clip) > 5:
                initial_text = clip
        except Exception:
            pass

    # Arrancar la aplicación gráfica compatible con Drag & Drop
    root = DragDropCTk(className="lector-libros-ia")
    app = LectorLibrosGUI(root, initial_file=initial_file, initial_text=initial_text)
    root.mainloop()


if __name__ == "__main__":
    main()
