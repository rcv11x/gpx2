#!/usr/bin/env bash
# Instala gpx2 para el usuario actual. No necesita sudo y no toca el sistema:
# todo va a ~/.local/. Para desinstalar: ./install.sh --uninstall
set -euo pipefail

APP_ID="io.github.rcv11x.gpx2"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ICONOS="$HOME/.local/share/icons/hicolor/scalable/apps"
APPS="$HOME/.local/share/applications"
BIN="$HOME/.local/bin"

if [[ "${1:-}" == "--uninstall" ]]; then
    systemctl --user disable --now gpx2d.service 2>/dev/null || true
    rm -f "$ICONOS/$APP_ID.svg" "$APPS/$APP_ID.desktop" "$BIN/gpx2" "$BIN/gpx2d"
    rm -f "$HOME/.config/systemd/user/gpx2d.service"
    systemctl --user daemon-reload 2>/dev/null || true
    update-desktop-database "$APPS" 2>/dev/null || true
    echo "gpx2 desinstalado (la regla udev, si la instalaste, sigue puesta)."
    exit 0
fi

mkdir -p "$ICONOS" "$APPS" "$BIN"

install -m644 "$RAIZ/data/gpx2.svg" "$ICONOS/$APP_ID.svg"
sed "s|^Exec=gpx2$|Exec=$BIN/gpx2|" "$RAIZ/data/$APP_ID.desktop" > "$APPS/$APP_ID.desktop"
chmod 644 "$APPS/$APP_ID.desktop"

cat > "$BIN/gpx2" <<LANZADOR
#!/usr/bin/env bash
exec python3 "$RAIZ/run_gui.py" "\$@"
LANZADOR
chmod +x "$BIN/gpx2"

cat > "$BIN/gpx2d" <<LANZADOR
#!/usr/bin/env bash
cd "$RAIZ" && exec python3 -m gpx2.daemon "\$@"
LANZADOR
chmod +x "$BIN/gpx2d"

UNIDADES="$HOME/.config/systemd/user"
mkdir -p "$UNIDADES"
sed "s|^ExecStart=/usr/bin/gpx2d$|ExecStart=$BIN/gpx2d|" \
    "$RAIZ/data/gpx2d.service" > "$UNIDADES/gpx2d.service"
chmod 644 "$UNIDADES/gpx2d.service"
systemctl --user daemon-reload 2>/dev/null || true

update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Instalado:"
echo "  interfaz : $BIN/gpx2"
echo "  demonio  : $BIN/gpx2d"
echo "  servicio : systemctl --user enable --now gpx2d.service"
echo "  icono    : $ICONOS/$APP_ID.svg"
echo "  menú     : $APPS/$APP_ID.desktop"
echo

if [[ ! -f /etc/udev/rules.d/99-logitech-hidpp.rules ]]; then
    echo "FALTA el permiso para hablar con el ratón. Ejecuta esto una vez:"
    echo
    echo "  sudo cp $RAIZ/99-logitech-hidpp.rules /etc/udev/rules.d/"
    echo "  sudo udevadm control --reload-rules && sudo udevadm trigger"
    echo
    echo "Y desconecta y reconecta el receptor."
else
    echo "La regla udev ya está instalada."
fi

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo; echo "Nota: $BIN no está en tu PATH; añádelo para poder escribir 'gpx2'." ;;
esac
