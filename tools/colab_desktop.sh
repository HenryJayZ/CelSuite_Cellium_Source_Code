#!/bin/bash
# colab_desktop.sh - one-shot clickable XFCE desktop via noVNC (idempotent, safe to re-run).
# Tomorrow: just run this script, then serve port 6080 from a Colab cell:
#   from google.colab import output
#   output.serve_kernel_port_as_window(6080)
set -u
export USER="${USER:-root}" LOGNAME="${LOGNAME:-root}"
VNC_PASS="${VNC_PASS:-henny123}"
GEO="${GEO:-1280x800}"

mkdir -p "$HOME/.vnc"
if [ ! -f "$HOME/.vnc/passwd" ]; then
  printf '%s\n%s\nn\n' "$VNC_PASS" "$VNC_PASS" | vncpasswd
fi
printf '#!/bin/sh\nunset SESSION_MANAGER\nunset DBUS_SESSION_BUS_ADDRESS\nexec startxfce4\n' > "$HOME/.vnc/xstartup"
chmod +x "$HOME/.vnc/xstartup"

pgrep -af '[X]tightvnc.*:1' >/dev/null 2>&1 || vncserver :1 -geometry "$GEO" -depth 24
(ss -tln 2>/dev/null | grep -q ':6080 ') || websockify -D --web=/usr/share/novnc/ 6080 localhost:5901
sleep 1
(ss -tln 2>/dev/null || netstat -tln 2>/dev/null) | grep -E ':5901|:6080' || echo "PORTS-MISSING"
echo DESKTOP-UP
