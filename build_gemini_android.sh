#!/usr/bin/env bash
# CelSuite Cellium (Gemini Android) — Autonomous Mobile APK Builder
# Bumps date-based version (YYMM.DD.V), compiles Vite web bundle,
# syncs assets to Android project, and runs Gradle debug assembly.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$REPO/Gemini Android"
ANDROID_DIR="$APP_DIR/android"
GRADLE_FILE="$ANDROID_DIR/app/build.gradle.kts"
ASSETS_DIR="$ANDROID_DIR/app/src/main/assets/public"

KIT_ON_MX="/media/henry/rootMX25/home/henry/Documents/Projects/Kotlin"
LEGACY="/home/henry/Documents/Projects/Kotlin"

if [ -f "$LEGACY/env.sh" ]; then
    KIT="$LEGACY"
elif [ -f "$KIT_ON_MX/env.sh" ]; then
    ln -sfn "$KIT_ON_MX" "$LEGACY"
    KIT="$LEGACY"
else
    echo "⚠️ Offline Kotlin kit not found in $LEGACY, falling back to system tools..."
    KIT=""
fi

if [ -n "$KIT" ]; then
    # shellcheck source=/dev/null
    source "$KIT/env.sh"
fi

# Step 1: Compile Vite + React Frontend
echo "📦 Step 1: Compiling Vite + React mobile frontend..."
cd "$APP_DIR" || exit 1
npm run build || { echo "FATAL: npm run build failed" >&2; exit 1; }

# Step 2: Copy web assets to Android assets folder
echo "🚚 Step 2: Syncing compiled distribution assets to Android..."
mkdir -p "$ASSETS_DIR"
rm -rf "${ASSETS_DIR:?}"/*
cp -r "$APP_DIR/dist/"* "$ASSETS_DIR/"

# Step 3: Date-Based Version Bumping (YYMM.DD.V and versionCode YYMMDDVV)
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

txt = re.sub(r'versionName\s*=\s*"[^"]+"', f'versionName = "{new_name}"', txt, count=1)
txt = re.sub(r'versionCode\s*=\s*\d+', f'versionCode = {new_code}', txt, count=1)
gf.write_text(txt, encoding="utf-8")
print(f"version    : {old_name} ({old_code}) -> {new_name} ({new_code})")
PYEOF

# Step 4: Run Gradle build
echo "🔨 Step 4: Running Gradle assembly..."
cd "$ANDROID_DIR" || exit 1

GRADLE_NET="--offline"
[ "${ONLINE:-0}" = "1" ] && GRADLE_NET=""

# Set machine-local SDK pointer
printf 'sdk.dir=%s\n' "${ANDROID_HOME:-/home/henry/Documents/Projects/Kotlin/android-sdk}" > "$ANDROID_DIR/local.properties"

if [ "${1:-}" = "clean" ]; then
    gradle clean $GRADLE_NET --no-daemon --console=plain || true
fi

gradle :app:assembleDebug $GRADLE_NET --no-daemon --console=plain
status=$?

if [ $status -ne 0 ]; then
    echo "⚠️ Offline Gradle build failed, trying without --offline if ONLINE is set..."
    if [ "${ONLINE:-0}" = "1" ]; then
        gradle :app:assembleDebug --no-daemon --console=plain
        status=$?
    fi
fi

if [ $status -ne 0 ]; then
    echo "BUILD FAILED (exit $status)" >&2
    exit $status
fi

APK="$ANDROID_DIR/app/build/outputs/apk/debug/app-debug.apk"
[ -f "$APK" ] || { echo "FATAL: assembleDebug reported success but no APK at $APK" >&2; exit 1; }

VER=$(grep -oE 'versionName[[:space:]]*=[[:space:]]*"[0-9.]+"' "$GRADLE_FILE" \
      | grep -oE '[0-9.]+' | head -1)
mkdir -p "$REPO/dist"
OUT="$REPO/dist/HenryJayZ.CelSuite.Cellium-v$VER.apk"
cp -f "$APK" "$OUT"

echo
echo "✅ BUILD SUCCESSFUL -> $OUT"
ls -la "$OUT"
echo "Install to device with:  adb install -r -d $OUT"
