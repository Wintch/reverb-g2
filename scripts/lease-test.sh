#!/bin/bash
# lease-test.sh <labwc|hyprland> -- run from a text VT (Ctrl+Alt+F3 login), headset connected and awake.
# Starts the compositor, runs check-lease.sh inside it, saves the answer, then exits the compositor.
# Answers ONE question: does this compositor offer the G2's connector for DRM lease (NVIDIA)?
set -u
C="${1:?usage: $0 <labwc|hyprland>}"
S="$HOME/Documents/reverb-g2/scripts"; L="$HOME/vr/logs"; mkdir -p "$L"
OUT="$L/lease-test-$C-$(date +%Y%m%d-%H%M%S).txt"
INNER="$HOME/vr/lease-test-inner.sh"
H=$HOME/vr/hyprland-build/prefix
cat > "$INNER" <<EOS
#!/bin/bash
sleep 4
{
  echo "compositor: $C   \$(date)"; echo "driver: \$(cat /proc/driver/nvidia/version | head -1)"
  echo "XDG_SESSION_TYPE=\$XDG_SESSION_TYPE  WAYLAND_DISPLAY=\$WAYLAND_DISPLAY"; echo
  bash "$S/check-lease.sh"; echo "check-lease rc=\$?"; echo
  echo "=== full wayland-info (lease + outputs) ==="; wayland-info 2>&1 | grep -iE "lease|connector|name:|make|model" | head -40
} > "$OUT" 2>&1
EOS
chmod +x "$INNER"
export __GLX_VENDOR_LIBRARY_NAME=nvidia LIBVA_DRIVER_NAME=nvidia WLR_NO_HARDWARE_CURSORS=1 XDG_SESSION_TYPE=wayland
case "$C" in
  labwc)
    timeout 90 labwc -s "sh -c '$INNER; labwc --exit'" ;;
  hyprland)
    export LD_LIBRARY_PATH=$H/lib PATH=$H/bin:$PATH
    CONF="$HOME/vr/lease-test-hypr.conf"
    printf 'cursor {\n  no_hardware_cursors = true\n}\nmisc {\n  disable_hyprland_logo = true\n  disable_splash_rendering = true\n}\nexec-once = sh -c "%s; hyprctl dispatch exit"\n' "$INNER" > "$CONF"
    timeout 90 Hyprland -c "$CONF" ;;
  *) echo "unknown compositor $C"; exit 1 ;;
esac
echo; echo "=== RESULT ($OUT) ==="; cat "$OUT" 2>/dev/null || echo "(no output file: the compositor did not start; see ~/vr/logs and the messages above)"
