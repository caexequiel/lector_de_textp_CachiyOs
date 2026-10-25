#!/usr/bin/env bash
# Script de instalación e integración en el sistema CachyOS / GNOME

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$SCRIPT_DIR/main.py"
chmod +x "$SCRIPT_DIR/cli.py"
chmod +x "$SCRIPT_DIR/run.sh"

# Crear directorios de usuario necesarios
mkdir -p "$HOME/.local/share/applications"
mkdir -p "$HOME/.local/share/icons/hicolor"
mkdir -p "$HOME/.local/bin"

# 1. Generar e instalar iconos multirresolución para GNOME (Super, Dash y Alt+Tab)
SRC_ICON="$SCRIPT_DIR/assets/alumno.png"
if [ -f "$SRC_ICON" ]; then
    mkdir -p "$SCRIPT_DIR/assets/icons"
    for sz in 16 24 32 48 64 128 256 512; do
        if command -v magick &>/dev/null; then
            magick "$SRC_ICON" -resize ${sz}x${sz} "$SCRIPT_DIR/assets/icons/icon_${sz}.png" 2>/dev/null
        fi
        mkdir -p "$HOME/.local/share/icons/hicolor/${sz}x${sz}/apps"
        if [ -f "$SCRIPT_DIR/assets/icons/icon_${sz}.png" ]; then
            cp -f "$SCRIPT_DIR/assets/icons/icon_${sz}.png" "$HOME/.local/share/icons/hicolor/${sz}x${sz}/apps/lector-libros-ia.png" 2>/dev/null
        else
            cp -f "$SRC_ICON" "$HOME/.local/share/icons/hicolor/${sz}x${sz}/apps/lector-libros-ia.png" 2>/dev/null
        fi
    done
    cp -f "$SRC_ICON" "$HOME/.local/share/icons/lector-libros-ia.png" 2>/dev/null
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

# 2. Crear archivo .desktop para integración total en GNOME
DESKTOP_FILE="$HOME/.local/share/applications/lector-libros-ia.desktop"

cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Name=Lector de Libros IA
GenericName=Lector de Libros y Documentos IA
Comment=Lector neuronal de libros, PDFs y documentos con control por joystick
Exec=$SCRIPT_DIR/run.sh %f
Icon=lector-libros-ia
Terminal=false
Type=Application
StartupWMClass=lector-libros-ia
Categories=AudioVideo;Audio;Education;Utility;
MimeType=application/pdf;application/epub+zip;text/plain;text/markdown;
Keywords=audiobook;tts;voice;reader;joystick;gimnasio;lector;libros;alumno;
StartupNotify=true
EOF

chmod +x "$DESKTOP_FILE"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null

# 3. Lanzador de selección primaria para atajos de teclado (Ctrl+Super+V)
READ_SEL_SCRIPT="$HOME/.local/bin/ai-read-selection.sh"
cat <<'EOF' > "$READ_SEL_SCRIPT"
#!/usr/bin/env bash
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

# Capturar texto resaltado en pantalla (ratón / portapapeles)
TEXT=""
if [ -n "$WAYLAND_DISPLAY" ]; then
    TEXT=$(wl-paste --primary 2>/dev/null)
fi
[ -z "$TEXT" ] && TEXT=$(xclip -o -selection primary 2>/dev/null)
[ -z "$TEXT" ] && TEXT=$(wl-paste 2>/dev/null)
[ -z "$TEXT" ] && TEXT=$(xclip -o -selection clipboard 2>/dev/null)

CLEAN_TEXT="$(echo "$TEXT" | tr -d '[:space:]')"

# Si la aplicación ya está abierta:
if pgrep -f "main.py" > /dev/null || pgrep -f "lector-libros-ia" > /dev/null; then
    pkill -f "main.py" 2>/dev/null
    pkill -f "mpv_reader_socket" 2>/dev/null
    if [ -z "$CLEAN_TEXT" ]; then
        exit 0
    fi
    sleep 0.2
fi

LAUNCHER="/home/exequiel/LectorLibrosIA/run.sh"
if [ ! -x "$LAUNCHER" ]; then
    LAUNCHER="$HOME/.local/bin/ai-reader-gui.py"
fi

if [ -n "$CLEAN_TEXT" ]; then
    echo "$TEXT" | "$LAUNCHER" &
else
    "$LAUNCHER" &
fi
EOF
chmod +x "$READ_SEL_SCRIPT"

# 4. Mantener compatibilidad con scripts anteriores en ~/.local/bin
cat <<EOF > "$HOME/.local/bin/ai-reader-gui.py"
#!/usr/bin/env bash
exec "$SCRIPT_DIR/run.sh" "\$@"
EOF
chmod +x "$HOME/.local/bin/ai-reader-gui.py"

cat <<EOF > "$HOME/.local/bin/ai-reader.py"
#!/usr/bin/env bash
exec "$HOME/.local/bin/.venv/bin/python" "$SCRIPT_DIR/cli.py" "\$@"
EOF
chmod +x "$HOME/.local/bin/ai-reader.py"

# 5. Configurar atajos de teclado de GNOME en CachyOS
if command -v gsettings &>/dev/null; then
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/', '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom1/', '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom4/']" 2>/dev/null || true
    
    # Atajo principal: Ctrl + Super + V
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom1/ name "Leer Selección con Lector IA" 2>/dev/null || true
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom1/ command "$READ_SEL_SCRIPT" 2>/dev/null || true
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom1/ binding "<Control><Super>v" 2>/dev/null || true

    # Atajo alternativo: Ctrl + Alt + Super + V
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom4/ name "Leer Selección con Lector IA (Alternativo)" 2>/dev/null || true
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom4/ command "$READ_SEL_SCRIPT" 2>/dev/null || true
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom4/ binding "<Control><Alt><Super>v" 2>/dev/null || true
fi

echo "✅ Instalación e integración completadas con éxito."
echo "• Ícono del alumno instalado en resoluciones 16x16 a 512x512 para Alt+Tab y Dash."
echo "• Atajo de teclado activado: [Ctrl + Super + V] (lee el texto seleccionado con el ratón)."
echo "• Atajo alternativo: [Ctrl + Alt + Super + V]."
