"""
Reproductor de audio inteligente basado en MPV para libros y documentos completos.
Gestiona la transición fluida entre párrafos, pre-síntesis, salto de línea/párrafo y comandos IPC.
"""

import os
import time
import json
import socket
import subprocess
import threading
from typing import Optional, Callable
from .config import SOCKET_FILE
from .document_parser import Document
from .tts_engine import TTSEngine


def send_mpv_command(cmd_list):
    """Envía una orden en formato JSON al socket UNIX de mpv."""
    if not os.path.exists(SOCKET_FILE):
        return None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.2)
        client.connect(SOCKET_FILE)
        msg = json.dumps({"command": cmd_list}) + "\n"
        client.sendall(msg.encode('utf-8'))
        client.close()
    except Exception:
        pass


def get_mpv_property(prop_name):
    """Consulta una propiedad interna de mpv (como time-pos o percent-pos)."""
    if not os.path.exists(SOCKET_FILE):
        return None
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.15)
        client.connect(SOCKET_FILE)
        msg = json.dumps({"command": ["get_property", prop_name]}) + "\n"
        client.sendall(msg.encode('utf-8'))
        response = client.recv(1024)
        client.close()
        if response:
            res = json.loads(response.decode('utf-8'))
            if res.get("error") == "success":
                return res.get("data")
    except Exception:
        pass
    return None


class BookPlayer:
    """Controla la lectura secuencial de párrafos y oraciones de un libro."""

    def __init__(self, tts_engine: TTSEngine):
        self.tts = tts_engine
        self.document: Optional[Document] = None
        self.current_paragraph_index: int = 0
        self.is_paused: bool = False
        self.is_playing: bool = False
        self.speed: float = 1.25
        self.volume: int = 100
        self.voice_label: str = "🇦🇷 Tomás (Argentina - Natural)"

        self.mpv_process: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        self.playback_token: int = 0  # Token de control para cancelar reproducciones obsoletas

        # Hilo de monitoreo de avance
        self.monitor_thread: Optional[threading.Thread] = None
        self.running: bool = False

        # Callbacks para la interfaz
        self.on_paragraph_change: Optional[Callable[[int], None]] = None
        self.on_progress: Optional[Callable[[int, float, float, float], None]] = None
        self.on_state_change: Optional[Callable[[str], None]] = None

    def start_monitor(self):
        """Inicia el monitoreo de estado de mpv en segundo plano."""
        if not self.running:
            self.running = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True, name="PlayerMonitor")
            self.monitor_thread.start()

    def stop_monitor(self):
        self.running = False

    def load_document(self, document: Document, start_paragraph: int = 0):
        """Carga un documento en el reproductor y posiciona el marcador."""
        self.stop()
        self.document = document
        self.current_paragraph_index = max(0, min(start_paragraph, document.total_paragraphs - 1))
        if self.on_paragraph_change:
            self.on_paragraph_change(self.current_paragraph_index)

    def play(self, paragraph_index: Optional[int] = None):
        """Comienza o reanuda la lectura en el párrafo especificado."""
        if not self.document or self.document.total_paragraphs == 0:
            return

        with self.lock:
            if paragraph_index is not None:
                self.current_paragraph_index = max(0, min(paragraph_index, self.document.total_paragraphs - 1))

            self.playback_token += 1
            token = self.playback_token
            self.is_paused = False
            self.is_playing = True

            if self.on_state_change:
                self.on_state_change("SYNTHESIZING")

            # Lanzar la síntesis y arranque en un hilo para no bloquear la interfaz ni los controles
            t = threading.Thread(target=self._play_worker, args=(self.current_paragraph_index, token), daemon=True)
            t.start()

    def _play_worker(self, index: int, token: int):
        """Hilo de síntesis y reproducción de un párrafo."""
        if not self.document or token != self.playback_token:
            return

        text = self.document.get_paragraph(index)
        if not text:
            # Párrafo vacío, pasar al siguiente
            self.next_paragraph()
            return

        # Pre-sintetizar el siguiente párrafo en segundo plano
        next_idx = index + 1
        if next_idx < self.document.total_paragraphs:
            next_text = self.document.get_paragraph(next_idx)
            if next_text:
                self.tts.pre_synthesize_async(next_text, self.voice_label)

        # Sintetizar párrafo actual
        audio_path = self.tts.synthesize(text, self.voice_label)

        if token != self.playback_token or not self.running:
            return

        if not audio_path or not os.path.exists(audio_path):
            if self.on_state_change:
                self.on_state_change("ERROR")
            return

        # Detener mpv anterior
        self._kill_mpv()

        # Iniciar mpv con socket IPC
        cmd = [
            "mpv",
            f"--input-ipc-server={SOCKET_FILE}",
            "--no-video",
            f"--speed={self.speed:.2f}",
            f"--volume={int(self.volume)}",
            "--keep-open=no",
            audio_path
        ]
        self.mpv_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        if self.on_paragraph_change:
            self.on_paragraph_change(index)
        if self.on_state_change:
            self.on_state_change("PLAYING")

    def toggle_pause(self):
        """Alterna entre pausar y reanudar la lectura."""
        if not self.is_playing or not self.mpv_process or self.mpv_process.poll() is not None:
            # Si no estaba reproduciendo, arrancar desde el párrafo actual
            self.play(self.current_paragraph_index)
            return

        self.is_paused = not self.is_paused
        send_mpv_command(["cycle", "pause"])

        if self.on_state_change:
            self.on_state_change("PAUSED" if self.is_paused else "PLAYING")

    def stop(self):
        """Detiene la reproducción actual."""
        with self.lock:
            self.playback_token += 1
            self.is_playing = False
            self.is_paused = False
            self._kill_mpv()
            if self.on_state_change:
                self.on_state_change("STOPPED")

    def _kill_mpv(self):
        """Termina procesos mpv existentes y limpia sockets."""
        send_mpv_command(["quit"])
        if self.mpv_process:
            try:
                self.mpv_process.terminate()
            except Exception:
                pass
            try:
                self.mpv_process.kill()
            except Exception:
                pass
            self.mpv_process = None
        subprocess.run(["pkill", "-9", "-f", "^mpv.*mpv_reader_socket"], stderr=subprocess.DEVNULL)
        if os.path.exists(SOCKET_FILE):
            try:
                os.remove(SOCKET_FILE)
            except Exception:
                pass

    def prev_paragraph(self):
        """Retrocede al párrafo anterior."""
        if not self.document:
            return
        new_idx = max(0, self.current_paragraph_index - 1)
        self.play(new_idx)

    def next_paragraph(self):
        """Avanza al siguiente párrafo."""
        if not self.document:
            return
        new_idx = self.current_paragraph_index + 1
        if new_idx < self.document.total_paragraphs:
            self.play(new_idx)
        else:
            self.stop()
            if self.on_state_change:
                self.on_state_change("COMPLETED")

    def prev_line(self):
        """Retrocede 5 segundos en el audio (línea anterior) o al párrafo anterior si está al inicio."""
        time_pos = get_mpv_property("time-pos")
        if time_pos is not None and time_pos > 3.0:
            send_mpv_command(["seek", -6])
        else:
            self.prev_paragraph()

    def next_line(self):
        """Avanza 5 segundos en el audio (línea siguiente)."""
        time_pos = get_mpv_property("time-pos")
        duration = get_mpv_property("duration")
        if time_pos is not None and duration is not None and (duration - time_pos) > 4.0:
            send_mpv_command(["seek", 6])
        else:
            self.next_paragraph()

    def set_speed(self, speed: float):
        """Ajusta dinámicamente la velocidad de lectura."""
        self.speed = max(0.5, min(2.5, float(speed)))
        send_mpv_command(["set_property", "speed", self.speed])

    def step_speed(self, delta: float):
        """Modifica la velocidad en pasos (ej. +/- 0.1x)."""
        self.set_speed(self.speed + delta)

    def set_volume(self, volume: int):
        """Ajusta dinámicamente el volumen."""
        self.volume = max(0, min(130, int(volume)))
        send_mpv_command(["set_property", "volume", self.volume])

    def step_volume(self, delta: int):
        """Modifica el volumen en pasos (ej. +/- 5%)."""
        self.set_volume(self.volume + delta)

    def _monitor_loop(self):
        """Monitorea periódicamente el progreso del párrafo actual y transiciona al siguiente."""
        while self.running:
            if self.is_playing and self.mpv_process and not self.is_paused:
                # Comprobar si mpv terminó el párrafo actual
                poll = self.mpv_process.poll()
                if poll is not None:
                    # El párrafo ha terminado de reproducirse, avanzar automáticamente
                    self.next_paragraph()
                    time.sleep(0.1)
                    continue

                # Consultar propiedades de tiempo
                t_pos = get_mpv_property("time-pos") or 0.0
                t_dur = get_mpv_property("duration") or 0.0
                percent = get_mpv_property("percent-pos") or 0.0

                if self.on_progress:
                    try:
                        self.on_progress(self.current_paragraph_index, float(t_pos), float(t_dur), float(percent))
                    except Exception:
                        pass

            time.sleep(0.2)
