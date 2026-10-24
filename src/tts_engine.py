"""
Motor de Síntesis de Voz (TTS) con Edge-TTS en la nube y Piper local offline.
Incluye caché en disco y cola de pre-síntesis para lectura continua sin pausas.
"""

import os
import hashlib
import asyncio
import subprocess
import threading
from typing import Optional, Callable
import edge_tts
from .config import VOICES, PIPER_AVAILABLE, PIPER_BIN, PIPER_MODEL, CACHE_DIR


class TTSEngine:
    """Administra la generación y caché de audios neuronales y locales."""

    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.pre_synth_thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

    def _get_cache_path(self, text: str, voice_code: str) -> str:
        """Calcula el hash del texto y la voz para almacenar el archivo en caché."""
        data = f"{voice_code}:{text}".encode("utf-8")
        h = hashlib.md5(data).hexdigest()
        ext = ".wav" if voice_code.startswith("piper:") else ".mp3"
        return os.path.join(CACHE_DIR, f"{h}{ext}")

    def synthesize(self, text: str, voice_label: str) -> Optional[str]:
        """
        Sintetiza el texto con la voz indicada y retorna la ruta del archivo de audio.
        Si ya existe en caché, lo devuelve instantáneamente.
        """
        clean = text.strip()
        if not clean:
            return None

        voice_code = VOICES.get(voice_label, "es-AR-TomasNeural")
        cache_path = self._get_cache_path(clean, voice_code)

        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
            return cache_path

        # 1. Si es voz Piper local offline
        if voice_code.startswith("piper:"):
            ok = self._synthesize_piper(clean, cache_path)
            return cache_path if ok else None

        # 2. Síntesis online con Edge-TTS
        try:
            async def run_edge():
                comm = edge_tts.Communicate(clean, voice_code)
                await comm.save(cache_path)

            asyncio.run(run_edge())
            if os.path.exists(cache_path) and os.path.getsize(cache_path) > 100:
                return cache_path
        except Exception:
            # Fallback automático a Piper local si falla Edge-TTS (ej. sin internet)
            if PIPER_AVAILABLE:
                cache_piper = self._get_cache_path(clean, "piper:es_ES-sharvard-medium")
                if self._synthesize_piper(clean, cache_piper):
                    return cache_piper

        return None

    def _synthesize_piper(self, text: str, output_path: str) -> bool:
        """Genera audio local offline usando el binario de Piper."""
        if not PIPER_AVAILABLE:
            return False
        try:
            proc = subprocess.Popen(
                [PIPER_BIN, "--model", PIPER_MODEL, "--output_file", output_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            proc.communicate(input=text.encode("utf-8"), timeout=20)
            return os.path.exists(output_path) and os.path.getsize(output_path) > 100
        except Exception:
            return False

    def pre_synthesize_async(self, text: str, voice_label: str, callback: Optional[Callable[[str], None]] = None):
        """Genera el siguiente párrafo en segundo plano para tenerlo listo con antelación."""
        def worker():
            path = self.synthesize(text, voice_label)
            if path and callback:
                try:
                    callback(path)
                except Exception:
                    pass

        t = threading.Thread(target=worker, daemon=True)
        t.start()
