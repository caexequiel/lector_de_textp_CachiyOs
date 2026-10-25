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
import uuid
from typing import Optional
from datetime import datetime
from tkinter import filedialog
import customtkinter as ctk

try:
    import tkinterdnd2
    class DragDropCTk(ctk.CTk, tkinterdnd2.TkinterDnD.DnDWrapper):
        """Ventana principal CTk compatible con arrastrar y soltar archivos (Drag & Drop)."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = tkinterdnd2.TkinterDnD._require(self)
    DND_AVAILABLE = True
except Exception:
    class DragDropCTk(ctk.CTk):
        pass
    tkinterdnd2 = None
    DND_AVAILABLE = False

from .config import (
    VOICES,
    load_config,
    save_config,
    get_pipewire_sinks,
    unmute_sink,
    get_sink_volume_and_mute,
    DEFAULT_JOYSTICK_MAP,
    JOYSTICK_ACTIONS,
    JOYSTICK_INPUT_DEFINITIONS,
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


def open_in_file_manager(file_path: str):
    """Abre el explorador de archivos nativo (Nautilus) seleccionando el archivo especificado."""
    if not file_path:
        return
    abs_p = os.path.abspath(file_path)
    try:
        if os.path.exists(abs_p):
            if shutil.which("nautilus"):
                subprocess.Popen(["nautilus", "--select", abs_p])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(abs_p)])
        elif os.path.exists(os.path.dirname(abs_p)):
            subprocess.Popen(["xdg-open", os.path.dirname(abs_p)])
    except Exception as e:
        print(f"[FileManager] Error abriendo ubicación: {e}")




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

        # Estado de resaltado interactivo en tiempo real (LB / RB)
        self.is_highlighting_active = False
        self.highlight_start_para = 0
        self.highlight_start_char = 0
        self.highlight_start_tk_idx = None
        self.last_speech_pos = (0, 0)

        # Configuración de ventana
        self.root.title("Lector de Libros IA — Modo Entrenamiento")
        self.root.geometry("960x620")
        self.root.minsize(780, 500)
        self.root.resizable(True, True)
        self.root.attributes("-topmost", False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Configurar icono de la aplicación (alumno.png)
        icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "alumno.png")
        if not os.path.exists(icon_path):
            icon_path = "/home/exequiel/Descargas/Íconos/alumno.png"
        if os.path.exists(icon_path):
            try:
                import tkinter as tk
                self._app_icon = tk.PhotoImage(file=icon_path)
                self.root.iconphoto(True, self._app_icon)
            except Exception as e:
                print(f"[Icon] Error configurando icono: {e}")

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

        # Configurar Drag and Drop para arrastrar documentos (.pdf, .epub, .txt, .md)
        self._setup_drag_and_drop()

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
        self.root.bind("<h>", lambda e: self._handle_joystick_action("TOGGLE_HIGHLIGHT"))
        self.root.bind("<H>", lambda e: self._handle_joystick_action("TOGGLE_HIGHLIGHT"))
        self.root.bind("<BackSpace>", lambda e: self._handle_joystick_action("DELETE_LAST_HIGHLIGHT"))
        self.root.bind("<Control-z>", lambda e: self._handle_joystick_action("DELETE_LAST_HIGHLIGHT"))

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
                "1. Arrastra cualquier archivo PDF, EPUB, TXT o MD directamente a esta ventana para leerlo de inmediato.\n"
                "2. O haz clic en '📂 Abrir Libro' para elegir un documento con el explorador nativo.\n"
                "3. Conecta tu joystick o mando inalámbrico (Bluetooth o dongle USB).\n"
                "4. ¡Usa las teclas del joystick para pausar, retroceder párrafos o resaltar texto con total libertad!\n\n"
                "Controles del Joystick por defecto:\n"
                "• [A / Cruz / Start]: Pausar y Reanudar la lectura.\n"
                "• [LB / L1]: Resaltar texto en amarillo mientras lee (pulsar de nuevo para guardar).\n"
                "• [RB / R1]: Borrar o deshacer el último resaltado.\n"
                "• [D-Pad Izquierda / Stick Izq]: Retroceder un párrafo completo.\n"
                "• [D-Pad Derecha / Stick Der]: Avanzar un párrafo completo.\n"
                "• [LT / L2]: Retroceder 5 segundos en el párrafo.\n"
                "• [RT / R2]: Avanzar 5 segundos en el párrafo.\n"
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

        # Botón Resaltados
        self.btn_highlights_list = ctk.CTkButton(
            header_bar,
            text="🖍️ Resaltados (0)",
            width=130,
            command=self.open_highlights_modal,
            fg_color="#854d0e",
            hover_color="#a16207",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.btn_highlights_list.pack(side="right", padx=(6, 0))

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
            text="📥 Arrastra un libro aquí (.pdf, .epub, .txt, .md) o ábrelo",
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
        # Resaltado permanente guardado (amarillo clarito)
        self.text_box._textbox.tag_config(
            "permanent_highlight",
            background="#fef08a",
            foreground="#0f172a"
        )
        # Resaltado activo en curso mientras se lee con joystick LB (amarillo brillante)
        self.text_box._textbox.tag_config(
            "active_highlighting",
            background="#fde047",
            foreground="#000000",
            underline=True
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
    # SOPORTE DE ARRASTRAR Y SOLTAR DOCUMENTOS (DRAG & DROP)
    # --------------------------------------------------------------------------
    def _setup_drag_and_drop(self):
        """Configura el receptor de arrastrar y soltar (Drag and Drop) para documentos."""
        if not getattr(self.root, "TkdndVersion", None):
            return

        try:
            widgets = [
                self.root,
                self.main_frame,
                self.left_panel,
                self.text_box,
                self.text_box._textbox,
                self.mini_frame,
            ]
            for w in widgets:
                try:
                    w.drop_target_register(tkinterdnd2.DND_FILES)
                    w.dnd_bind("<<Drop>>", self._on_file_dropped)
                    w.dnd_bind("<<DropEnter>>", self._on_dnd_enter)
                    w.dnd_bind("<<DropLeave>>", self._on_dnd_leave)
                except Exception:
                    pass
        except Exception as e:
            print(f"[DnD] Error configurando drag-and-drop: {e}")

    def _on_dnd_enter(self, event):
        """Muestra una indicación visual cuando se arrastra un archivo sobre la aplicación."""
        if hasattr(self, "status_label"):
            self.status_label.configure(
                text="📥 ¡Suelta aquí tu libro (.pdf, .epub, .txt, .md) para leerlo de inmediato!",
                text_color="#38bdf8"
            )
        if hasattr(self, "lbl_mini_osd") and self.is_mini:
            self.lbl_mini_osd.configure(
                text="📥 Suelta para leer",
                text_color="#38bdf8"
            )

    def _on_dnd_leave(self, event):
        """Restaura el estado al salir del área de soltado."""
        if hasattr(self, "status_label"):
            if self.player.is_playing:
                self.status_label.configure(text="▶️ Leyendo...", text_color="#57A868")
            elif self.player.is_paused:
                self.status_label.configure(text="⏸️ En pausa", text_color="#E5B567")
            else:
                self.status_label.configure(text="Listo para entrenar", text_color="gray70")

    def _on_file_dropped(self, event):
        """Maneja el evento de soltar un documento arrastrado desde el explorador."""
        self._on_dnd_leave(event)
        raw_data = getattr(event, "data", "")
        if not raw_data:
            return

        import urllib.parse
        try:
            items = self.root.tk.splitlist(raw_data)
        except Exception:
            items = [raw_data]

        valid_exts = {".pdf", ".epub", ".txt", ".md"}
        selected_file = None

        for item in items:
            clean_item = item.strip("{}").strip()
            if clean_item.startswith("file://"):
                clean_item = urllib.parse.unquote(urllib.parse.urlparse(clean_item).path)
            clean_item = os.path.abspath(clean_item)

            if os.path.isfile(clean_item):
                ext = os.path.splitext(clean_item)[1].lower()
                if ext in valid_exts:
                    selected_file = clean_item
                    break

        if not selected_file:
            self.show_osd("FORMATO NO VÁLIDO", "Arrastra archivos PDF, EPUB, TXT o MD", icon="⚠️", color="#f59e0b")
            return

        # 1. Cargar el documento
        self.open_document_path(selected_file)

        # 2. Iniciar la reproducción automáticamente desde el párrafo activo
        if self.document and self.document.total_paragraphs > 0:
            start_p = self.player.current_paragraph_index
            self.player.play(start_p)
            doc_title = self.document.title or os.path.basename(selected_file)
            self.show_osd("DOCUMENTO CARGADO", f"Leyendo: {doc_title[:32]}...", icon="📖", color="#10b981")

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

    @property
    def current_file(self) -> Optional[str]:
        """Devuelve la ruta absoluta del documento abierto actualmente."""
        if self.document and self.document.file_path:
            return self.document.file_path
        return None

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
        self.is_highlighting_active = False
        self.highlight_start_tk_idx = None
        self._highlight_paragraph(0)
        self._refresh_permanent_highlights()

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
            # Mantener los resaltados en amarillo encima del fondo del párrafo
            tb.tag_raise("permanent_highlight")
            tb.tag_raise("active_highlighting")

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
            if ranges:
                total_len = len(self.document.get_paragraph(para_idx))
                curr_chars = int(total_len * (percent / 100.0)) if percent > 0 else 0
                self.last_speech_pos = (para_idx, curr_chars)

                if curr_chars > 0:
                    start_p = ranges[0]
                    prog_end = f"{start_p} + {curr_chars} chars"
                    tb.tag_remove("read_progress", start_p, ranges[1])
                    tb.tag_add("read_progress", start_p, prog_end)

                    # Si el usuario activó pintar con joystick (LB), extender el trazo en amarillo
                    if self.is_highlighting_active and self.highlight_start_tk_idx:
                        tb.tag_remove("active_highlighting", "1.0", "end")
                        tb.tag_add("active_highlighting", self.highlight_start_tk_idx, prog_end)
                        tb.tag_raise("permanent_highlight")
                        tb.tag_raise("active_highlighting")

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

            elif action == "TOGGLE_HIGHLIGHT":
                self.toggle_highlight()

            elif action == "DELETE_LAST_HIGHLIGHT":
                self.delete_last_highlight()

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
    # GESTOR DE RESALTADOS (LB / RB / AMARILLO CLARITO)
    # --------------------------------------------------------------------------
    def _update_highlights_badge(self):
        """Actualiza el contador del botón de resaltados en la barra superior."""
        if not hasattr(self, "btn_highlights_list"):
            return
        count = len(self.bookmarks.get_highlights(self.current_file)) if self.current_file else 0
        self.btn_highlights_list.configure(text=f"🖍️ Resaltados ({count})")

    def toggle_highlight(self):
        """
        Alterna el resaltado interactivo en tiempo real con el botón LB / L1 del mando.
        - Primera pulsación: Inicia la pintura del texto en amarillo a medida que la voz avanza.
        - Segunda pulsación: Detiene la pintura, almacena el fragmento y lo muestra en amarillo clarito.
        """
        if not self.document:
            self.show_osd("SIN DOCUMENTO", "Abre un libro antes de resaltar texto", icon="⚠️", color="#f59e0b")
            return

        tb = self.text_box._textbox
        curr_p = self.player.current_paragraph_index

        if not self.is_highlighting_active:
            # INICIAR RESALTADO
            self.is_highlighting_active = True
            last_p, last_c = self.last_speech_pos
            start_char = last_c if last_p == curr_p else 0

            self.highlight_start_para = curr_p
            self.highlight_start_char = start_char

            ranges = tb.tag_ranges(f"para_{curr_p}")
            if ranges:
                self.highlight_start_tk_idx = f"{ranges[0]} + {start_char} chars"
            else:
                self.highlight_start_tk_idx = "1.0"

            tb.tag_remove("active_highlighting", "1.0", "end")
            tb.tag_add("active_highlighting", self.highlight_start_tk_idx, f"{self.highlight_start_tk_idx} + 1 chars")
            tb.tag_raise("permanent_highlight")
            tb.tag_raise("active_highlighting")

            self.show_osd("🖍️ RESALTANDO TEXTO", "Leyendo y pintando... (Pulsa LB para finalizar)", icon="🖍️", color="#eab308", duration_ms=2500)
        else:
            # FINALIZAR Y GUARDAR RESALTADO
            self.is_highlighting_active = False
            last_p, last_c = self.last_speech_pos

            if last_p == curr_p:
                end_char = last_c
            else:
                end_char = len(self.document.get_paragraph(curr_p)) if self.document else 0

            ranges = tb.tag_ranges(f"para_{curr_p}")
            if ranges:
                end_tk_idx = f"{ranges[0]} + {end_char} chars"
            else:
                end_tk_idx = f"{self.highlight_start_tk_idx} + 1 chars"

            if self.highlight_start_tk_idx and tb.compare(self.highlight_start_tk_idx, ">=", end_tk_idx):
                end_tk_idx = f"{self.highlight_start_tk_idx} + 1 chars"

            raw_text = tb.get(self.highlight_start_tk_idx, end_tk_idx).strip() if self.highlight_start_tk_idx else ""
            tb.tag_remove("active_highlighting", "1.0", "end")
            self.highlight_start_tk_idx = None

            if not raw_text:
                self.show_osd("RESALTADO VACÍO", "No se capturó texto para resaltar", icon="⚠️", color="#f59e0b")
                return

            highlight_record = {
                "id": uuid.uuid4().hex[:8],
                "start_para": self.highlight_start_para,
                "start_char": self.highlight_start_char,
                "end_para": curr_p,
                "end_char": end_char,
                "text": raw_text,
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M")
            }
            self.bookmarks.add_highlight(self.current_file, highlight_record)
            self._refresh_permanent_highlights()

            preview = (raw_text[:35] + "...") if len(raw_text) > 35 else raw_text
            self.show_osd("✅ RESALTADO GUARDADO", f'"{preview}"', icon="🖍️", color="#eab308")

    def delete_last_highlight(self):
        """
        Elimina el último fragmento resaltado (deshacer con botón RB del mando).
        Si se estaba pintando activamente en ese instante, cancela la acción sin guardarla.
        """
        if self.is_highlighting_active:
            self.is_highlighting_active = False
            self.highlight_start_tk_idx = None
            self.text_box._textbox.tag_remove("active_highlighting", "1.0", "end")
            self.show_osd("RESALTADO CANCELADO", "Pintura cancelada sin guardar (RB)", icon="↩️", color="#f59e0b")
            return

        if not self.current_file:
            return

        removed = self.bookmarks.remove_last_highlight(self.current_file)
        if removed:
            self._refresh_permanent_highlights()
            text_prev = removed.get("text", "")[:35]
            if len(removed.get("text", "")) > 35:
                text_prev += "..."
            self.show_osd("🗑️ RESALTADO BORRADO", f'"{text_prev}" eliminado (RB)', icon="↩️", color="#ef4444")
        else:
            self.show_osd("SIN RESALTADOS", "No hay fragmentos resaltados para borrar", icon="ℹ️", color="#94a3b8")

    def _refresh_permanent_highlights(self):
        """Aplica los resaltados guardados en amarillo clarito sobre el texto."""
        if not self.document or not self.current_file:
            self._update_highlights_badge()
            return

        tb = self.text_box._textbox
        tb.tag_remove("permanent_highlight", "1.0", "end")

        highlights = self.bookmarks.get_highlights(self.current_file)
        for h in highlights:
            s_para = h.get("start_para", 0)
            s_char = h.get("start_char", 0)
            e_para = h.get("end_para", s_para)
            e_char = h.get("end_char", s_char)

            ranges_s = tb.tag_ranges(f"para_{s_para}")
            ranges_e = tb.tag_ranges(f"para_{e_para}")

            applied = False
            if ranges_s and ranges_e:
                try:
                    tk_s = f"{ranges_s[0]} + {s_char} chars"
                    tk_e = f"{ranges_e[0]} + {e_char} chars"
                    if tb.compare(tk_s, "<", tk_e):
                        tb.tag_add("permanent_highlight", tk_s, tk_e)
                        applied = True
                except Exception:
                    applied = False

            if not applied and h.get("text"):
                fragment = h["text"].strip()
                if fragment:
                    pos = tb.search(fragment[:40], "1.0", "end")
                    if pos:
                        tb.tag_add("permanent_highlight", pos, f"{pos} + {len(fragment)} chars")

        tb.tag_raise("permanent_highlight")
        tb.tag_raise("active_highlighting")
        self._update_highlights_badge()

    def open_highlights_modal(self):
        """
        Abre el panel de gestión de citas y fragmentos resaltados del documento activo.
        Permite revisar, saltar al texto, copiar al portapapeles y exportar a Markdown (.md).
        """
        modal = ctk.CTkToplevel(self.root)
        modal.title("🖍️ Resaltados y Citas del Libro — Lector IA")
        modal.geometry("820x600")
        modal.minsize(740, 500)
        modal.transient(self.root)
        modal.grab_set()

        header = ctk.CTkFrame(modal, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(14, 6))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")

        ctk.CTkLabel(
            title_box,
            text="🖍️ Citas y Fragmentos Resaltados",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w")

        book_name = os.path.basename(self.current_file) if self.current_file else "Ningún documento abierto"
        ctk.CTkLabel(
            title_box,
            text=f"Libro: {book_name}",
            font=ctk.CTkFont(size=11),
            text_color="gray70"
        ).pack(anchor="w")

        header_actions = ctk.CTkFrame(header, fg_color="transparent")
        header_actions.pack(side="right")

        scroll_cards = ctk.CTkScrollableFrame(modal)
        scroll_cards.pack(fill="both", expand=True, padx=18, pady=(8, 12))

        def render_highlights():
            for child in scroll_cards.winfo_children():
                child.destroy()

            if not self.current_file:
                ctk.CTkLabel(
                    scroll_cards,
                    text="No hay ningún documento abierto.\nAbre un libro para ver o crear resaltados.",
                    text_color="gray60",
                    font=ctk.CTkFont(size=13)
                ).pack(pady=50)
                return

            highlights = self.bookmarks.get_highlights(self.current_file)
            if not highlights:
                info_msg = (
                    "No hay fragmentos resaltados en este documento todavía.\n\n"
                    "💡 Cómo resaltar con el mando GameSir mientras escuchas:\n"
                    "• Pulsa LB (Bumper Izquierdo) para empezar a pintar en amarillo mientras lee.\n"
                    "• Pulsa LB de nuevo para terminar el resaltado y guardarlo.\n"
                    "• Pulsa RB (Bumper Derecho) para deshacer o borrar el último resaltado.\n\n"
                    "También puedes pulsar la tecla 'H' en tu teclado para resaltar."
                )
                ctk.CTkLabel(
                    scroll_cards,
                    text=info_msg,
                    text_color="gray60",
                    justify="left",
                    font=ctk.CTkFont(size=12)
                ).pack(pady=40, padx=20)
                return

            for idx, h in enumerate(reversed(highlights), 1):
                card = ctk.CTkFrame(scroll_cards, corner_radius=8, fg_color="#1e293b")
                card.pack(fill="x", pady=6, padx=2)

                top_bar = ctk.CTkFrame(card, fg_color="transparent")
                top_bar.pack(fill="x", padx=12, pady=(10, 4))

                p_num = h.get("start_para", 0) + 1
                created = h.get("created_at", "")
                h_id = h.get("id", "")

                lbl_tag = ctk.CTkLabel(
                    top_bar,
                    text=f" 🖍️ Cita #{len(highlights) - idx + 1} — Párrafo {p_num} ",
                    fg_color="#854d0e",
                    corner_radius=4,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    text_color="#fef08a"
                )
                lbl_tag.pack(side="left")

                if created:
                    ctk.CTkLabel(
                        top_bar,
                        text=f"📅 {created}",
                        font=ctk.CTkFont(size=11),
                        text_color="gray60"
                    ).pack(side="left", padx=(10, 0))

                # Acciones individuales
                btn_box = ctk.CTkFrame(top_bar, fg_color="transparent")
                btn_box.pack(side="right")

                def go_to_text(target_para=h.get("start_para", 0)):
                    modal.destroy()
                    self.player.play(target_para)
                    self._highlight_paragraph(target_para)

                btn_jump = ctk.CTkButton(
                    btn_box,
                    text="📖 Ir al Texto",
                    width=90,
                    height=26,
                    fg_color="#0284c7",
                    hover_color="#0369a1",
                    font=ctk.CTkFont(size=11, weight="bold"),
                    command=go_to_text
                )
                btn_jump.pack(side="left", padx=(0, 4))

                def copy_quote(txt=h.get("text", "")):
                    self.root.clipboard_clear()
                    self.root.clipboard_append(txt)
                    self.root.update()
                    self.show_osd("COPIADO", "Texto copiado al portapapeles", icon="📋", color="#10b981")

                btn_copy = ctk.CTkButton(
                    btn_box,
                    text="📋 Copiar",
                    width=75,
                    height=26,
                    fg_color="gray25",
                    hover_color="gray35",
                    font=ctk.CTkFont(size=11),
                    command=copy_quote
                )
                btn_copy.pack(side="left", padx=(0, 4))

                def delete_quote(target_id=h_id):
                    self.bookmarks.remove_highlight_by_id(self.current_file, target_id)
                    self._refresh_permanent_highlights()
                    render_highlights()
                    self.show_osd("RESALTADO BORRADO", "Fragmento eliminado", icon="🗑️", color="#ef4444")

                btn_del = ctk.CTkButton(
                    btn_box,
                    text="🗑️",
                    width=35,
                    height=26,
                    fg_color="gray25",
                    hover_color="#dc2626",
                    text_color="#f87171",
                    command=delete_quote
                )
                btn_del.pack(side="left")

                # Cuerpo del texto resaltado
                quote_box = ctk.CTkFrame(card, fg_color="#292524", corner_radius=6)
                quote_box.pack(fill="x", padx=12, pady=(4, 10))

                text_content = h.get("text", "").strip()
                ctk.CTkLabel(
                    quote_box,
                    text=f'"{text_content}"',
                    font=ctk.CTkFont(size=12, slant="italic"),
                    text_color="#fef08a",
                    justify="left",
                    wraplength=730
                ).pack(fill="x", padx=10, pady=8, anchor="w")

        def export_to_markdown():
            highlights = self.bookmarks.get_highlights(self.current_file) if self.current_file else []
            if not highlights:
                self.show_osd("SIN RESALTADOS", "No hay fragmentos para exportar", icon="ℹ️", color="#f59e0b")
                return

            clean_title = os.path.splitext(os.path.basename(self.current_file))[0]
            default_dir = os.path.expanduser("~/Documentos")
            os.makedirs(default_dir, exist_ok=True)

            out_path = filedialog.asksaveasfilename(
                parent=modal,
                title="Exportar Resaltados a Markdown",
                initialfile=f"{clean_title}_resaltados.md",
                initialdir=default_dir,
                defaultextension=".md",
                filetypes=[("Markdown (*.md)", "*.md"), ("Todos los archivos", "*.*")]
            )
            if not out_path:
                return

            lines = [
                f"# Resaltados y Notas: {clean_title}",
                f"- **Archivo fuente:** `{self.current_file}`",
                f"- **Fecha de exportación:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
                f"- **Total de citas:** {len(highlights)}",
                "",
                "---",
                ""
            ]
            for idx, h in enumerate(highlights, 1):
                p_num = h.get("start_para", 0) + 1
                created = h.get("created_at", "Sin fecha")
                text = h.get("text", "").replace("\n", " ").strip()
                lines.append(f"### {idx}. Párrafo {p_num} — *{created}*")
                lines.append(f"> ❝ {text} ❞")
                lines.append("")
                lines.append("---")
                lines.append("")

            try:
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                self.show_osd("EXPORTADO A MARKDOWN", f"Guardado en {os.path.basename(out_path)}", icon="📄", color="#10b981")
            except Exception as e:
                self.show_osd("ERROR EXPORTANDO", str(e)[:30], icon="⚠️", color="#ef4444")

        btn_export = ctk.CTkButton(
            header_actions,
            text="📤 Exportar a Markdown (.md)",
            width=190,
            height=32,
            fg_color="#0284c7",
            hover_color="#0369a1",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=export_to_markdown
        )
        btn_export.pack(side="right")

        def clear_all_highlights():
            if not self.current_file or not self.bookmarks.get_highlights(self.current_file):
                return
            if self.current_file in self.bookmarks.library:
                self.bookmarks.library[self.current_file]["highlights"] = []
                self.bookmarks.save()
            self._refresh_permanent_highlights()
            render_highlights()
            self.show_osd("RESALTADOS BORRADOS", "Se eliminaron todas las citas del libro", icon="🗑️", color="#ef4444")

        btn_clear_all = ctk.CTkButton(
            header_actions,
            text="🗑️ Borrar Todos",
            width=120,
            height=32,
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            font=ctk.CTkFont(size=11),
            command=clear_all_highlights
        )
        btn_clear_all.pack(side="right", padx=(0, 8))

        render_highlights()

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
        modal.geometry("860x580")
        modal.minsize(780, 520)
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
        # PESTAÑA 1: LIBROS RECIENTES Y MARCADORES (CON GESTIÓN Y UBICACIÓN)
        # ======================================================================
        # Barra de herramientas de gestión de la biblioteca
        recents_toolbar = ctk.CTkFrame(tab_recents, fg_color="transparent")
        recents_toolbar.pack(fill="x", padx=4, pady=(2, 6))

        lbl_lib_count = ctk.CTkLabel(
            recents_toolbar,
            text="📚 Cargando...",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8",
            anchor="w"
        )
        lbl_lib_count.pack(side="left")

        lib_actions = ctk.CTkFrame(recents_toolbar, fg_color="transparent")
        lib_actions.pack(side="right")

        def do_cleanup_missing():
            removed = self.bookmarks.cleanup_missing_books()
            populate_recents(search_entry.get())
            if removed > 0:
                self.show_osd("BIBLIOTECA DEPURADA", f"{removed} libros inexistentes eliminados", icon="🧹", color="#38bdf8")
            else:
                self.show_osd("BIBLIOTECA AL DÍA", "Todos los libros existen en disco", icon="✅", color="#10b981")

        btn_cleanup = ctk.CTkButton(
            lib_actions,
            text="🧹 Limpiar Inexistentes",
            width=150,
            height=28,
            fg_color="gray25",
            hover_color="gray35",
            font=ctk.CTkFont(size=11),
            command=do_cleanup_missing
        )
        btn_cleanup.pack(side="left", padx=(0, 6))

        def do_clear_all():
            if not self.bookmarks.library:
                return
            self.bookmarks.clear_library()
            populate_recents()
            self.show_osd("BIBLIOTECA VACIADA", "Todos los marcadores fueron eliminados", icon="🗑️", color="#ef4444")

        btn_clear = ctk.CTkButton(
            lib_actions,
            text="🗑️ Vaciar Todo",
            width=100,
            height=28,
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            font=ctk.CTkFont(size=11),
            command=do_clear_all
        )
        btn_clear.pack(side="left")

        scroll_recents = ctk.CTkScrollableFrame(tab_recents)
        scroll_recents.pack(fill="both", expand=True, padx=4, pady=4)

        def populate_recents(filter_text=""):
            for child in scroll_recents.winfo_children():
                child.destroy()

            books = self.bookmarks.get_recent_books(50)
            if filter_text:
                q = filter_text.strip().lower()
                books = [b for b in books if q in b.get("title", "").lower() or q in b.get("path", "").lower()]

            lbl_lib_count.configure(text=f"📚 {len(books)} libro(s) en tu biblioteca")

            if not books:
                ctk.CTkLabel(
                    scroll_recents,
                    text="No se encontraron libros que coincidan con la búsqueda." if filter_text else "No hay libros recientes guardados en la biblioteca.",
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
                file_exists = os.path.exists(path) if path else False

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

                # Información central
                info = ctk.CTkFrame(card, fg_color="transparent")
                info.pack(side="left", fill="both", expand=True, padx=4, pady=6)

                ctk.CTkLabel(
                    info,
                    text=title[:52],
                    font=ctk.CTkFont(size=13, weight="bold"),
                    anchor="w"
                ).pack(fill="x")

                # Ubicación y estado del archivo
                details_frame = ctk.CTkFrame(info, fg_color="transparent")
                details_frame.pack(fill="x", pady=(1, 2))

                if file_exists:
                    folder_path = os.path.dirname(path)
                    ctk.CTkLabel(
                        details_frame,
                        text=f"📁 {folder_path[:60]}",
                        font=ctk.CTkFont(size=11),
                        text_color="gray70",
                        anchor="w"
                    ).pack(side="left")
                else:
                    ctk.CTkLabel(
                        details_frame,
                        text="⚠️ Archivo no encontrado en disco",
                        font=ctk.CTkFont(size=11),
                        text_color="#ef4444",
                        anchor="w"
                    ).pack(side="left")

                # Progreso
                prog_frame = ctk.CTkFrame(info, fg_color="transparent")
                prog_frame.pack(fill="x", pady=(1, 0))

                pbar = ctk.CTkProgressBar(prog_frame, height=6, progress_color="#38bdf8")
                pbar.set(min(1.0, max(0.0, percent / 100.0)))
                pbar.pack(side="left", fill="x", expand=True, padx=(0, 10))

                ctk.CTkLabel(
                    prog_frame,
                    text=f"{percent}% (Párrafo {curr_p} de {tot_p})",
                    font=ctk.CTkFont(size=11),
                    text_color="gray70"
                ).pack(side="right")

                # Botonera de acciones (Reanudar, Ubicación en Nautilus, Quitar de biblioteca)
                btn_box = ctk.CTkFrame(card, fg_color="transparent")
                btn_box.pack(side="right", padx=10, pady=6)

                def do_resume(p=path):
                    modal.destroy()
                    self.open_document_path(p)

                btn_read = ctk.CTkButton(
                    btn_box,
                    text="Reanudar ▶",
                    width=90,
                    height=28,
                    fg_color="#0284c7" if file_exists else "gray30",
                    state="normal" if file_exists else "disabled",
                    hover_color="#0369a1",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    command=do_resume
                )
                btn_read.pack(side="left", padx=(0, 4))

                btn_locate = ctk.CTkButton(
                    btn_box,
                    text="📁 Carpeta",
                    width=80,
                    height=28,
                    fg_color="gray25",
                    hover_color="gray35",
                    font=ctk.CTkFont(size=11),
                    command=lambda p=path: open_in_file_manager(p)
                )
                btn_locate.pack(side="left", padx=(0, 4))

                def do_remove(p=path, t=title):
                    self.bookmarks.remove_book(p)
                    populate_recents(search_entry.get())
                    self.show_osd("LIBRO ELIMINADO", t[:35], icon="🗑️", color="#ef4444")

                btn_del = ctk.CTkButton(
                    btn_box,
                    text="🗑️ Quitar",
                    width=75,
                    height=28,
                    fg_color="gray25",
                    hover_color="#dc2626",
                    text_color="#f87171",
                    font=ctk.CTkFont(size=11),
                    command=lambda p=path, t=title: do_remove(p, t)
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
        """
        Ventana de personalización y remapeo interactivo de controles para cualquier mando o joystick.
        Permite asignar libremente cualquier botón, cruceta o gatillo a subir volumen, pausa, saltos, etc.
        """
        modal = ctk.CTkToplevel(self.root)
        modal.title("Personalización de Controles — GameSir / Joystick")
        modal.geometry("740x650")
        modal.minsize(680, 560)
        modal.transient(self.root)
        modal.grab_set()

        # Cabecera
        header = ctk.CTkFrame(modal, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(12, 6))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")

        ctk.CTkLabel(
            title_box,
            text="🎮 Configurar Controles de Joystick / Mando",
            font=ctk.CTkFont(size=18, weight="bold")
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box,
            text="Personaliza cualquier tecla para volumen, pausa, navegación de párrafos y velocidad.",
            font=ctk.CTkFont(size=11),
            text_color="gray70"
        ).pack(anchor="w")

        # Barra de estado del dispositivo y re-escaneo
        dev_bar = ctk.CTkFrame(modal, fg_color="transparent")
        dev_bar.pack(fill="x", padx=18, pady=(2, 6))

        dev_status = f"Dispositivo detectado: {self.joystick.current_device_name}"
        lbl_dev = ctk.CTkLabel(
            dev_bar,
            text=dev_status,
            text_color="#10b981" if self.joystick.is_connected else "#e2e8f0",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        )
        lbl_dev.pack(side="left")

        def refresh_devices():
            pads = self.joystick.list_available_gamepads()
            if pads:
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
            dev_bar,
            text="🔄 Re-escanear",
            width=120,
            height=28,
            command=refresh_devices,
            fg_color="gray25",
            hover_color="gray35",
            font=ctk.CTkFont(size=11)
        )
        btn_rescan.pack(side="right")

        # Mensaje de estado de guardado
        lbl_feedback = ctk.CTkLabel(
            modal,
            text="💡 Elige la acción deseada para cada tecla. Los cambios se guardan y aplican al instante.",
            font=ctk.CTkFont(size=11, slant="italic"),
            text_color="#38bdf8"
        )
        lbl_feedback.pack(padx=18, pady=(0, 6), anchor="w")

        # Diccionarios de conversión para la UI
        action_display_list = list(JOYSTICK_ACTIONS.values())
        action_name_to_key = {v: k for k, v in JOYSTICK_ACTIONS.items()}
        dropdown_widgets = {}

        # Pestañas: Asignación Visual vs Probador en Vivo
        tabview = ctk.CTkTabview(modal)
        tabview.pack(fill="both", expand=True, padx=18, pady=(0, 10))

        tab_mapping = tabview.add("🎛️ Asignación de Controles")
        tab_tester = tabview.add("🎯 Probador y Mapeo Rápido en Vivo")

        # ======================================================================
        # PESTAÑA 1: ASIGNACIÓN DE CONTROLES (TABLA VISUAL)
        # ======================================================================
        scroll_map = ctk.CTkScrollableFrame(tab_mapping)
        scroll_map.pack(fill="both", expand=True, padx=4, pady=4)

        def on_mapping_changed(choice, key_id, input_label):
            action_key = action_name_to_key.get(choice, "NONE")
            if action_key == "NONE":
                if key_id in self.joystick.action_map:
                    del self.joystick.action_map[key_id]
            else:
                self.joystick.action_map[key_id] = action_key

            # Persistir en la configuración
            self.config["joystick_map"] = dict(self.joystick.action_map)
            save_config(self.config)

            lbl_feedback.configure(
                text=f"✅ Guardado: {input_label} ➔ {choice}",
                text_color="#10b981"
            )
            self.show_osd("CONTROL GUARDADO", f"{input_label} ➔ {choice}", icon="🎮", color="#10b981")

        for key_id, input_label, desc in JOYSTICK_INPUT_DEFINITIONS:
            row = ctk.CTkFrame(scroll_map, corner_radius=6)
            row.pack(fill="x", pady=3, padx=2)

            info_box = ctk.CTkFrame(row, fg_color="transparent")
            info_box.pack(side="left", fill="both", expand=True, padx=10, pady=6)

            ctk.CTkLabel(
                info_box,
                text=input_label,
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w"
            ).pack(fill="x")

            ctk.CTkLabel(
                info_box,
                text=f"{desc}  ({key_id})",
                font=ctk.CTkFont(size=10),
                text_color="gray70",
                anchor="w"
            ).pack(fill="x")

            # Determinar acción actual
            current_act_key = self.joystick.action_map.get(key_id, "NONE")
            current_disp_name = JOYSTICK_ACTIONS.get(current_act_key, "❌ Desactivado / Sin Asignar")

            opt_menu = ctk.CTkOptionMenu(
                row,
                values=action_display_list,
                width=250,
                height=28,
                command=lambda c, k=key_id, l=input_label: on_mapping_changed(c, k, l)
            )
            opt_menu.set(current_disp_name)
            opt_menu.pack(side="right", padx=10, pady=6)
            dropdown_widgets[key_id] = opt_menu

        # ======================================================================
        # PESTAÑA 2: DETECCIÓN Y MAPEO RÁPIDO EN VIVO
        # ======================================================================
        ctk.CTkLabel(
            tab_tester,
            text="Presiona cualquier botón o mueve la cruceta de tu joystick para detectarlo automáticamente:",
            font=ctk.CTkFont(size=12),
            text_color="gray80"
        ).pack(pady=(8, 8))

        live_card = ctk.CTkFrame(tab_tester, corner_radius=10, fg_color="#1e293b")
        live_card.pack(fill="x", padx=8, pady=(0, 10), ipady=8)

        lbl_detected_input = ctk.CTkLabel(
            live_card,
            text="[ Esperando pulsación en el mando... ]",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#38bdf8"
        )
        lbl_detected_input.pack(pady=(6, 4))

        quick_assign_frame = ctk.CTkFrame(live_card, fg_color="transparent")
        quick_assign_frame.pack(fill="x", padx=16, pady=(4, 6))

        ctk.CTkLabel(
            quick_assign_frame,
            text="Asignar acción a esta tecla:",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="left", padx=(0, 8))

        last_detected_info = [None, None]  # [key_id, display_label]

        def on_quick_action_selected(choice):
            if not last_detected_info[0]:
                return
            key_id, input_label = last_detected_info
            on_mapping_changed(choice, key_id, input_label)

            # Sincronizar el dropdown de la Pestaña 1
            if key_id in dropdown_widgets:
                dropdown_widgets[key_id].set(choice)

        opt_live_action = ctk.CTkOptionMenu(
            quick_assign_frame,
            values=action_display_list,
            width=260,
            height=30,
            command=on_quick_action_selected
        )
        opt_live_action.set("Selecciona una acción...")
        opt_live_action.configure(state="disabled")
        opt_live_action.pack(side="left")

        # Registro de eventos sin procesar (para diagnóstico)
        ctk.CTkLabel(
            tab_tester,
            text="Historial de eventos del mando en tiempo real:",
            font=ctk.CTkFont(size=11),
            text_color="gray70"
        ).pack(anchor="w", padx=8, pady=(6, 2))

        txt_log = ctk.CTkTextbox(tab_tester, height=130, font=ctk.CTkFont(family="monospace", size=11))
        txt_log.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        txt_log.insert("end", "Inicia la pulsación de teclas para verificar la lectura del kernel...\n")
        txt_log.configure(state="disabled")

        def on_raw_joystick_event(dev_name, ev_type, num, val):
            btn_names = {
                0: "Botón A / Cruz", 1: "Botón B / Círculo", 2: "Botón X / Cuadrado", 3: "Botón Y / Triángulo",
                4: "LB / L1", 5: "RB / R1", 6: "Back / Select", 7: "Start", 8: "Logo / Home",
                9: "L3 (Stick Izq)", 10: "R3 (Stick Der)"
            }

            key_id = None
            display_name = None

            if ev_type == "button" and val == 1:
                key_id = f"btn_{num}"
                display_name = btn_names.get(num, f"Botón {num}")
            elif ev_type == "axis" and abs(val) > 16000:
                direction = "neg" if val < 0 else "pos"
                key_id = f"axis_{num}_{direction}"
                axis_names = {
                    "axis_6_neg": "D-Pad Izquierda ⬅", "axis_6_pos": "D-Pad Derecha ➡",
                    "axis_7_neg": "D-Pad Arriba ⬆", "axis_7_pos": "D-Pad Abajo ⬇",
                    "axis_0_neg": "Stick Izq ⬅", "axis_0_pos": "Stick Izq ➡",
                    "axis_1_neg": "Stick Izq ⬆", "axis_1_pos": "Stick Izq ⬇",
                    "axis_2_pos": "Gatillo LT / L2", "axis_5_pos": "Gatillo RT / R2",
                }
                display_name = axis_names.get(key_id, f"Eje {num} ({direction})")

            if key_id and display_name:
                last_detected_info[0] = key_id
                last_detected_info[1] = display_name

                curr_act_key = self.joystick.action_map.get(key_id, "NONE")
                curr_disp_name = JOYSTICK_ACTIONS.get(curr_act_key, "❌ Desactivado / Sin Asignar")

                def update_live_ui():
                    lbl_detected_input.configure(
                        text=f"🟢 Detectado: {display_name}  ({key_id})",
                        text_color="#10b981"
                    )
                    opt_live_action.configure(state="normal")
                    opt_live_action.set(curr_disp_name)

                    # Log en caja de texto
                    txt_log.configure(state="normal")
                    txt_log.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] {display_name} ({key_id}) ➜ {curr_disp_name}\n")
                    txt_log.see("end")
                    txt_log.configure(state="disabled")

                modal.after(0, update_live_ui)

        self.joystick.on_raw_event = on_raw_joystick_event

        # ======================================================================
        # BARRA INFERIOR (RESTAURAR POR DEFECTO / CERRAR)
        # ======================================================================
        bottom_bar = ctk.CTkFrame(modal, fg_color="transparent")
        bottom_bar.pack(fill="x", padx=18, pady=(0, 14))

        def restore_defaults():
            self.joystick.action_map = dict(DEFAULT_JOYSTICK_MAP)
            self.config["joystick_map"] = dict(DEFAULT_JOYSTICK_MAP)
            save_config(self.config)

            # Actualizar todos los dropdowns
            for k, opt in dropdown_widgets.items():
                act_k = DEFAULT_JOYSTICK_MAP.get(k, "NONE")
                disp = JOYSTICK_ACTIONS.get(act_k, "❌ Desactivado / Sin Asignar")
                opt.set(disp)

            lbl_feedback.configure(
                text="✅ Controles restaurados a la configuración predeterminada de fábrica.",
                text_color="#10b981"
            )
            self.show_osd("CONTROLES RESTAURADOS", "Configuración de fábrica", icon="🎮", color="#10b981")

        btn_reset = ctk.CTkButton(
            bottom_bar,
            text="🔄 Restaurar Valores por Defecto",
            width=210,
            height=32,
            fg_color="gray25",
            hover_color="gray35",
            command=restore_defaults
        )
        btn_reset.pack(side="left")

        def on_modal_close():
            self.joystick.on_raw_event = None
            modal.destroy()

        btn_close = ctk.CTkButton(
            bottom_bar,
            text="✅ Guardar y Cerrar",
            width=140,
            height=32,
            fg_color="#0284c7",
            hover_color="#0369a1",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=on_modal_close
        )
        btn_close.pack(side="right")

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
