"""
Interfaz Gráfica Moderna (CustomTkinter) para Lector de Libros IA.
Visualización de documentos completos, navegación por párrafos,
control por joystick inalámbrico en tiempo real y Modo Mini Flotante para gimnasio.
"""

import os
import sys
import shutil
import subprocess
import threading
from datetime import datetime
from tkinter import filedialog
import customtkinter as ctk

from .config import (
    VOICES,
    load_config,
    save_config,
    get_pipewire_sinks,
    unmute_sink,
    get_sink_volume_and_mute,
    DEFAULT_JOYSTICK_MAP,
)
from .document_parser import DocumentParser, Document
from .bookmarks import BookmarkManager
from .tts_engine import TTSEngine
from .player import BookPlayer
from .joystick_manager import JoystickManager


def format_seconds(seconds: float) -> str:
    """Formatea segundos a MM:SS."""
    if not seconds or seconds < 0:
        return "00:00"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def format_filesize(bytes_size: int) -> str:
    """Formatea tamaño de archivo en bytes a KB o MB legibles."""
    if not bytes_size or bytes_size < 1024:
        return f"{bytes_size or 0} B"
    kb = bytes_size / 1024.0
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024.0
    return f"{mb:.2f} MB"


def open_cachyos_file_dialog(start_dir: str = None, directory_only: bool = False) -> str:
    """
    Abre el diálogo de archivos nativo de CachyOS (GTK4 / GNOME) usando zenity.
    Soporta temas oscuros, barra de marcadores del sistema y filtros de extensiones.
    Si zenity no está instalado o falla, recurre de forma transparente a filedialog de tkinter.
    """
    if shutil.which("zenity"):
        cmd = ["zenity", "--file-selection"]
        if directory_only:
            cmd.extend(["--directory", "--title=Seleccionar Carpeta — CachyOS"])
        else:
            cmd.extend([
                "--title=Seleccionar Libro o Documento — CachyOS",
                "--file-filter=Todos los libros (*.pdf, *.epub, *.txt, *.md) | *.pdf *.epub *.txt *.md *.PDF *.EPUB *.TXT *.MD",
                "--file-filter=Documentos PDF (*.pdf) | *.pdf *.PDF",
                "--file-filter=Libros EPUB (*.epub) | *.epub *.EPUB",
                "--file-filter=Texto Plano y Markdown (*.txt, *.md) | *.txt *.md *.TXT *.MD",
                "--file-filter=Todos los archivos | *"
            ])

        if start_dir and os.path.exists(start_dir):
            if os.path.isdir(start_dir):
                cmd.append(f"--filename={start_dir.rstrip('/')}/")
            else:
                cmd.append(f"--filename={start_dir}")

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0:
                selected = res.stdout.strip()
                if selected and os.path.exists(selected):
                    return selected
            elif res.returncode == 1:
                # El usuario canceló la selección deliberadamente
                return None
        except Exception as e:
            print(f"[CachyOS Dialog] Error ejecutando zenity: {e}")

    # Fallback con filedialog de tkinter
    if directory_only:
        return filedialog.askdirectory(
            initialdir=start_dir or os.path.expanduser("~"),
            title="Seleccionar Carpeta"
        )
    return filedialog.askopenfilename(
        initialdir=start_dir or os.path.expanduser("~"),
        title="Seleccionar libro o documento",
        filetypes=[
            ("Libros y Documentos", "*.pdf *.epub *.txt *.md"),
            ("Archivos PDF", "*.pdf"),
            ("Libros EPUB", "*.epub"),
            ("Texto Plano y Markdown", "*.txt *.md"),
            ("Todos los archivos", "*.*")
        ]
    )


def send_desktop_osd(title: str, subtitle: str = ""):
    """Envía notificación OSD nativa al escritorio de CachyOS (Wayland / GNOME)."""
    def _notify():
        try:
            if shutil.which("notify-send"):
                subprocess.run(
                    [
                        "notify-send",
                        "-a", "Lector Libros IA",
                        "-h", "string:x-canonical-private-synchronous:osd",
                        "-u", "low",
                        "-t", "1400",
                        title,
                        subtitle or ""
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        except Exception:
            pass

    threading.Thread(target=_notify, daemon=True).start()



class LectorLibrosGUI:
    """Ventana principal del lector de libros y documentos con soporte para joystick."""

    def __init__(self, root: ctk.CTk, initial_file: str = None, initial_text: str = None):
        self.root = root
        self.config = load_config()
        self.bookmarks = BookmarkManager()
        self.tts = TTSEngine()
        self.player = BookPlayer(self.tts)
        self.joystick = JoystickManager(self.config.get("joystick_map", DEFAULT_JOYSTICK_MAP))

        self.document: Document = None
        self.is_mini = False
        self.last_highlighted_para = -1
        self.osd_timer = None

        # Configuración de ventana
        self.root.title("Lector de Libros IA — Modo Entrenamiento")
        self.root.geometry("960x620")
        self.root.minsize(780, 500)
        self.root.resizable(True, True)
        self.root.attributes("-topmost", False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # Conectar callbacks del reproductor
        self.player.on_paragraph_change = self._on_paragraph_changed
        self.player.on_progress = self._on_progress_update
        self.player.on_state_change = self._on_state_changed
        self.player.voice_label = self.config.get("voice", list(VOICES.keys())[0])
        self.player.speed = float(self.config.get("speed", 1.25))
        self.player.volume = int(self.config.get("volume", 100))
        self.player.start_monitor()

        # Conectar callbacks del joystick
        self.joystick.on_action = self._handle_joystick_action
        self.joystick.on_connection_change = self._on_joystick_connection_change
        self.joystick.start()

        # Construir UI
        self.build_ui()

        # Si el joystick ya se detectó, actualizar badge de inmediato
        if self.joystick.is_connected:
            self._on_joystick_connection_change(True, self.joystick.current_device_name)

        # Atajos de teclado sincronizados con el OSD y joystick
        self.root.bind("<space>", lambda e: self._handle_joystick_action("PLAY_PAUSE"))
        self.root.bind("<Left>", lambda e: self._handle_joystick_action("PREV_PARAGRAPH"))
        self.root.bind("<Right>", lambda e: self._handle_joystick_action("NEXT_PARAGRAPH"))
        self.root.bind("<Up>", lambda e: self._handle_joystick_action("PREV_LINE"))
        self.root.bind("<Down>", lambda e: self._handle_joystick_action("NEXT_LINE"))
        self.root.bind("<plus>", lambda e: self._handle_joystick_action("SPEED_UP"))
        self.root.bind("<minus>", lambda e: self._handle_joystick_action("SPEED_DOWN"))

        # Cargar documento inicial si se proporcionó
        if initial_file and os.path.exists(initial_file):
            self.open_document_path(initial_file)
        elif initial_text:
            doc = DocumentParser.from_text(initial_text, "Texto Seleccionado")
            self.set_document(doc)
        elif self.config.get("last_opened_file") and os.path.exists(self.config["last_opened_file"]):
            self.open_document_path(self.config["last_opened_file"])
        else:
            # Documento de bienvenida con instrucciones
            welcome_text = (
                "¡Bienvenido a tu Lector de Libros IA!\n\n"
                "Para comenzar a escuchar mientras haces gimnasia:\n"
                "1. Haz clic en '📂 Abrir Libro' para cargar cualquier archivo PDF, EPUB o TXT.\n"
                "2. Conecta tu joystick o mando inalámbrico (Bluetooth o USB).\n"
                "3. ¡Usa las teclas del joystick para reproducir, pausar y retroceder párrafos o líneas con total comodidad!\n\n"
                "Controles del Joystick por defecto:\n"
                "• [A / Cruz / Start]: Pausar y Reanudar la lectura.\n"
                "• [D-Pad Izquierda / L1]: Retroceder un párrafo completo.\n"
                "• [D-Pad Derecha / R1]: Avanzar un párrafo completo.\n"
                "• [X / Cuadrado]: Retroceder una línea / 5 segundos.\n"
                "• [Y / Triángulo]: Avanzar una línea / 5 segundos.\n"
                "• [D-Pad Arriba / Abajo]: Subir o Bajar volumen."
            )
            doc = DocumentParser.from_text(welcome_text, "Guía de Inicio")
            self.set_document(doc)

    # --------------------------------------------------------------------------
    # CONSTRUCCIÓN DE INTERFAZ
    # --------------------------------------------------------------------------
    def build_ui(self):
        # 1. CONTENEDOR PRINCIPAL
        self.main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.main_frame.pack(fill="both", expand=True, padx=15, pady=12)

        # Barra superior (Header)
        header_bar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        header_bar.pack(fill="x", pady=(0, 10))

        self.title_label = ctk.CTkLabel(
            header_bar,
            text="📖 Lector de Libros IA",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.title_label.pack(side="left")

        # Botón Modo Mini
        self.btn_mini = ctk.CTkButton(
            header_bar,
            text="🔽 Modo Mini (Gimnasio)",
            width=140,
            command=self.toggle_mini,
            fg_color="gray25",
            hover_color="gray35"
        )
        self.btn_mini.pack(side="right", padx=(6, 0))

        # Indicador de estado del joystick (Badge interactivo)
        self.badge_joystick = ctk.CTkButton(
            header_bar,
            text="🎮 Joystick: Buscando...",
            width=160,
            command=self.open_joystick_modal,
            fg_color="#334155",
            hover_color="#475569",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.badge_joystick.pack(side="right", padx=(6, 0))

        # Botón Biblioteca
        self.btn_library = ctk.CTkButton(
            header_bar,
            text="📚 Biblioteca",
            width=100,
            command=self.open_library_modal,
            fg_color="gray25",
            hover_color="gray35"
        )
        self.btn_library.pack(side="right", padx=(6, 0))

        # Botón Abrir Documento
        self.btn_open = ctk.CTkButton(
            header_bar,
            text="📂 Abrir Libro",
            width=110,
            command=self.select_file_dialog,
            fg_color="#0284c7",
            hover_color="#0369a1",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.btn_open.pack(side="right")

        # 2. CUERPO DIVIDIDO (VISOR DE PÁRRAFOS + CONTROLES)
        self.split_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.split_frame.pack(fill="both", expand=True)

        # ::: PANEL IZQUIERDO: VISOR DE LIBRO Y PÁRRAFOS :::
        self.left_panel = ctk.CTkFrame(self.split_frame, fg_color="transparent")
        self.left_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))

        doc_info_bar = ctk.CTkFrame(self.left_panel, fg_color="transparent")
        doc_info_bar.pack(fill="x", pady=(0, 6))

        self.doc_name_label = ctk.CTkLabel(
            doc_info_bar,
            text="Documento no cargado",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#38bdf8"
        )
        self.doc_name_label.pack(side="left")

        self.para_count_label = ctk.CTkLabel(
            doc_info_bar,
            text="Párrafo: 0 / 0",
            font=ctk.CTkFont(size=12),
            text_color="gray70"
        )
        self.para_count_label.pack(side="right")

        # Caja de texto enriquecido para el documento completo
        self.text_box = ctk.CTkTextbox(
            self.left_panel,
            wrap="word",
            corner_radius=10,
            font=ctk.CTkFont(size=14)
        )
        self.text_box.pack(fill="both", expand=True)

        # Configurar estilos de resaltado
        # Párrafo activo actual (fondo azul suave con texto destacado)
        self.text_box._textbox.tag_config(
            "active_paragraph",
            background="#0369a1",
            foreground="#ffffff",
            spacing1=4,
            spacing3=4
        )
        # Resaltado de progreso dentro del párrafo (azul celeste brillante)
        self.text_box._textbox.tag_config(
            "read_progress",
            background="#0284c7",
            foreground="#ffffff"
        )

        # Permitir hacer clic en cualquier parte del texto para saltar a ese párrafo
        self.text_box._textbox.bind("<Button-1>", self._on_text_click)

        # Overlay flotante On-Screen Display (OSD) para comandos de joystick/teclado
        self.osd_frame = ctk.CTkFrame(
            self.left_panel,
            corner_radius=18,
            fg_color="#0f172a",
            border_width=2,
            border_color="#38bdf8"
        )
        osd_inner = ctk.CTkFrame(self.osd_frame, fg_color="transparent")
        osd_inner.pack(padx=28, pady=16)

        self.osd_icon_label = ctk.CTkLabel(
            osd_inner,
            text="🎮",
            font=ctk.CTkFont(size=36)
        )
        self.osd_icon_label.pack(side="left", padx=(0, 16))

        osd_text_box = ctk.CTkFrame(osd_inner, fg_color="transparent")
        osd_text_box.pack(side="left")

        self.osd_title_label = ctk.CTkLabel(
            osd_text_box,
            text="COMANDO",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#38bdf8",
            anchor="w"
        )
        self.osd_title_label.pack(fill="x")

        self.osd_subtitle_label = ctk.CTkLabel(
            osd_text_box,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8",
            anchor="w"
        )
        self.osd_subtitle_label.pack(fill="x")

        # ::: PANEL DERECHO: TARJETAS DE CONTROLES MULTIMEDIA Y JOYSTICK :::
        self.right_panel = ctk.CTkFrame(self.split_frame, fg_color="transparent", width=320)
        self.right_panel.pack(side="right", fill="y", expand=False)
        self.right_panel.pack_propagate(False)

        # TARJETA 1: Reproductor y Navegación de Párrafos
        player_card = ctk.CTkFrame(self.right_panel, corner_radius=10)
        player_card.pack(fill="x", pady=(0, 10), ipadx=8, ipady=8)

        ctk.CTkLabel(
            player_card,
            text="Control de Lectura:",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(anchor="w", padx=12, pady=(2, 6))

        # Tiempos del párrafo
        time_frame = ctk.CTkFrame(player_card, fg_color="transparent")
        time_frame.pack(fill="x", padx=12, pady=(0, 4))
        self.lbl_time_pos = ctk.CTkLabel(time_frame, text="00:00", font=ctk.CTkFont(size=11), text_color="gray70")
        self.lbl_time_pos.pack(side="left")
        self.lbl_time_dur = ctk.CTkLabel(time_frame, text="00:00", font=ctk.CTkFont(size=11), text_color="gray70")
        self.lbl_time_dur.pack(side="right")

        self.progress_bar = ctk.CTkProgressBar(player_card, height=8, progress_color="#38bdf8")
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", padx=12, pady=(0, 10))

        # Botonera Principal (Play / Pause grande)
        self.btn_play_pause = ctk.CTkButton(
            player_card,
            text="▶️ Iniciar Lectura",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=38,
            fg_color="#0284c7",
            hover_color="#0369a1",
            command=lambda: self._handle_joystick_action("PLAY_PAUSE")
        )
        self.btn_play_pause.pack(fill="x", padx=12, pady=(0, 8))

        # Fila 1 de navegación: Párrafos
        nav_para_frame = ctk.CTkFrame(player_card, fg_color="transparent")
        nav_para_frame.pack(fill="x", padx=8, pady=(0, 4))
        nav_para_frame.grid_columnconfigure((0, 1), weight=1)

        self.btn_prev_para = ctk.CTkButton(
            nav_para_frame,
            text="⏮ Párrafo Ant.",
            command=lambda: self._handle_joystick_action("PREV_PARAGRAPH"),
            fg_color="gray30",
            hover_color="gray40"
        )
        self.btn_prev_para.grid(row=0, column=0, padx=3, pady=2, sticky="ew")

        self.btn_next_para = ctk.CTkButton(
            nav_para_frame,
            text="⏭ Párrafo Sig.",
            command=lambda: self._handle_joystick_action("NEXT_PARAGRAPH"),
            fg_color="gray30",
            hover_color="gray40"
        )
        self.btn_next_para.grid(row=0, column=1, padx=3, pady=2, sticky="ew")

        # Fila 2 de navegación: Líneas / 5 segundos
        nav_line_frame = ctk.CTkFrame(player_card, fg_color="transparent")
        nav_line_frame.pack(fill="x", padx=8, pady=(0, 6))
        nav_line_frame.grid_columnconfigure((0, 1), weight=1)

        self.btn_prev_line = ctk.CTkButton(
            nav_line_frame,
            text="⏪ -5s (Línea)",
            command=lambda: self._handle_joystick_action("PREV_LINE"),
            fg_color="gray25",
            hover_color="gray35"
        )
        self.btn_prev_line.grid(row=0, column=0, padx=3, pady=2, sticky="ew")

        self.btn_next_line = ctk.CTkButton(
            nav_line_frame,
            text="⏩ +5s (Línea)",
            command=lambda: self._handle_joystick_action("NEXT_LINE"),
            fg_color="gray25",
            hover_color="gray35"
        )
        self.btn_next_line.grid(row=0, column=1, padx=3, pady=2, sticky="ew")

        # TARJETA 2: Velocidad y Volumen
        settings_card = ctk.CTkFrame(self.right_panel, corner_radius=10)
        settings_card.pack(fill="x", pady=(0, 10), ipadx=8, ipady=6)

        # Velocidad
        spd_hdr = ctk.CTkFrame(settings_card, fg_color="transparent")
        spd_hdr.pack(fill="x", padx=12, pady=(4, 2))
        ctk.CTkLabel(spd_hdr, text="Velocidad:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        self.lbl_speed = ctk.CTkLabel(spd_hdr, text=f"{self.player.speed:.2f}x", font=ctk.CTkFont(size=12))
        self.lbl_speed.pack(side="right")

        self.scale_speed = ctk.CTkSlider(settings_card, from_=0.5, to=2.5, command=self._on_speed_slider)
        self.scale_speed.set(self.player.speed)
        self.scale_speed.pack(fill="x", padx=12, pady=(0, 8))

        # Volumen
        vol_hdr = ctk.CTkFrame(settings_card, fg_color="transparent")
        vol_hdr.pack(fill="x", padx=12, pady=(4, 2))
        ctk.CTkLabel(vol_hdr, text="Volumen:", font=ctk.CTkFont(size=12, weight="bold")).pack(side="left")
        self.lbl_volume = ctk.CTkLabel(vol_hdr, text=f"{self.player.volume}%", font=ctk.CTkFont(size=12))
        self.lbl_volume.pack(side="right")

        self.scale_vol = ctk.CTkSlider(settings_card, from_=0, to=130, command=self._on_volume_slider)
        self.scale_vol.set(self.player.volume)
        self.scale_vol.pack(fill="x", padx=12, pady=(0, 8))

        # TARJETA 3: Selección de Voz Neuronal y Salida
        voice_card = ctk.CTkFrame(self.right_panel, corner_radius=10)
        voice_card.pack(fill="x", pady=(0, 10), ipadx=8, ipady=6)

        ctk.CTkLabel(voice_card, text="Voz Neuronal:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=12, pady=(4, 2))
        self.combo_voice = ctk.CTkOptionMenu(voice_card, values=list(VOICES.keys()), command=self._on_voice_selected, width=280)
        self.combo_voice.set(self.player.voice_label)
        self.combo_voice.pack(padx=12, pady=(0, 8), fill="x")

        ctk.CTkLabel(voice_card, text="Salida de Audio:", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=12, pady=(2, 2))
        self.sinks_map, default_sink_label = get_pipewire_sinks()
        sink_names = list(self.sinks_map.keys()) if self.sinks_map else ["Por defecto"]
        self.combo_sink = ctk.CTkOptionMenu(voice_card, values=sink_names, command=self._on_sink_selected, width=280)
        if default_sink_label and default_sink_label in sink_names:
            self.combo_sink.set(default_sink_label)
        elif sink_names:
            self.combo_sink.set(sink_names[0])
        self.combo_sink.pack(padx=12, pady=(0, 6), fill="x")

        # Estado inferior
        self.status_label = ctk.CTkLabel(
            self.right_panel,
            text="Listo para reproducir",
            text_color="#57A868",
            font=ctk.CTkFont(slant="italic", size=12)
        )
        self.status_label.pack(pady=(4, 0))

        # 3. CONTENEDOR MODO MINI (FLOTANTE PARA GIMNASIO)
        self.mini_frame = ctk.CTkFrame(self.root, fg_color="transparent")

        self.lbl_mini_osd = ctk.CTkLabel(
            self.mini_frame,
            text="🎮 Modo Gimnasio",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        self.lbl_mini_osd.pack(side="top", pady=(4, 2))

        mini_btn_row = ctk.CTkFrame(self.mini_frame, fg_color="transparent")
        mini_btn_row.pack(side="top", fill="x")

        self.btn_mini_prev = ctk.CTkButton(
            mini_btn_row,
            text="⏮",
            width=48, height=48, corner_radius=24,
            fg_color="gray25", hover_color="gray35",
            font=ctk.CTkFont(size=18, weight="bold"),
            command=lambda: self._handle_joystick_action("PREV_PARAGRAPH")
        )
        self.btn_mini_prev.pack(side="left", padx=4, pady=4)

        self.btn_mini_play = ctk.CTkButton(
            mini_btn_row,
            text="▶",
            width=56, height=56, corner_radius=28,
            fg_color="#38bdf8", hover_color="#0ea5e9",
            text_color="#0f172a",
            font=ctk.CTkFont(size=24, weight="bold"),
            command=lambda: self._handle_joystick_action("PLAY_PAUSE")
        )
        self.btn_mini_play.pack(side="left", padx=6, pady=4)

        self.btn_mini_next = ctk.CTkButton(
            mini_btn_row,
            text="⏭",
            width=48, height=48, corner_radius=24,
            fg_color="gray25", hover_color="gray35",
            font=ctk.CTkFont(size=18, weight="bold"),
            command=lambda: self._handle_joystick_action("NEXT_PARAGRAPH")
        )
        self.btn_mini_next.pack(side="left", padx=4, pady=4)

        self.btn_mini_expand = ctk.CTkButton(
            mini_btn_row,
            text="⤢",
            width=48, height=48, corner_radius=24,
            fg_color="gray25", hover_color="gray35",
            text_color="#f8fafc",
            font=ctk.CTkFont(size=18, weight="bold"),
            command=self.toggle_mini
        )
        self.btn_mini_expand.pack(side="left", padx=4, pady=4)

    # --------------------------------------------------------------------------
    # MODO MINI PARA GIMNASIO
    # --------------------------------------------------------------------------
    def toggle_mini(self):
        """Conmuta a una ventana compacta que puede estar siempre encima durante el entrenamiento."""
        self.is_mini = not self.is_mini
        if self.is_mini:
            self.main_frame.pack_forget()
            self.root.minsize(300, 112)
            self.root.resizable(False, False)
            self.root.attributes("-topmost", True)  # Siempre visible mientras entrenas
            self.root.update_idletasks()
            self.root.geometry("300x112")
            self.mini_frame.pack(expand=True, fill="both", padx=8, pady=4)
        else:
            self.mini_frame.pack_forget()
            self.root.minsize(780, 500)
            self.root.resizable(True, True)
            self.root.attributes("-topmost", False)
            self.root.update_idletasks()
            self.root.geometry("960x620")
            self.main_frame.pack(fill="both", expand=True, padx=15, pady=12)

    # --------------------------------------------------------------------------
    # GESTIÓN DE DOCUMENTOS
    # --------------------------------------------------------------------------
    def select_file_dialog(self):
        """Abre el diálogo de archivos nativo de CachyOS (GTK4/Zenity) para seleccionar un libro."""
        last_dir = None
        if self.document and self.document.file_path:
            last_dir = os.path.dirname(self.document.file_path)
        elif self.config.get("last_opened_file"):
            last_dir = os.path.dirname(self.config["last_opened_file"])
        else:
            last_dir = os.path.expanduser("~/Descargas")
            if not os.path.exists(last_dir):
                last_dir = os.path.expanduser("~/Documentos")

        path = open_cachyos_file_dialog(last_dir)
        if path:
            self.open_document_path(path)

    def open_document_path(self, file_path: str):
        """Carga un documento desde el disco y restaura su marcador."""
        try:
            self.status_label.configure(text="⏳ Cargando documento...", text_color="#38bdf8")
            self.root.update_idletasks()

            doc = DocumentParser.load_file(file_path)
            self.set_document(doc)

            # Recordar archivo
            self.config["last_opened_file"] = file_path
            save_config(self.config)

            # Notificar en OSD
            self.show_osd("LIBRO CARGADO", doc.title[:45], icon="📖", color="#10b981")

            # Restaurar punto de lectura si existe en la biblioteca
            prog = self.bookmarks.get_progress(file_path)
            if prog and self.config.get("auto_resume", True):
                start_p = prog.get("current_paragraph", 0)
                if start_p > 0 and start_p < doc.total_paragraphs:
                    self.player.current_paragraph_index = start_p
                    self._highlight_paragraph(start_p)
                    self.status_label.configure(
                        text=f"🔖 Reanudado en párrafo {start_p + 1} de {doc.total_paragraphs}",
                        text_color="#38bdf8"
                    )
        except Exception as e:
            self.status_label.configure(text=f"Error cargando archivo: {e}", text_color="#C25450")

    def set_document(self, document: Document):
        """Asigna un nuevo documento al visor y reproductor."""
        self.document = document
        self.player.load_document(document)

        # Actualizar información visual
        self.doc_name_label.configure(text=document.title[:40])
        est_min = document.estimated_duration_minutes(self.player.speed)
        self.para_count_label.configure(text=f"Párrafo: 1 / {document.total_paragraphs} (~{est_min} min)")

        # Llenar la caja de texto
        tb = self.text_box._textbox
        tb.configure(state="normal")
        tb.delete("1.0", "end")

        # Insertar párrafos con marcas de índice
        for i, p in enumerate(document.paragraphs):
            start_idx = tb.index("end-1c")
            tb.insert("end", f"{p}\n\n")
            end_idx = tb.index("end-1c")
            tb.tag_add(f"para_{i}", start_idx, end_idx)

        tb.configure(state="disabled")
        self._highlight_paragraph(0)

    def _highlight_paragraph(self, index: int):
        """Resalta visualmente el párrafo activo y hace scroll automático."""
        if not self.document or index < 0 or index >= self.document.total_paragraphs:
            return

        tb = self.text_box._textbox
        tb.tag_remove("active_paragraph", "1.0", "end")
        tb.tag_remove("read_progress", "1.0", "end")

        tag_name = f"para_{index}"
        ranges = tb.tag_ranges(tag_name)
        if ranges:
            tb.tag_add("active_paragraph", ranges[0], ranges[1])
            tb.see(ranges[0])

        self.last_highlighted_para = index
        self.para_count_label.configure(
            text=f"Párrafo: {index + 1} / {self.document.total_paragraphs}"
        )

        # Guardar progreso en la biblioteca
        if self.document.file_path:
            self.bookmarks.save_progress(
                self.document.file_path,
                self.document.title,
                index,
                self.document.total_paragraphs
            )

    def _on_text_click(self, event):
        """Permite hacer clic sobre cualquier párrafo para empezar a leer desde allí."""
        if not self.document:
            return
        tb = self.text_box._textbox
        click_index = tb.index(f"@{event.x},{event.y}")

        # Identificar a qué párrafo pertenece
        for i in range(self.document.total_paragraphs):
            tag_name = f"para_{i}"
            ranges = tb.tag_ranges(tag_name)
            if ranges and tb.compare(ranges[0], "<=", click_index) and tb.compare(click_index, "<=", ranges[1]):
                self.player.play(i)
                break

    # --------------------------------------------------------------------------
    # CALLBACKS DEL REPRODUCTOR
    # --------------------------------------------------------------------------
    def _on_paragraph_changed(self, index: int):
        """Se ejecuta en el hilo de reproducción cuando cambia de párrafo."""
        self.root.after(0, lambda: self._highlight_paragraph(index))

    def _on_progress_update(self, para_idx: int, t_pos: float, t_dur: float, percent: float):
        """Actualiza los cronómetros y el resaltado interno."""
        def update_ui():
            self.lbl_time_pos.configure(text=format_seconds(t_pos))
            self.lbl_time_dur.configure(text=format_seconds(t_dur))
            if t_dur > 0:
                self.progress_bar.set(min(1.0, max(0.0, t_pos / t_dur)))

            # Resaltado de progreso dentro del párrafo
            tb = self.text_box._textbox
            tag_name = f"para_{para_idx}"
            ranges = tb.tag_ranges(tag_name)
            if ranges and percent > 0:
                start_p = ranges[0]
                total_len = len(self.document.get_paragraph(para_idx))
                curr_chars = int(total_len * (percent / 100.0))
                if curr_chars > 0:
                    prog_end = f"{start_p} + {curr_chars} chars"
                    tb.tag_remove("read_progress", start_p, ranges[1])
                    tb.tag_add("read_progress", start_p, prog_end)

        self.root.after(0, update_ui)

    def _on_state_changed(self, state: str):
        """Actualiza los botones de play/pause y el texto de estado."""
        def update_state():
            if state == "PLAYING":
                self.btn_play_pause.configure(text="⏸️ Pausar", fg_color="#0284c7")
                self.btn_mini_play.configure(text="⏸", fg_color="#38bdf8")
                self.status_label.configure(text="▶️ Leyendo...", text_color="#57A868")
            elif state == "PAUSED":
                self.btn_play_pause.configure(text="▶️ Reanudar", fg_color="#57A868")
                self.btn_mini_play.configure(text="▶", fg_color="#38bdf8")
                self.status_label.configure(text="⏸️ En pausa", text_color="#E5B567")
            elif state == "SYNTHESIZING":
                self.status_label.configure(text="⏳ Sintetizando audio...", text_color="#38bdf8")
            elif state == "STOPPED":
                self.btn_play_pause.configure(text="▶️ Iniciar Lectura", fg_color="#0284c7")
                self.btn_mini_play.configure(text="▶", fg_color="#38bdf8")
                self.status_label.configure(text="⏹️ Detenido", text_color="gray70")
            elif state == "COMPLETED":
                self.btn_play_pause.configure(text="▶️ Repetir", fg_color="#57A868")
                self.btn_mini_play.configure(text="▶", fg_color="#38bdf8")
                self.status_label.configure(text="✅ Lectura finalizada", text_color="#57A868")
            elif state == "ERROR":
                self.status_label.configure(text="⚠️ Error al sintetizar audio", text_color="#C25450")

        self.root.after(0, update_state)

    # --------------------------------------------------------------------------
    # SISTEMA DE NOTIFICACIÓN ON-SCREEN DISPLAY (OSD)
    # --------------------------------------------------------------------------
    def show_osd(self, title: str, subtitle: str = "", icon: str = "🎮", color: str = "#38bdf8", duration_ms: int = 1800):
        """Muestra un banner flotante en pantalla (OSD) con el comando ejecutado."""
        try:
            # 1. Configurar y mostrar banner OSD en la ventana principal
            self.osd_frame.configure(border_color=color)
            self.osd_icon_label.configure(text=icon)
            self.osd_title_label.configure(text=title, text_color=color)
            self.osd_subtitle_label.configure(text=subtitle)

            self.osd_frame.place(relx=0.5, rely=0.30, anchor="center")
            self.osd_frame.lift()

            # 2. Configurar indicador OSD en Modo Mini si está activo
            if hasattr(self, "lbl_mini_osd"):
                self.lbl_mini_osd.configure(text=f"{icon} {title}", text_color=color)

            # 3. Actualizar barra de estado inferior
            self.status_label.configure(text=f"{icon} {title} — {subtitle}", text_color=color)

            # 4. Programar auto-ocultamiento
            if self.osd_timer:
                try:
                    self.root.after_cancel(self.osd_timer)
                except Exception:
                    pass
            self.osd_timer = self.root.after(duration_ms, self._hide_osd)

            # 5. Notificación OSD nativa en el escritorio CachyOS
            send_desktop_osd(f"{icon} {title}", subtitle)
        except Exception as e:
            print(f"[OSD] Error mostrando banner: {e}")

    def _hide_osd(self):
        """Oculta el banner flotante OSD."""
        try:
            self.osd_frame.place_forget()
        except Exception:
            pass
        if hasattr(self, "lbl_mini_osd"):
            self.lbl_mini_osd.configure(
                text="🎮 Modo Gimnasio Activo",
                text_color="#94a3b8"
            )

    # --------------------------------------------------------------------------
    # ACCIONES DEL JOYSTICK Y MANDOS INALÁMBRICOS
    # --------------------------------------------------------------------------
    def _handle_joystick_action(self, action: str):
        """Ejecuta la orden recibida desde el joystick inalámbrico o teclado con feedback visual OSD."""
        def run_action():
            p_idx = self.player.current_paragraph_index
            tot = self.document.total_paragraphs if self.document else 0

            if action == "PLAY_PAUSE":
                if self.player.is_playing:
                    self.show_osd("PAUSA", "Lectura pausada", icon="⏸️", color="#f59e0b")
                else:
                    self.show_osd("CONTINUAR / LECTURA", f"Párrafo {p_idx + 1} de {tot}", icon="▶️", color="#10b981")
                self.player.toggle_pause()

            elif action == "PREV_PARAGRAPH":
                prev_idx = max(0, p_idx - 1)
                self.show_osd("RETROCEDER PÁRRAFO", f"Párrafo {prev_idx + 1} de {tot}", icon="⏮️", color="#38bdf8")
                self.player.prev_paragraph()

            elif action == "NEXT_PARAGRAPH":
                next_idx = min(tot - 1, p_idx + 1) if tot > 0 else 0
                self.show_osd("AVANZAR PÁRRAFO", f"Párrafo {next_idx + 1} de {tot}", icon="⏭️", color="#38bdf8")
                self.player.next_paragraph()

            elif action == "PREV_LINE":
                self.show_osd("RETROCEDER (-5s)", "Rebobinando en el párrafo", icon="⏪", color="#818cf8")
                self.player.prev_line()

            elif action == "NEXT_LINE":
                self.show_osd("AVANZAR (+5s)", "Adelantando en el párrafo", icon="⏩", color="#818cf8")
                self.player.next_line()

            elif action == "VOL_UP":
                self.step_volume(5)
                self.show_osd(f"VOLUMEN: {self.player.volume}%", "Nivel de audio aumentado", icon="🔊", color="#a855f7")

            elif action == "VOL_DOWN":
                self.step_volume(-5)
                self.show_osd(f"VOLUMEN: {self.player.volume}%", "Nivel de audio reducido", icon="🔉", color="#a855f7")

            elif action == "SPEED_UP":
                self.step_speed(0.1)
                self.show_osd(f"VELOCIDAD: {self.player.speed:.2f}x", "Ritmo de lectura acelerado", icon="⚡", color="#06b6d4")

            elif action == "SPEED_DOWN":
                self.step_speed(-0.1)
                self.show_osd(f"VELOCIDAD: {self.player.speed:.2f}x", "Ritmo de lectura más pausado", icon="🐌", color="#06b6d4")

            elif action == "STOP":
                self.show_osd("DETENIDO", "Lectura finalizada", icon="⏹️", color="#ef4444")
                self.player.stop()

        self.root.after(0, run_action)

    def _on_joystick_connection_change(self, connected: bool, name: str):
        """Actualiza el badge superior cuando se conecta o desconecta el joystick."""
        def update_badge():
            if connected:
                self.badge_joystick.configure(
                    text=f"🎮 {name[:14]}",
                    fg_color="#065f46",
                    hover_color="#047857"
                )
                self.status_label.configure(
                    text=f"🎮 Mando '{name}' conectado. ¡Listo para entrenar!",
                    text_color="#10b981"
                )
                self.show_osd("JOYSTICK CONECTADO", name, icon="🎮", color="#10b981")
            else:
                self.badge_joystick.configure(
                    text="🎮 Joystick: Desconectado",
                    fg_color="#334155",
                    hover_color="#475569"
                )
                self.show_osd("JOYSTICK DESCONECTADO", "Buscando mando...", icon="🎮", color="#f59e0b")

        self.root.after(0, update_badge)

    # --------------------------------------------------------------------------
    # CONTROLES DE AJUSTES
    # --------------------------------------------------------------------------
    def _on_speed_slider(self, val: float):
        speed = round(float(val), 2)
        self.lbl_speed.configure(text=f"{speed:.2f}x")
        self.player.set_speed(speed)
        self.config["speed"] = speed
        save_config(self.config)

    def step_speed(self, delta: float):
        new_speed = max(0.5, min(2.5, round(self.player.speed + delta, 2)))
        self.scale_speed.set(new_speed)
        self._on_speed_slider(new_speed)

    def _on_volume_slider(self, val: float):
        vol = int(float(val))
        self.lbl_volume.configure(text=f"{vol}%")
        self.player.set_volume(vol)
        self.config["volume"] = vol
        save_config(self.config)

    def step_volume(self, delta: int):
        new_vol = max(0, min(130, self.player.volume + delta))
        self.scale_vol.set(new_vol)
        self._on_volume_slider(new_vol)

    def _on_voice_selected(self, val: str):
        self.player.voice_label = val
        self.config["voice"] = val
        save_config(self.config)
        # Si estaba reproduciendo, reiniciar con la nueva voz
        if self.player.is_playing:
            self.player.play(self.player.current_paragraph_index)

    def _on_sink_selected(self, val: str):
        sink_name = self.combo_sink.get()
        if sink_name in self.sinks_map:
            sink_id = self.sinks_map[sink_name]
            import subprocess
            subprocess.run(["wpctl", "set-default", sink_id])
            unmute_sink(sink_id)
            self.status_label.configure(text=f"Salida: {sink_name[:24]}...", text_color="#57A868")

    # --------------------------------------------------------------------------
    # MODAL DE BIBLIOTECA
    # --------------------------------------------------------------------------
    def open_library_modal(self):
        """
        Explorador y Biblioteca de Libros avanzado estilo CachyOS.
        Permite navegar libros recientes con progreso, explorar carpetas del sistema
        (Documentos, Descargas, etc.) y abrir el selector nativo de GNOME/CachyOS.
        """
        modal = ctk.CTkToplevel(self.root)
        modal.title("Explorador y Biblioteca de Libros — CachyOS")
        modal.geometry("820x570")
        modal.minsize(740, 500)
        modal.transient(self.root)
        modal.grab_set()

        # Recordar la carpeta activa para el explorador
        default_dir = os.path.expanduser("~/Descargas")
        if not os.path.exists(default_dir):
            default_dir = os.path.expanduser("~/Documentos")
        current_browse_dir = [default_dir]

        # 1. Cabecera superior con títulos y accesos directos
        header = ctk.CTkFrame(modal, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(14, 6))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")
        ctk.CTkLabel(
            title_box,
            text="🗂️ Explorador de Libros",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box,
            text="Integración con el escritorio CachyOS (GNOME / GTK4)",
            font=ctk.CTkFont(size=11),
            text_color="gray70"
        ).pack(anchor="w")

        # Botones de acción del sistema
        header_actions = ctk.CTkFrame(header, fg_color="transparent")
        header_actions.pack(side="right")

        def open_with_nautilus():
            dir_to_open = current_browse_dir[0] if os.path.exists(current_browse_dir[0]) else os.path.expanduser("~")
            subprocess.Popen(["xdg-open", dir_to_open])

        btn_nautilus = ctk.CTkButton(
            header_actions,
            text="📁 Abrir en Nautilus",
            width=135,
            height=32,
            fg_color="gray25",
            hover_color="gray35",
            command=open_with_nautilus
        )
        btn_nautilus.pack(side="right", padx=(8, 0))

        def open_native_chooser():
            path = open_cachyos_file_dialog(current_browse_dir[0])
            if path:
                modal.destroy()
                self.open_document_path(path)

        btn_native = ctk.CTkButton(
            header_actions,
            text="🗂️ Selector de CachyOS",
            width=165,
            height=32,
            fg_color="#0284c7",
            hover_color="#0369a1",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=open_native_chooser
        )
        btn_native.pack(side="right")

        # 2. Barra de Búsqueda reactiva
        search_frame = ctk.CTkFrame(modal, fg_color="transparent")
        search_frame.pack(fill="x", padx=18, pady=(4, 8))

        search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="🔍 Filtrar libros por nombre, archivo o palabra clave...",
            height=36,
            font=ctk.CTkFont(size=13)
        )
        search_entry.pack(fill="x")

        # 3. Pestañas: Recientes vs Explorador de Carpetas de CachyOS
        tabview = ctk.CTkTabview(modal)
        tabview.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        tab_recents = tabview.add("📚 Mis Libros Recientes")
        tab_browse = tabview.add("🔎 Explorar Carpetas del Sistema")

        # ======================================================================
        # PESTAÑA 1: LIBROS RECIENTES Y MARCADORES
        # ======================================================================
        scroll_recents = ctk.CTkScrollableFrame(tab_recents)
        scroll_recents.pack(fill="both", expand=True, padx=4, pady=4)

        def populate_recents(filter_text=""):
            for child in scroll_recents.winfo_children():
                child.destroy()

            books = self.bookmarks.get_recent_books(50)
            if filter_text:
                q = filter_text.strip().lower()
                books = [b for b in books if q in b.get("title", "").lower() or q in b.get("path", "").lower()]

            if not books:
                ctk.CTkLabel(
                    scroll_recents,
                    text="No se encontraron libros que coincidan con la búsqueda." if filter_text else "No hay libros recientes guardados.",
                    text_color="gray60",
                    font=ctk.CTkFont(size=13)
                ).pack(pady=40)
                return

            for b in books:
                card = ctk.CTkFrame(scroll_recents, corner_radius=8)
                card.pack(fill="x", pady=4, padx=2)

                path = b.get("path", "")
                title = b.get("title", os.path.basename(path) if path else "Sin título")
                curr_p = b.get("current_paragraph", 0) + 1
                tot_p = b.get("total_paragraphs", 1)
                percent = b.get("progress_percent", 0.0)

                # Badge de tipo de formato
                ext = os.path.splitext(path)[1].lower() if path else ""
                badge_colors = {
                    '.pdf': ('PDF', '#dc2626'),
                    '.epub': ('EPUB', '#9333ea'),
                    '.txt': ('TXT', '#2563eb'),
                    '.md': ('MD', '#059669')
                }
                badge_text, badge_color = badge_colors.get(ext, (ext[1:].upper() or "DOC", '#475569'))

                lbl_badge = ctk.CTkLabel(
                    card,
                    text=f" {badge_text} ",
                    fg_color=badge_color,
                    corner_radius=4,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color="#ffffff"
                )
                lbl_badge.pack(side="left", padx=(10, 8), pady=8)

                # Información y barra de progreso
                info = ctk.CTkFrame(card, fg_color="transparent")
                info.pack(side="left", fill="both", expand=True, padx=4, pady=6)

                ctk.CTkLabel(
                    info,
                    text=title[:55],
                    font=ctk.CTkFont(size=13, weight="bold"),
                    anchor="w"
                ).pack(fill="x")

                prog_frame = ctk.CTkFrame(info, fg_color="transparent")
                prog_frame.pack(fill="x", pady=(2, 0))

                pbar = ctk.CTkProgressBar(prog_frame, height=6, progress_color="#38bdf8")
                pbar.set(min(1.0, max(0.0, percent / 100.0)))
                pbar.pack(side="left", fill="x", expand=True, padx=(0, 10))

                ctk.CTkLabel(
                    prog_frame,
                    text=f"{percent}% (Párrafo {curr_p} de {tot_p})",
                    font=ctk.CTkFont(size=11),
                    text_color="gray70"
                ).pack(side="right")

                # Botones de Reanudar y Quitar
                btn_box = ctk.CTkFrame(card, fg_color="transparent")
                btn_box.pack(side="right", padx=10, pady=6)

                def do_resume(p=path):
                    modal.destroy()
                    self.open_document_path(p)

                btn_read = ctk.CTkButton(
                    btn_box,
                    text="Reanudar ▶",
                    width=95,
                    height=28,
                    fg_color="#0284c7",
                    hover_color="#0369a1",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    command=do_resume
                )
                btn_read.pack(side="left", padx=(0, 6))

                def do_remove(p=path):
                    self.bookmarks.remove_book(p)
                    populate_recents(search_entry.get())

                btn_del = ctk.CTkButton(
                    btn_box,
                    text="✕",
                    width=28,
                    height=28,
                    fg_color="gray30",
                    hover_color="#ef4444",
                    command=do_remove
                )
                btn_del.pack(side="left")

        # ======================================================================
        # PESTAÑA 2: EXPLORADOR DE CARPETAS DE CACHYOS
        # ======================================================================
        folder_bar = ctk.CTkFrame(tab_browse, fg_color="transparent")
        folder_bar.pack(fill="x", pady=(2, 6))

        lbl_folder_path = ctk.CTkLabel(
            folder_bar,
            text=f"📂 Carpeta: {default_dir}",
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        lbl_folder_path.pack(side="left", fill="x", expand=True)

        quick_btns = ctk.CTkFrame(folder_bar, fg_color="transparent")
        quick_btns.pack(side="right")

        scroll_files = ctk.CTkScrollableFrame(tab_browse)
        scroll_files.pack(fill="both", expand=True, padx=4, pady=4)

        def scan_folder_books(folder: str, max_depth: int = 1):
            valid_exts = {'.pdf', '.epub', '.txt', '.md'}
            found = []
            folder = os.path.abspath(folder)
            if not os.path.exists(folder):
                return found

            for root_dir, dirs, files in os.walk(folder):
                rel = os.path.relpath(root_dir, folder)
                depth = 0 if rel == '.' else len(rel.split(os.sep))
                if depth > max_depth:
                    dirs.clear()
                    continue
                # Ignorar carpetas ocultas
                dirs[:] = [d for d in dirs if not d.startswith('.')]

                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in valid_exts and not f.startswith('.'):
                        full_p = os.path.join(root_dir, f)
                        try:
                            st = os.stat(full_p)
                            found.append({
                                'filename': f,
                                'path': full_p,
                                'ext': ext,
                                'size': st.st_size,
                                'mtime': st.st_mtime,
                                'rel_dir': '' if rel == '.' else rel
                            })
                        except Exception:
                            pass
            return sorted(found, key=lambda x: x['mtime'], reverse=True)

        def populate_folder_files(folder: str, filter_text: str = ""):
            for child in scroll_files.winfo_children():
                child.destroy()

            current_browse_dir[0] = folder
            files = scan_folder_books(folder, max_depth=1)

            if filter_text:
                q = filter_text.strip().lower()
                files = [f for f in files if q in f['filename'].lower()]

            folder_display = os.path.basename(folder) or folder
            lbl_folder_path.configure(
                text=f"📂 {folder_display} ({len(files)} libros encontrados)"
            )

            if not files:
                ctk.CTkLabel(
                    scroll_files,
                    text="No se encontraron libros (.pdf, .epub, .txt, .md) en esta carpeta.",
                    text_color="gray60",
                    font=ctk.CTkFont(size=13)
                ).pack(pady=40)
                return

            for item in files:
                card = ctk.CTkFrame(scroll_files, corner_radius=8)
                card.pack(fill="x", pady=4, padx=2)

                ext = item['ext']
                badge_colors = {
                    '.pdf': ('PDF', '#dc2626'),
                    '.epub': ('EPUB', '#9333ea'),
                    '.txt': ('TXT', '#2563eb'),
                    '.md': ('MD', '#059669')
                }
                badge_text, badge_color = badge_colors.get(ext, (ext[1:].upper() or "DOC", '#475569'))

                lbl_badge = ctk.CTkLabel(
                    card,
                    text=f" {badge_text} ",
                    fg_color=badge_color,
                    corner_radius=4,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color="#ffffff"
                )
                lbl_badge.pack(side="left", padx=(10, 8), pady=8)

                info = ctk.CTkFrame(card, fg_color="transparent")
                info.pack(side="left", fill="both", expand=True, padx=4, pady=6)

                ctk.CTkLabel(
                    info,
                    text=item['filename'][:55],
                    font=ctk.CTkFont(size=13, weight="bold"),
                    anchor="w"
                ).pack(fill="x")

                dt = datetime.fromtimestamp(item['mtime']).strftime('%d/%m/%Y %H:%M')
                sub_text = f"Tamaño: {format_filesize(item['size'])} • Modificado: {dt}"
                if item['rel_dir']:
                    sub_text += f" • Subcarpeta: {item['rel_dir']}"

                ctk.CTkLabel(
                    info,
                    text=sub_text,
                    font=ctk.CTkFont(size=11),
                    text_color="gray70",
                    anchor="w"
                ).pack(fill="x")

                def do_open(p=item['path']):
                    modal.destroy()
                    self.open_document_path(p)

                btn_open_book = ctk.CTkButton(
                    card,
                    text="📖 Abrir y Leer",
                    width=110,
                    height=28,
                    fg_color="#0284c7",
                    hover_color="#0369a1",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    command=do_open
                )
                btn_open_book.pack(side="right", padx=10, pady=6)

        def switch_folder(target_dir):
            if os.path.exists(target_dir):
                populate_folder_files(target_dir, search_entry.get())

        def choose_custom_folder():
            f = open_cachyos_file_dialog(current_browse_dir[0], directory_only=True)
            if f and os.path.isdir(f):
                switch_folder(f)

        btn_f_desc = ctk.CTkButton(quick_btns, text="📥 Descargas", width=90, height=26, fg_color="gray25", hover_color="gray35", command=lambda: switch_folder(os.path.expanduser("~/Descargas")))
        btn_f_desc.pack(side="left", padx=2)

        btn_f_docs = ctk.CTkButton(quick_btns, text="📄 Documentos", width=95, height=26, fg_color="gray25", hover_color="gray35", command=lambda: switch_folder(os.path.expanduser("~/Documentos")))
        btn_f_docs.pack(side="left", padx=2)

        btn_f_home = ctk.CTkButton(quick_btns, text="🏠 Personal", width=80, height=26, fg_color="gray25", hover_color="gray35", command=lambda: switch_folder(os.path.expanduser("~")))
        btn_f_home.pack(side="left", padx=2)

        btn_f_custom = ctk.CTkButton(quick_btns, text="📁 Elegir Carpeta...", width=115, height=26, fg_color="gray30", hover_color="gray40", command=choose_custom_folder)
        btn_f_custom.pack(side="left", padx=2)

        # Conectar buscador en tiempo real
        def on_search_type(event=None):
            q = search_entry.get()
            current_tab = tabview.get()
            if "Recientes" in current_tab:
                populate_recents(q)
            else:
                populate_folder_files(current_browse_dir[0], q)

        search_entry.bind("<KeyRelease>", on_search_type)

        # Cargar datos iniciales
        populate_recents()
        populate_folder_files(default_dir)

    # --------------------------------------------------------------------------
    # MODAL DE CONFIGURACIÓN Y PRUEBA DE JOYSTICK
    # --------------------------------------------------------------------------
    def open_joystick_modal(self):
        """Ventana de diagnóstico y remapeo de botones para cualquier mando inalámbrico."""
        modal = ctk.CTkToplevel(self.root)
        modal.title("Configuración de Joystick / Mando")
        modal.geometry("540x500")
        modal.transient(self.root)
        modal.grab_set()

        ctk.CTkLabel(
            modal,
            text="🎮 Probador y Configuración de Joystick",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(12, 4))

        dev_status = f"Dispositivo actual: {self.joystick.current_device_name}"
        lbl_dev = ctk.CTkLabel(
            modal,
            text=dev_status,
            text_color="#10b981" if self.joystick.is_connected else "#e2e8f0",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        lbl_dev.pack(pady=(0, 6))

        # Barra de re-escaneo
        scan_bar = ctk.CTkFrame(modal, fg_color="transparent")
        scan_bar.pack(fill="x", padx=16, pady=(0, 10))

        def refresh_devices():
            pads = self.joystick.list_available_gamepads()
            if pads:
                names = [f"{p[1]} ({p[0]})" for p in pads]
                lbl_dev.configure(
                    text=f"Detectado: {self.joystick.current_device_name}",
                    text_color="#10b981"
                )
                self.badge_joystick.configure(
                    text=f"🎮 {self.joystick.current_device_name[:14]}",
                    fg_color="#065f46"
                )
            else:
                lbl_dev.configure(text="No se detectó ningún mando conectado.", text_color="#C25450")

        btn_rescan = ctk.CTkButton(
            scan_bar,
            text="🔄 Re-escanear Mandos",
            width=160,
            command=refresh_devices,
            fg_color="gray30",
            hover_color="gray40"
        )
        btn_rescan.pack(side="top")

        # Cuadro de prueba en vivo
        test_box = ctk.CTkFrame(modal, corner_radius=8, fg_color="#1e293b")
        test_box.pack(fill="x", padx=16, pady=(0, 12), ipady=6)

        ctk.CTkLabel(test_box, text="Presiona cualquier botón o cruceta de tu mando para probarlo:", text_color="gray70", font=ctk.CTkFont(size=11)).pack(pady=(4, 2))
        lbl_last_btn = ctk.CTkLabel(test_box, text="[ Esperando pulsación... ]", font=ctk.CTkFont(size=14, weight="bold"), text_color="#10b981")
        lbl_last_btn.pack(pady=4)

        # Conectar callback temporal de prueba
        def on_raw(dev_name, ev_type, num, val):
            btn_names_map = {
                0: "A / Cruz", 1: "B / Círculo", 2: "X / Cuadrado", 3: "Y / Triángulo",
                4: "LB / L1", 5: "RB / R1", 6: "Back / Select", 7: "Start", 8: "Logo / Home"
            }
            if ev_type == "button" and val == 1:
                key_id = f"btn_{num}"
                mapped = self.joystick.action_map.get(key_id, "Sin asignar")
                b_name = btn_names_map.get(num, f"Botón {num}")
                lbl_last_btn.configure(text=f"🟢 {b_name} ({key_id}) ➜ Acción: {mapped}")
            elif ev_type == "axis" and abs(val) > 16000:
                direction = "neg" if val < 0 else "pos"
                axis_key = f"axis_{num}_{direction}"
                mapped = self.joystick.action_map.get(axis_key)
                if not mapped:
                    axis_name = "axis_x" if num in (0, 6) else ("axis_y" if num in (1, 7) else f"axis_{num}")
                    axis_key = f"{axis_name}_{direction}"
                    mapped = self.joystick.action_map.get(axis_key, "Sin asignar")

                axis_desc = {
                    "axis_6_neg": "D-Pad Izquierda", "axis_6_pos": "D-Pad Derecha",
                    "axis_7_neg": "D-Pad Arriba", "axis_7_pos": "D-Pad Abajo",
                    "axis_0_neg": "Stick Izq ⬅", "axis_0_pos": "Stick Izq ➡",
                    "axis_1_neg": "Stick Izq ⬆", "axis_1_pos": "Stick Izq ⬇",
                    "axis_2_pos": "Gatillo LT / L2", "axis_5_pos": "Gatillo RT / R2",
                }.get(f"axis_{num}_{direction}", axis_key)

                lbl_last_btn.configure(text=f"🎯 {axis_desc} ({axis_key}) ➜ Acción: {mapped}")

        self.joystick.on_raw_event = on_raw

        # Guía de controles recomendada
        guide_frame = ctk.CTkScrollableFrame(modal, width=500, height=200)
        guide_frame.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        guide_data = [
            ("A / Cruz / Start (Botón 0 / 7)", "Pausar y Reanudar la lectura"),
            ("D-Pad Izquierda o LB/L1 (Eje 6- / Botón 4)", "Retroceder un párrafo completo"),
            ("D-Pad Derecha o RB/R1 (Eje 6+ / Botón 5)", "Avanzar un párrafo completo"),
            ("X / Cuadrado o LT/L2 (Botón 2 / Eje 2+)", "Retroceder una línea / 5 segundos"),
            ("Y / Triángulo o RT/R2 (Botón 3 / Eje 5+)", "Avanzar una línea / 5 segundos"),
            ("D-Pad Arriba (Eje 7-)", "Subir volumen (+5%)"),
            ("D-Pad Abajo (Eje 7+)", "Bajar volumen (-5%)"),
            ("Back / Select (Botón 6)", "Reducir velocidad (-0.1x)"),
            ("B / Círculo (Botón 1)", "Detener lectura"),
        ]

        for key_desc, act_desc in guide_data:
            row = ctk.CTkFrame(guide_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=f"• {key_desc}:", font=ctk.CTkFont(size=12, weight="bold"), anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=act_desc, font=ctk.CTkFont(size=12), text_color="#38bdf8", anchor="w").pack(side="right")

        # Botón Restaurar valores por defecto
        btn_reset = ctk.CTkButton(
            modal,
            text="Restaurar Controles por Defecto",
            width=200,
            command=lambda: (self.joystick.action_map.update(DEFAULT_JOYSTICK_MAP), lbl_last_btn.configure(text="Controles restaurados"))
        )
        btn_reset.pack(pady=(0, 12))

        def on_modal_close():
            self.joystick.on_raw_event = None
            modal.destroy()

        modal.protocol("WM_DELETE_WINDOW", on_modal_close)

    # --------------------------------------------------------------------------
    # CIERRE DE LA APLICACIÓN
    # --------------------------------------------------------------------------
    def on_close(self):
        """Cierra la aplicación liberando mpv y el hilo del joystick."""
        self.player.stop()
        self.player.stop_monitor()
        self.joystick.stop()
        try:
            self.root.destroy()
        except Exception:
            pass
        os._exit(0)
