"""
Controlador universal de Joystick y Mandos Inalámbricos / Bluetooth para Linux (CachyOS).
Especializado en GameSir, Xbox 360, PlayStation, mandos Bluetooth y dongles inalámbricos 2.4G.
Lectura por kernel (/dev/input/js*), filtrado estricto de punteros virtuales (keyd),
detección instantánea de conexión en caliente (hotplug) y multiplexación no bloqueante con select.
"""

import os
import glob
import time
import struct
import fcntl
import select
import threading
from typing import Optional, Callable, Dict, List, Tuple
from .config import DEFAULT_JOYSTICK_MAP

# Constantes ioctl del kernel Linux para Joysticks
JSIOCGNAME_128 = 0x80806a13  # Nombre legible del mando
JSIOCGAXES = 0x80016a11      # Número de ejes
JSIOCGBUTTONS = 0x80016a12   # Número de botones

# Tipos de eventos
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80

# Dispositivos virtuales a ignorar (no son mandos de juego)
BLACKLIST = [
    "keyd",
    "virtual pointer",
    "virtual keyboard",
    "ydotoold",
    "touchpad",
    "synaptics",
    "trackpoint"
]


class JoystickManager:
    """Administra la conexión y lectura en segundo plano de mandos GameSir y joysticks."""

    def __init__(self, action_map: Optional[Dict[str, str]] = None):
        self.action_map = dict(DEFAULT_JOYSTICK_MAP)
        if action_map:
            self.action_map.update(action_map)

        self.running = False
        self.worker_thread: Optional[threading.Thread] = None

        self.current_device_path: Optional[str] = None
        self.current_device_name: str = "Buscando mando..."
        self.is_connected = False
        self.lock = threading.Lock()

        # Callbacks
        self.on_action: Optional[Callable[[str], None]] = None
        self.on_raw_event: Optional[Callable[[str, str, int, int], None]] = None
        self.on_connection_change: Optional[Callable[[bool, str], None]] = None

        # Control de rebote (debounce) para no disparar saltos repetidos
        self.last_action_time = 0.0
        self.debounce_seconds = 0.22

        # Estado de ejes para detectar transiciones de la cruceta/sticks
        self.last_axis_states: Dict[int, int] = {}

    def start(self):
        """Inicia el hilo de monitoreo y lectura continua."""
        if self.running:
            return
        self.running = True
        self.worker_thread = threading.Thread(target=self._run_loop, daemon=True, name="GameSirJoystickListener")
        self.worker_thread.start()

    def stop(self):
        """Detiene la lectura del joystick."""
        self.running = False

    @staticmethod
    def get_device_info(path: str) -> Optional[Tuple[str, int, int]]:
        """Devuelve (nombre_amigable, num_ejes, num_botones) para un dispositivo /dev/input/js*."""
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            buf = bytearray(128)
            fcntl.ioctl(fd, JSIOCGNAME_128, buf)
            name = buf.split(b'\x00')[0].decode('utf-8', errors='replace').strip()

            axes = bytearray(1)
            buttons = bytearray(1)
            try:
                fcntl.ioctl(fd, JSIOCGAXES, axes)
                fcntl.ioctl(fd, JSIOCGBUTTONS, buttons)
            except Exception:
                pass
            os.close(fd)

            # Verificar lista negra de dispositivos virtuales
            if any(b in name.lower() for b in BLACKLIST):
                return None

            # Mejorar el nombre para mandos GameSir / Xbox
            display_name = name
            if "x-box" in name.lower() or "xbox" in name.lower():
                display_name = f"GameSir / Xbox ({name})"
            elif not display_name:
                display_name = f"Mando USB ({os.path.basename(path)})"

            return display_name, axes[0], buttons[0]
        except Exception:
            return None

    def list_available_gamepads(self) -> List[Tuple[str, str]]:
        """Lista todos los mandos válidos conectados: [(path, nombre)]."""
        found = []
        for dev in sorted(glob.glob("/dev/input/js*")):
            info = self.get_device_info(dev)
            if info:
                found.append((dev, info[0]))
        return found

    def _find_best_gamepad(self) -> Optional[Tuple[str, str]]:
        """Selecciona el mejor mando real conectado, priorizando GameSir / Xbox."""
        pads = self.list_available_gamepads()
        if not pads:
            return None

        # Priorizar mandos GameSir / Xbox / Gamepad
        for path, name in pads:
            lower = name.lower()
            if "gamesir" in lower or "xbox" in lower or "pad" in lower or "joystick" in lower:
                return path, name

        return pads[0]

    def _run_loop(self):
        """Bucle supervisor: gestiona conexión, reconexión en caliente y lectura no bloqueante."""
        current_fd = -1

        while self.running:
            # 1. Si no hay mando abierto, buscarlo
            if current_fd < 0:
                best = self._find_best_gamepad()
                if best:
                    path, name = best
                    try:
                        current_fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                        self.current_device_path = path
                        self.current_device_name = name
                        self.is_connected = True
                        if self.on_connection_change:
                            self.on_connection_change(True, name)
                    except Exception:
                        current_fd = -1
                        time.sleep(0.5)
                        continue
                else:
                    if self.is_connected:
                        self.is_connected = False
                        self.current_device_path = None
                        self.current_device_name = "Desconectado"
                        if self.on_connection_change:
                            self.on_connection_change(False, "Desconectado")
                    time.sleep(0.8)
                    continue

            # 2. Leer eventos con select (timeout de 0.5s para no bloquear el hilo)
            try:
                rlist, _, _ = select.select([current_fd], [], [], 0.5)
            except Exception:
                # Dispositivo desconectado (dongle retirado o error)
                try:
                    os.close(current_fd)
                except Exception:
                    pass
                current_fd = -1
                self.is_connected = False
                continue

            if not rlist:
                # Timeout: verificar si el archivo sigue existiendo
                if not os.path.exists(self.current_device_path):
                    try:
                        os.close(current_fd)
                    except Exception:
                        pass
                    current_fd = -1
                    self.is_connected = False
                    if self.on_connection_change:
                        self.on_connection_change(False, "Desconectado")
                continue

            # 3. Procesar datos disponibles
            EVENT_FORMAT = '<IhBB'
            EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

            while True:
                try:
                    data = os.read(current_fd, EVENT_SIZE)
                    if len(data) < EVENT_SIZE:
                        break

                    tv_time, value, ev_type, number = struct.unpack(EVENT_FORMAT, data)

                    # Ignorar eventos de inicialización sintéticos
                    if ev_type & JS_EVENT_INIT:
                        continue

                    # BOTONES
                    if ev_type == JS_EVENT_BUTTON:
                        btn_key = f"btn_{number}"
                        if self.on_raw_event:
                            self.on_raw_event(self.current_device_name, "button", number, value)

                        if value == 1:
                            self._trigger_mapped_action(btn_key)

                    # EJES / CRUCETA (D-PAD)
                    elif ev_type == JS_EVENT_AXIS:
                        if self.on_raw_event:
                            self.on_raw_event(self.current_device_name, "axis", number, value)

                        # Umbral de zona muerta para evitar drift analógico
                        THRESHOLD = 16000
                        direction = None
                        if value < -THRESHOLD:
                            direction = "neg"
                        elif value > THRESHOLD:
                            direction = "pos"

                        curr_state = -1 if value < -THRESHOLD else (1 if value > THRESHOLD else 0)
                        prev_state = self.last_axis_states.get(number, 0)

                        if curr_state != prev_state and curr_state != 0 and direction:
                            # Disparar con clave específica del eje (ej: axis_6_neg para D-pad izquierda)
                            specific_key = f"axis_{number}_{direction}"
                            if specific_key in self.action_map:
                                self._trigger_mapped_action(specific_key)
                            else:
                                # Claves semánticas genéricas (axis_x / axis_y) de fallback
                                if number in (0, 6):  # Eje horizontal (Stick izq o D-Pad Hat)
                                    self._trigger_mapped_action(f"axis_x_{direction}")
                                elif number in (1, 7):  # Eje vertical (Stick izq o D-Pad Hat)
                                    self._trigger_mapped_action(f"axis_y_{direction}")

                        self.last_axis_states[number] = curr_state

                except BlockingIOError:
                    break
                except (OSError, IOError):
                    # Dispositivo desconectado
                    try:
                        os.close(current_fd)
                    except Exception:
                        pass
                    current_fd = -1
                    self.is_connected = False
                    if self.on_connection_change:
                        self.on_connection_change(False, "Desconectado")
                    break

        if current_fd >= 0:
            try:
                os.close(current_fd)
            except Exception:
                pass

    def _trigger_mapped_action(self, key_id: str):
        """Ejecuta la acción asignada si ha pasado el tiempo de debounce."""
        now = time.time()
        if now - self.last_action_time < self.debounce_seconds:
            return
        self.last_action_time = now

        action = self.action_map.get(key_id)
        if action and self.on_action:
            try:
                self.on_action(action)
            except Exception:
                pass
