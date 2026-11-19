#!/usr/bin/env bash
# CelSuite Cellium - OFFLINE Android build with automatic YYM.DD.V version bumping.
#
# Automatically reads today's date (e.g. Oct 17, 2026 -> 2610.17) and increments
# the build suffix (.0 -> .1 -> .2 ...) and 8-digit versionCode (26101701 -> 26101702)
# on every run so `adb install -r` never hits INSTALL_FAILED_VERSION_DOWNGRADE.

set -uo pipefail

KIT_ON_MX=/media/henry/rootMX25/home/henry/Documents/Projects/Kotlin
LEGACY=/home/henry/Documents/Projects/Kotlin

if [ -f "$LEGACY/env.sh" ]; then
    KIT="$LEGACY"
elif [ -f "$KIT_ON_MX/env.sh" ]; then
    ln -sfn "$KIT_ON_MX" "$LEGACY"
    KIT="$LEGACY"
else
    echo "FATAL: offline Kotlin build kit not found." >&2
    echo "  looked in: $LEGACY" >&2
    echo "            $KIT_ON_MX" >&2
    echo "  mount it with:  sudo mount /dev/sda7 /media/henry/rootMX25" >&2
    exit 1
fi

# shellcheck source=/dev/null
source "$KIT/env.sh"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default to Gemini Android builder unless 'legacy' is explicitly requested
if [ "${1:-}" != "legacy" ]; then
    exec "$REPO/build_gemini_android.sh" "$@"
fi
shift

APP="$REPO/Android/cellium-app"
GRADLE_FILE="$APP/app/build.gradle.kts"

# Keep machine-local SDK pointer accurate
printf 'sdk.dir=%s\n' "${ANDROID_HOME:-$KIT/android-sdk}" > "$APP/local.properties"

# Smart Date-Based Version Bumper (YYMM.DD.V and 8-digit versionCode YYMMDDVV)
PY_BIN="/home/henry/Documents/Projects/Python/venv/bin/python"
if [ ! -x "$PY_BIN" ]; then
    PY_BIN="python3"
fi

"$PY_BIN" - "$GRADLE_FILE" << 'PYEOF'
import datetime as dt
import re
import sys
from pathlib import Path

gf = Path(sys.argv[1])
txt = gf.read_text(encoding="utf-8")

now = dt.datetime.now()
yy = now.strftime("%y")
mm = f"{now.month:02d}"
dd = f"{now.day:02d}"
today_prefix = f"{yy}{mm}.{dd}"
today_code_base = int(f"{yy}{mm}{dd}00")

m_name = re.search(r'versionName\s*=\s*"([^"]+)"', txt)
m_code = re.search(r'versionCode\s*=\s*(\d+)', txt)

old_name = m_name.group(1) if m_name else f"{today_prefix}.0"
old_code = int(m_code.group(1)) if m_code else today_code_base

if old_name.startswith(today_prefix + "."):
    try:
        old_v = int(old_name.rsplit(".", 1)[1])
    except ValueError:
        old_v = 0
    new_v = old_v + 1
else:
    new_v = 1

new_name = f"{today_prefix}.{new_v}"
new_code = max(old_code + 1, today_code_base + min(new_v, 99))

if new_code - today_code_base > new_v:
    new_v = new_code - today_code_base
    new_name = f"{today_prefix}.{new_v}"

txt = re.sub(r'versionName\s*=\s*"[^"]+"', f'versionName = "{new_name}"', txt, count=1)
txt = re.sub(r'versionCode\s*=\s*\d+', f'versionCode = {new_code}', txt, count=1)
gf.write_text(txt, encoding="utf-8")
print(f"version    : {old_name} ({old_code}) -> {new_name} ({new_code})")
PYEOF

cd "$APP" || { echo "FATAL: $APP missing" >&2; exit 1; }

echo "kit        : $KIT"
echo "JAVA_HOME  : ${JAVA_HOME:-unset}"
echo "ANDROID_HOME: ${ANDROID_HOME:-unset}"
echo "GRADLE_USER_HOME: ${GRADLE_USER_HOME:-unset}"

# Offline by default. ONLINE=1 seeds the kit cache for newly added deps.
GRADLE_NET="--offline"
[ "${ONLINE:-0}" = "1" ] && GRADLE_NET=""

if [ "${1:-}" = "clean" ]; then
    gradle clean $GRADLE_NET --no-daemon --console=plain
fi

gradle :app:assembleDebug $GRADLE_NET --no-daemon --console=plain
status=$?
if [ $status -ne 0 ]; then
    echo "BUILD FAILED (exit $status)" >&2
  echo "📦 Generating Android_Errors_Bundle.md..."
  python3 "$REPO/tools/bundle_errors.py" || echo "  (bundler failed)"
  exit $status
fi

APK="$APP/app/build/outputs/apk/debug/app-debug.apk"
[ -f "$APK" ] || { echo "FATAL: assembleDebug reported success but no APK at $APK" >&2; exit 1; }

VER=$(grep -oE 'versionName[[:space:]]*=[[:space:]]*"[0-9.]+"' "$GRADLE_FILE" \
      | grep -oE '[0-9.]+' | head -1)
mkdir -p "$REPO/dist"
OUT="$REPO/dist/HenryJayZ.CelSuite.Cellium-v$VER.apk"
cp -f "$APK" "$OUT"

echo
echo "BUILD SUCCESSFUL -> $OUT"
ls -la "$OUT"
echo "install with:  adb install -r -d $OUT"
