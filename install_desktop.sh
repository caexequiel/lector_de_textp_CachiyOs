#!/usr/bin/env bash
# Script de instalación e integración en el sistema CachyOS / GNOME

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$SCRIPT_DIR/main.py"
chmod +x "$SCRIPT_DIR/cli.py"
chmod +x "$SCRIPT_DIR/run.sh"

# Crear directorio de aplicaciones de usuario si no existe
mkdir -p "$HOME/.local/share/applications"
mkdir -p "$HOME/.local/bin"

# 1. Crear archivo .desktop para que aparezca en el menú de aplicaciones de GNOME
DESKTOP_FILE="$HOME/.local/share/applications/lector-libros-ia.desktop"

cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Name=Lector de Libros IA
Comment=Lector neuronal de libros, PDFs y documentos con control por joystick
Exec=$SCRIPT_DIR/run.sh %f
Icon=accessories-character-map
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Office;
MimeType=application/pdf;application/epub+zip;text/plain;text/markdown;
Keywords=audiobook;tts;voice;reader;joystick;gimnasio;
EOF

chmod +x "$DESKTOP_FILE"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null

# 2. Mantener compatibilidad con los atajos anteriores en ~/.local/bin
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

echo "✅ Instalación completada con éxito."
echo "• Aplicación integrada en el menú de GNOME: Lector de Libros IA"
echo "• Lanzador ejecutable: $SCRIPT_DIR/run.sh"
echo "• Atajo de teclado GNOME existente (Ctrl+Alt+Super+V) redirigido al nuevo proyecto."
