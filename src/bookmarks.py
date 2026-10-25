"""
Gestor de marcadores y biblioteca para recordar la posición exacta de lectura en libros y documentos.
"""

import os
import json
from datetime import datetime
from typing import Dict, Any, Optional
from .config import LIBRARY_FILE, CONFIG_DIR


class BookmarkManager:
    """Administra el progreso de lectura y la biblioteca de libros recientes."""

    def __init__(self):
        self.library: Dict[str, Any] = {}
        self.load()

    def load(self):
        """Carga la biblioteca guardada."""
        try:
            if os.path.exists(LIBRARY_FILE):
                with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
                    self.library = json.load(f)
        except Exception:
            self.library = {}

    def save(self):
        """Guarda la biblioteca en disco."""
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(LIBRARY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.library, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def get_progress(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Obtiene el último punto de lectura de un archivo."""
        if not file_path:
            return None
        abs_path = os.path.abspath(file_path)
        return self.library.get(abs_path)

    def save_progress(self, file_path: str, title: str, current_paragraph: int, total_paragraphs: int):
        """Actualiza el marcador del documento actual."""
        if not file_path:
            return
        abs_path = os.path.abspath(file_path)
        percent = round((current_paragraph / max(total_paragraphs, 1)) * 100, 1)

        existing_entry = self.library.get(abs_path, {})
        existing_highlights = existing_entry.get("highlights", [])

        self.library[abs_path] = {
            "title": title,
            "path": abs_path,
            "current_paragraph": current_paragraph,
            "total_paragraphs": total_paragraphs,
            "progress_percent": percent,
            "last_read": datetime.now().isoformat(),
            "highlights": existing_highlights,
        }
        self.save()

    def add_highlight(self, file_path: str, highlight: Dict[str, Any]):
        """Agrega un fragmento resaltado al libro."""
        if not file_path:
            return
        abs_path = os.path.abspath(file_path)
        if abs_path not in self.library:
            self.library[abs_path] = {
                "title": os.path.basename(abs_path),
                "path": abs_path,
                "current_paragraph": 0,
                "total_paragraphs": 1,
                "progress_percent": 0.0,
                "last_read": datetime.now().isoformat(),
                "highlights": [],
            }
        if "highlights" not in self.library[abs_path]:
            self.library[abs_path]["highlights"] = []
        self.library[abs_path]["highlights"].append(highlight)
        self.save()

    def get_highlights(self, file_path: str) -> list:
        """Obtiene la lista de resaltados de un documento."""
        if not file_path:
            return []
        abs_path = os.path.abspath(file_path)
        return self.library.get(abs_path, {}).get("highlights", [])

    def remove_last_highlight(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Elimina el último fragmento resaltado (deshacer con RB)."""
        if not file_path:
            return None
        abs_path = os.path.abspath(file_path)
        if abs_path in self.library and self.library[abs_path].get("highlights"):
            removed = self.library[abs_path]["highlights"].pop()
            self.save()
            return removed
        return None

    def remove_highlight_by_id(self, file_path: str, highlight_id: str) -> bool:
        """Elimina un resaltado específico por su ID."""
        if not file_path or not highlight_id:
            return False
        abs_path = os.path.abspath(file_path)
        if abs_path in self.library and self.library[abs_path].get("highlights"):
            before = len(self.library[abs_path]["highlights"])
            self.library[abs_path]["highlights"] = [
                h for h in self.library[abs_path]["highlights"] if h.get("id") != highlight_id
            ]
            if len(self.library[abs_path]["highlights"]) < before:
                self.save()
                return True
        return False

    def get_recent_books(self, limit: int = 10):
        """Devuelve los libros más recientemente leídos ordenados por fecha."""
        books = list(self.library.values())
        books.sort(key=lambda b: b.get("last_read", ""), reverse=True)
        return books[:limit]

    def remove_book(self, file_path: str):
        """Elimina un libro de la biblioteca."""
        if not file_path:
            return
        abs_path = os.path.abspath(file_path)
        if abs_path in self.library:
            del self.library[abs_path]
            self.save()

    def cleanup_missing_books(self) -> int:
        """Elimina de la biblioteca libros que ya no existen en el disco."""
        to_delete = [p for p in self.library if not os.path.exists(p)]
        for p in to_delete:
            del self.library[p]
        if to_delete:
            self.save()
        return len(to_delete)

    def clear_library(self):
        """Vacía por completo todos los libros de la biblioteca."""
        self.library.clear()
        self.save()
