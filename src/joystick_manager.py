"""
Controlador universal de Joystick y Mandos Inalámbricos / Bluetooth para Linux (CachyOS).
Lee eventos mediante el API estándar del kernel (/dev/input/js*) sin requerir permisos root.
Soporta hotplug (conexión en caliente), mapeo configurable de botones y prevención de rebotes.
"""

import os
import glob
import time
import struct
import fcntl
import threading
from typing import Optional, Callable, Dict
from .config import DEFAULT_JOYSTICK_MAP

# Constante ioctl para obtener el nombre legible del joystick
JSIOCGNAME_128 = 0x80806a13  # _IOC(_IOC_READ, 'j', 0x13, 128)

# Tipos de eventos del joystick en Linux
JS_EVENT_BUTTON = 0x01  # Botón presionado o liberado
JS_EVENT_AXIS = 0x02    # Eje o cruceta analógica/digital
JS_EVENT_INIT = 0x80    # Bandera de estado inicial


class JoystickManager:
    """Detecta y procesa órdenes de mandos y joysticks inalámbricos en segundo plano."""

    def __init__(self, action_map: Optional[Dict[str, str]] = None):
        self.action_map = action_map or dict(DEFAULT_JOYSTICK_MAP)
        self.running = False
        self.worker_thread: Optional[threading.Thread] = None
        self.current_device_path: Optional[str] = None
        self.current_device_name: str = "Ninguno"
        self.is_connected = False

        # Callbacks
        self.on_action: Optional[Callable[[str], None]] = None
        self.on_raw_event: Optional[Callable[[str, str, int, int], None]] = None
        self.on_connection_change: Optional[Callable[[bool, str], None]] = None

        # Control de rebote (debounce) para evitar saltos dobles al presionar
        self.last_action_time = 0.0
        self.debounce_seconds = 0.25

        # Estado de ejes para detectar movimiento discreto (D-Pad)
        self.last_axis_states: Dict[int, int] = {}

    def start(self):
        """Inicia el hilo de monitoreo y lectura continua."""
        if self.running:
            return
        self.running = True
        self.worker_thread = threading.Thread(target=self._run_loop, daemon=True, name="JoystickListener")
        self.worker_thread.start()

    def stop(self):
        """Detiene la lectura del joystick."""
        self.running = False

    def _get_device_name(self, fd: int) -> str:
        """Obtiene el nombre del mando a través de ioctl."""
        try:
            buf = bytearray(128)
            fcntl.ioctl(fd, JSIOCGNAME_128, buf)
            name = buf.split(b'\x00')[0].decode('utf-8', errors='replace').strip()
            return name if name else "Joystick Genérico"
        except Exception:
            return "Joystick Genérico"

    def _find_active_device(self) -> Optional[str]:
        """Busca dispositivos /dev/input/js* disponibles en el sistema."""
        devices = sorted(glob.glob("/dev/input/js*"))
        if not devices:
            return None
        # Preferir js1 o superiores si js0 es un puntero virtual (como keyd)
        for dev in devices:
            try:
                fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
                name = self._get_device_name(fd)
                os.close(fd)
                # Si no es un puntero virtual, es nuestro joystick preferido
                if "virtual pointer" not in name.lower():
                    return dev
            except Exception:
                continue
        # Si todos son iguales o solo hay uno, devolver el primero accesible
        for dev in devices:
            try:
                fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
                os.close(fd)
                return dev
            except Exception:
                continue
        return None

    def _run_loop(self):
        """Bucle principal de detección de mando y lectura de eventos."""
        while self.running:
            # Si no hay dispositivo conectado, buscarlo periódicamente
            if not self.current_device_path or not os.path.exists(self.current_device_path):
                dev_path = self._find_active_device()
                if dev_path:
                    try:
                        fd = os.open(dev_path, os.O_RDONLY | os.O_NONBLOCK)
                        dev_name = self._get_device_name(fd)
                        self.current_device_path = dev_path
                        self.current_device_name = dev_name
                        self.is_connected = True
                        if self.on_connection_change:
                            self.on_connection_change(True, dev_name)
                        self._read_device_events(fd)
                    except Exception:
                        pass
                else:
                    if self.is_connected:
                        self.is_connected = False
                        self.current_device_path = None
                        self.current_device_name = "Ninguno"
                        if self.on_connection_change:
                            self.on_connection_change(False, "Ninguno")
                    time.sleep(1.0)
            else:
                time.sleep(1.0)

    def _read_device_events(self, fd: int):
        """Lee paquetes continuos de 8 bytes del socket del joystick."""
        EVENT_FORMAT = '<IhBB'  # time (uint32), value (int16), type (uint8), number (uint8)
        EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

        try:
            while self.running:
                try:
                    data = os.read(fd, EVENT_SIZE)
                    if len(data) < EVENT_SIZE:
                        time.sleep(0.01)
                        continue

                    tv_time, value, ev_type, number = struct.unpack(EVENT_FORMAT, data)

                    # Ignorar eventos de inicialización sintéticos
                    if ev_type & JS_EVENT_INIT:
                        continue

                    # 1. Evento de Botón
                    if ev_type == JS_EVENT_BUTTON:
                        btn_key = f"btn_{number}"
                        if self.on_raw_event:
                            self.on_raw_event(self.current_device_name, "button", number, value)

                        # value == 1 indica botón presionado
                        if value == 1:
                            self._trigger_mapped_action(btn_key)

                    # 2. Evento de Eje (D-pad o Sticks analógicos)
                    elif ev_type == JS_EVENT_AXIS:
                        if self.on_raw_event:
                            self.on_raw_event(self.current_device_name, "axis", number, value)

                        # Detectar umbral de cruceta o inclinación de palanca
                        axis_dir = None
                        THRESHOLD = 18000
                        if value < -THRESHOLD:
                            axis_dir = "neg"
                        elif value > THRESHOLD:
                            axis_dir = "pos"

                        prev_state = self.last_axis_states.get(number, 0)
                        curr_state = -1 if value < -THRESHOLD else (1 if value > THRESHOLD else 0)

                        if curr_state != prev_state and curr_state != 0:
                            # Eje X = 0 (o 6 para D-Pad hats), Eje Y = 1 (o 7 para D-Pad hats)
                            axis_name = "axis_x" if number in (0, 6) else ("axis_y" if number in (1, 7) else f"axis_{number}")
                            axis_key = f"{axis_name}_{axis_dir}"
                            self._trigger_mapped_action(axis_key)

                        self.last_axis_states[number] = curr_state

                except BlockingIOError:
                    time.sleep(0.01)
                except (OSError, IOError):
                    # Dispositivo desconectado (ej. mando apagado por bluetooth)
                    break
        finally:
            try:
                os.close(fd)
            except Exception:
                pass
            self.is_connected = False
            self.current_device_path = None
            if self.on_connection_change:
                self.on_connection_change(False, "Ninguno")

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
