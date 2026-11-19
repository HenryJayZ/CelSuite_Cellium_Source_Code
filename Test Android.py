#!/usr/bin/env python3
"""
Test Android.py - launch CelSuite Cellium on a device (adb only), record
EVERYTHING for N seconds (default: 60 if the user inputs nothing), then package
the whole run into ONE markdown report and clean up after itself.

Henny's rules baked in:
  • adb only → works no matter how the phone's IP changes
    (discovery: `adb devices` → remembered IPs → `adb mdns services`)
  • the report is `Android_Bugs.md` in the repo root - ALWAYS overwritten,
    never appended
  • every raw dump (logcat/dumpsys/uiautomator/txt/xml) is DELETED after
    packaging - the .md is the only report that survives
  • latest screenshots live in tests/last_screenshots/ (cleared each run)
  • tests/.device_history.json keeps known IPs (never deleted)

Usage:
  venv
  python "Test Android.py"                  # 60 seconds, auto device + package
  python "Test Android.py" 30               # 30 seconds
  python "Test Android.py" 1m30s            # compound durations work too
  python "Test Android.py" 90 --no-perf     # skip periodic meminfo/screencaps
  python "Test Android.py" 60 --no-restart  # record WITHOUT relaunching first
  python "Test Android.py" 60 --serial <ip>:5555 --package <applicationId>

Exit codes: 0 clean · 1 warnings · 2 ANR/soft death · 3 hard crash ·
            10 no device · 11 no package installed · 130 interrupted
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
OUT_ROOT = REPO / "tests"
HISTORY_FILE = OUT_ROOT / ".device_history.json"
REPORT_FILE = REPO / "Android_Bugs.md"
SHOTS_DIR = OUT_ROOT / "last_screenshots"
APP_GRADLE = (REPO / "Gemini Android" / "android" / "app" / "build.gradle.kts"
              if (REPO / "Gemini Android" / "android" / "app" / "build.gradle.kts").exists()
              else REPO / "Android" / "cellium-app" / "app" / "build.gradle.kts")
DEFAULT_APP_ID = "HenryJayZ.CelSuite.Cellium"
ADB = shutil.which("adb") or "/usr/bin/adb"
ANOMALY_CAP = 1500


# ─────────────────────────────────────────────────────────────── adb helpers
def run_adb(args: list[str], serial: str | None = None, timeout: float = 20.0,
            binary: bool = False):
    """Run one adb command. Returns (rc, stdout_text_or_bytes, stderr_text)."""
    cmd = [ADB] + (["-s", serial] if serial else []) + args
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, (b"TIMEOUT" if binary else "TIMEOUT"), "timeout"
    except FileNotFoundError:
        return 127, "", "adb binary not found"
    if binary:
        return (p.returncode, p.stdout or b"",
                (p.stderr or b"").decode("utf-8", "replace"))
    return (p.returncode, (p.stdout or b"").decode("utf-8", "replace"),
            (p.stderr or b"").decode("utf-8", "replace"))


def sh(serial: str | None, command_line: str, timeout: float = 20.0) -> str:
    """`adb shell <command_line>` → stdout text (stripped)."""
    return run_adb(["shell", command_line], serial, timeout)[1].strip()


def device_rows() -> list[dict]:
    out = run_adb(["devices", "-l"], timeout=15)[1]
    rows: list[dict] = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or "List of devices" in line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            row = {"serial": parts[0], "state": parts[1]}
            for tok in parts[2:]:
                if ":" in tok:
                    k, v = tok.split(":", 1)
                    row[k] = v
            rows.append(row)
    return rows


def ready_serials() -> list[dict]:
    return [r for r in device_rows() if r["state"] == "device"]


def remembered_addresses() -> list[str]:
    try:
        data = json.loads(HISTORY_FILE.read_text())
        return [a for a in data if isinstance(a, str)]
    except Exception:
        return []


def remember_address(serial: str) -> None:
    """Persist ip:port serials so future runs auto-reconnect (no hardcoded IP)."""
    if ":" not in serial:
        return
    try:
        all_addrs = remembered_addresses()
        if serial in all_addrs:
            all_addrs.remove(serial)
        all_addrs.insert(0, serial)
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(all_addrs[:12], indent=1))
    except Exception:
        pass


def try_connect(address: str) -> bool:
    out = run_adb(["connect", address], timeout=12)[1] or ""
    return "connected" in out          # "connected to" / "already connected to"


def mdns_candidates() -> list[str]:
    """Parse `adb mdns services` for _adb-tls-connect services."""
    out = run_adb(["mdns", "services"], timeout=10)[1] or ""
    found: list[str] = []
    # format: ADB-192-168-1-167-5555._adb-tls-connect._tcp
    for m in re.finditer(r"ADB-([0-9\-]+)\._adb-tls-connect", out):
        parts = m.group(1).split("-")
        if len(parts) >= 5:
            ip = ".".join(parts[:4])
            port = parts[4]
            found.append(f"{ip}:{port}" if port.isdigit() else f"{ip}:5555")
    seen, uniq = set(), []
    for cand in found:
        if cand not in seen:
            seen.add(cand)
            uniq.append(cand)
    return uniq


def pick_device(want: str | None = None) -> str | None:
    """One ready device → it. --serial disambiguates. Else try auto-connect."""
    ready = ready_serials()
    if want:
        if any(r["serial"] == want for r in ready):
            return want
        states = [f"{r['serial']}:{r['state']}" for r in device_rows()]
        print(f"✗ requested device '{want}' not ready; adb devices: {states}")
        return None
    if len(ready) == 1:
        return ready[0]["serial"]
    if len(ready) > 1:
        print("! multiple devices ready - pass --serial, one of:")
        for r in ready:
            print(f"      {r['serial']}   ({r.get('model', '?')})")
        return None
    for cand in remembered_addresses() + mdns_candidates():
        print(f"• trying adb connect {cand} …")
        if try_connect(cand):
            now_ready = ready_serials()
            if now_ready:
                return now_ready[0]["serial"]
    return None


# ─────────────────────────────────────────────────────────── package resolution
def read_versions() -> tuple[str, str, str]:
    """(applicationId, versionName, versionCode) from the gradle file."""
    app_id, vname, vcode = DEFAULT_APP_ID, "?", "?"
    try:
        gradle_txt = APP_GRADLE.read_text()
        m = re.search(r'applicationId\s*=\s*"([^"]+)"', gradle_txt)
        if m:
            app_id = m.group(1)
        m = re.search(r'versionName\s*=\s*"([^"]+)"', gradle_txt)
        if m:
            vname = m.group(1)
        m = re.search(r"versionCode\s*=\s*(\d+)", gradle_txt)
        if m:
            vcode = m.group(1)
    except Exception:
        pass
    return app_id, vname, vcode


def package_exists(serial: str, pkg: str) -> bool:
    return sh(serial, f"pm path {pkg}", 12).startswith("package:")


def pick_package(serial: str, app_id: str, override: str | None) -> str | None:
    if override:
        return override if package_exists(serial, override) else None
    for cand in (f"{app_id}.debug", app_id):      # debug first - the iterating build
        if package_exists(serial, cand):
            return cand
    out = sh(serial, "pm list packages", 10)
    m = re.search(r"package:([A-Za-z0-9._]*[Cc]ellium[A-Za-z0-9._]*)", out)
    return m.group(1) if m else None


def resolve_launcher(serial: str, pkg: str) -> str | None:
    out = sh(serial, f"cmd package resolve-activity --brief {pkg}", 14)
    for line in reversed(out.splitlines()):
        line = line.strip()
        if "/" in line and not line.lower().startswith("priority"):
            return line
    return None


def pid_of(serial: str, pkg: str) -> int | None:
    out = sh(serial, f"pidof {pkg}", 10)
    m = re.search(r"\b(\d+)\b", out)
    return int(m.group(1)) if m else None


# ─────────────────────────────────────────────────────────── background stream
class LogStream(threading.Thread):
    """`adb logcat <args>` reader thread: streams to file, counts levels."""

    LINE = re.compile(
        r"^(\d{2}-\d{2}|[A-Za-z]{3})\s+([0-9:.]+)\s+(\d+)\s+(\d+)\s+([VDIWEF])\s+(.*)$"
    )

    def __init__(self, serial: str, log_args: list[str], out_path: Path):
        super().__init__(daemon=True)
        self.cmd = [ADB] + (["-s", serial] if serial else []) + log_args
        self.out_path = out_path
        self.lines: list[str] = []
        self.levels = {k: 0 for k in "VDIWEF"}
        self.dropped = False
        self.err: str | None = None
        self._stop = threading.Event()
        self._fh = open(out_path, "wb")

    def alive(self) -> bool:
        p = getattr(self, "proc_ref", None)
        return p is not None and p.poll() is None

    def run(self) -> None:
        try:
            with subprocess.Popen(self.cmd, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL,
                                  stdin=subprocess.DEVNULL) as proc:
                self.proc_ref = proc
                assert proc.stdout is not None
                for raw in iter(proc.stdout.readline, b""):
                    if self._stop.is_set():
                        break
                    self._feed(raw)
                if not self._stop.is_set():
                    self.dropped = True
        except Exception as exc:
            self.err = str(exc)
            self.dropped = True
        finally:
            try:
                self._fh.close()
            except Exception:
                pass

    def _feed(self, raw: bytes) -> None:
        self._fh.write(raw)
        line_txt = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line_txt or line_txt.startswith("---------"):
            return
        m = self.LINE.match(line_txt)
        if m:
            self.levels[m.group(5)] += 1
        if len(self.lines) < 300_000:
            self.lines.append(line_txt)

    def stop(self) -> None:
        self._stop.set()
        p = getattr(self, "proc_ref", None)
        if p is not None and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=4)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass


# ──────────────────────────────────────────────────────────── analysis helpers
CRASHY = re.compile(
    r"FATAL|AndroidRuntime|ANR in|has died|Force finishing|SIGSEGV|SIGABRT|"
    r"SIGKILL|tombstone|lowmemorykiller|OutOfMemoryError|Permission Denial|"
    r"beginning of crash", re.IGNORECASE)
APPISH = re.compile(r"HenryJayZ|CelSuite|Cellium", re.IGNORECASE)
COUNTED = ("FATAL EXCEPTION", "ANR in", "OutOfMemoryError",
           "Permission Denial", "tombstone")


def harvest(all_lines: list[str], crash_lines: list[str]) -> dict:
    stats = {k: 0 for k in "VDIWEF"}
    bad: list[str] = []
    fatal = anr = False
    app_errors = 0
    pcounts = {name: 0 for name in COUNTED}

    def scan(line_txt: str, count_levels: bool) -> None:
        nonlocal fatal, anr, app_errors
        m = LogStream.LINE.match(line_txt)
        if m:
            if count_levels:
                stats[m.group(5)] += 1
            tag = m.group(6).split(":", 1)[0]
            if m.group(5) in "EF" and APPISH.search(tag + " " + line_txt):
                app_errors += 1
        else:
            m2 = re.match(r"^([VDIWEF])/", line_txt)
            if m2 and count_levels:
                stats[m2.group(1)] += 1
        low = line_txt.lower()
        for name in COUNTED:
            if name.lower() in low:
                pcounts[name] += 1
        if CRASHY.search(line_txt):
            bad.append(line_txt)
        if "FATAL EXCEPTION" in line_txt:
            fatal = True
        if "ANR in" in line_txt:
            anr = True

    for ln in all_lines:
        scan(ln, True)
    for ln in crash_lines:
        if ln not in bad:
            scan(ln, False)

    return {"levels": stats, "bad": bad, "fatal": fatal, "anr": anr,
            "app_errors": app_errors, "patterns": pcounts}


def top_error_tags(lines: list[str], limit: int = 12) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for ln in lines:
        m = LogStream.LINE.match(ln)
        if m and m.group(5) == "E":
            tag = m.group(6).split(":", 1)[0].strip()
            if tag:
                counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def verdict_of(result: dict, pid_died: bool) -> tuple[str, int]:
    if result["fatal"]:
        return "HARD CRASH - see Anomalies below", 3
    if result["anr"] or pid_died:
        return "ANR / PROCESS DIED - see Anomalies + PID timeline", 2
    if result["app_errors"]:
        return "APP ERRORS (E/F from the app) - see Anomalies", 1
    if result["bad"]:
        return "SYSTEM WARNINGS TOUCHING THE APP - scroll Anomalies", 1
    return "CLEAN", 0


# ─────────────────────────────────────────────────────────── report rendering
def render_report(meta: dict, result: dict, pid_log: list[str], launch_how: str,
                  mem_series: list[str], excerpts: dict[str, str],
                  ui_texts: str, shot_names: list[str],
                  top: list[tuple[str, int]]) -> tuple[str, int]:
    verdict, code = verdict_of(result, meta["pid_died"])
    stats = result["levels"]
    bad = result["bad"]
    out: list[str] = []

    def add(text: str = "") -> None:
        out.append(text)

    add("# Android_Bugs - adb forensic report (`Test Android.py`)")
    add()
    add("> This whole file is **overwritten on every run** - raw dumps "
        "(logcat / dumpsys / uiautomator / txt / xml) are deleted after "
        "packaging. Only this file + `tests/last_screenshots/` persist.")
    add()
    add("## Run")
    add()
    add("| field | value |")
    add("|---|---|")
    add(f"| timestamp | {meta['ts']} |")
    add(f"| device | `{meta['serial']}` - Android {meta['release']} (SDK {meta['sdk']}) |")
    add(f"| package | `{meta['pkg']}` - installed v{meta['installed_version']} |")
    add(f"| source | versionName {meta['gradle_version']}, versionCode {meta['gradle_code']} |")
    add(f"| launcher | `{meta['launcher'] or 'monkey fallback'}` |")
    add(f"| launch method | {launch_how} |")
    add(f"| window | {meta['seconds']}s, snapshots every {meta['interval']}s |")
    add()
    add(f"## Verdict - {verdict}")
    add()
    add("### Counters")
    add()
    add("| metric | value |")
    add("|---|---|")
    add("| log levels | " + " ".join(f"{k}: {stats[k]}" for k in "VDIWEF") + " |")
    add(f"| anomaly lines | {len(bad)} |")
    add(f"| app E/F lines | {result['app_errors']} |")
    add("| patterns | " + ", ".join(
        f"{k}={v}" for k, v in result["patterns"].items()) + " |")
    add()
    if top:
        add("### Top error tags")
        add()
        add("| tag | E lines |")
        add("|---|---|")
        for tag, cnt in top:
            add(f"| `{tag}` | {cnt} |")
        add()
    add("### PID timeline")
    add()
    add("```text")
    out.extend(pid_log)
    add("```")
    add()
    if mem_series:
        add("### Memory (dumpsys meminfo TOTAL)")
        add()
        add("```text")
        out.extend(mem_series)
        add("```")
        add()
    if ui_texts:
        add("### Visible UI texts (final uiautomator dump)")
        add()
        add("```text")
        add(ui_texts)
        add("```")
        add()
    for label, value in excerpts.items():
        if value and value.strip():
            add(f"### {label}")
            add()
            add("```text")
            add(value.strip())
            add("```")
            add()
    shown = len(bad) if len(bad) <= ANOMALY_CAP else ANOMALY_CAP
    add(f"### Anomalies ({len(bad)} lines, first {shown} shown)")
    add()
    add("```text")
    for ln in bad[:ANOMALY_CAP]:
        add(ln)
    if len(bad) > ANOMALY_CAP:
        add(f"... ({len(bad) - ANOMALY_CAP} more lines truncated)")
    add("```")
    add()
    if shot_names:
        add("### Screenshots (latest run)")
        add()
        for name in shot_names:
            add(f"![{name}](tests/last_screenshots/{name})")
        add()
    add("---")
    add("*Generated by `Test Android.py` - adb only, device-IP independent. "
        "Exit codes: 0 clean · 1 warnings · 2 ANR/died · 3 crash.*")
    return "\n".join(out) + "\n", code


# ─────────────────────────────────────────────────────────────────── artifacts
def screencap(serial: str, dest: Path) -> bool:
    rc, data, _ = run_adb(["exec-out", "screencap", "-p"], serial, 20, binary=True)
    if rc == 0 and isinstance(data, bytes) and data.startswith(b"\x89PNG"):
        dest.write_bytes(data)
        return True
    return False


def snapshot(serial: str, pkg: str, idx: int, elapsed: float, flags) -> str | None:
    """One periodic snapshot. Returns the meminfo TOTAL line (or None)."""
    tag = f"{idx:02d}_t{elapsed:06.1f}"
    if not flags.no_screen:
        screencap(serial, SHOTS_DIR / f"{tag}.png")
    if not flags.no_perf:
        mem = sh(serial, f"dumpsys meminfo {pkg}", 25)
        for ln in mem.splitlines():
            if ln.strip().startswith("TOTAL"):
                return f"t+{elapsed:6.1f}s  " + " ".join(ln.split())
    return None


def collect_excerpts(serial: str, pkg: str) -> dict[str, str]:
    """Small, high-value runtime excerpts (raw dumps are deleted anyway)."""
    return {
        "Window focus (final)": sh(
            serial, "dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | head -4", 30),
        "Battery": sh(
            serial, "dumpsys battery | grep -E 'level|temperature' | head -4", 15),
        "CPU (app rows)": sh(
            serial, "dumpsys cpuinfo | grep -iE 'cellium' | head -8", 30),
        "Activity (resumed)": sh(
            serial, "dumpsys activity top | grep -E 'ACTIVITY|ResumedActivity' | head -10", 30),
        "Processes (app rows)": sh(
            serial, "dumpsys activity processes | grep -iE 'HenryJayZ|CelSuite|Cellium' | head -30", 30),
    }


def ui_dump_texts(serial: str) -> str:
    sh(serial, "uiautomator dump /sdcard/window_dump.xml", 30)
    xml = run_adb(["shell", "cat", "/sdcard/window_dump.xml"], serial, 15)[1]
    sh(serial, "rm -f /sdcard/window_dump.xml", 8)
    if not isinstance(xml, str):
        return ""
    texts: list[str] = []
    for t in re.findall(r'text="([^"]+)"', xml):
        t = t.strip()
        if t and t not in texts:
            texts.append(t)
    return " | ".join(texts[:40])


def parse_duration(text_value: str) -> int:
    s_v = str(text_value).strip().lower()
    combo = re.match(r"^(\d+)m(\d+)s$", s_v)
    if combo:
        return int(combo.group(1)) * 60 + int(combo.group(2))
    m = re.match(r"^(\d+)(m|s)?$", s_v)
    if not m:
        raise argparse.ArgumentTypeError(
            f"bad duration: {text_value!r} (use 90, 2m, 1m30s)")
    return int(m.group(1)) * (60 if m.group(2) == "m" else 1)


# ──────────────────────────────────────────────────────────────── main session
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="Test Android.py",
        description="Launch Cellium, dump every adb log for N seconds, "
                    "package it all into Android_Bugs.md.")
    parser.add_argument("duration", nargs="?", default="60",
                        help="seconds to record: 90 | 2m | 1m30s (default 60)")
    parser.add_argument("--serial", help="adb serial / ip:port if several devices")
    parser.add_argument("--package", help="override application id to test")
    parser.add_argument("--interval", type=int, default=15,
                        help="seconds between snapshots (default 15, 0 = none)")
    parser.add_argument("--no-restart", action="store_true",
                        help="do not force-stop / relaunch; record current session")
    parser.add_argument("--no-perf", action="store_true", help="skip meminfo polls")
    parser.add_argument("--no-screen", action="store_true", help="skip screencaps")
    parser.add_argument("--no-wake", action="store_true", help="don't wake screen")
    parser.add_argument("--no-clean", action="store_true", help="keep old logs")
    args = parser.parse_args(argv)

    seconds = max(1, parse_duration(args.duration))
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / f"TestAndroid_{ts}"          # raw temp, deleted at end
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    for old_png in SHOTS_DIR.glob("*.png"):           # latest-run only, no buildup
        try:
            old_png.unlink()
        except OSError:
            pass

    print(f"◆ Test Android.py - {seconds}s forensic window")
    print(f"◆ will package into {REPORT_FILE.name} (overwritten) and delete raw dumps")

    serial = pick_device(args.serial)
    if not serial:
        print("✗ no device ready. Fix with:")
        print("    phone → Developer options → Wireless debugging → enable")
        print("    then:  adb connect <phone-ip>:5555    (IP shows on the phone)")
        return 10
    remember_address(serial)

    app_id, gradle_version, gradle_code = read_versions()
    pkg = pick_package(serial, app_id, args.package)
    if not pkg:
        looked = args.package or f"{app_id} / {app_id}.debug"
        print(f"✗ no Cellium package installed on {serial} (looked for {looked})")
        return 11
    launcher = resolve_launcher(serial, pkg)

    release_v = sh(serial, "getprop ro.build.version.release", 10)
    sdk_v = sh(serial, "getprop ro.build.version.sdk", 10)
    installed_version = "?"
    for line_v in sh(serial, f"dumpsys package {pkg}", 25).splitlines():
        mv = re.search(r"versionName=([^\s]+)", line_v)
        if mv:
            installed_version = mv.group(1)
            break
    print(f"◆ device  : {serial}  (Android {release_v} / SDK {sdk_v})")
    print(f"◆ package : {pkg}   installed v{installed_version}")

    if not args.no_clean:
        sh(serial, "logcat -c", 12)
        print("◆ logcat buffers cleared")

    # streams start BEFORE launch so nothing is missed
    out_dir.mkdir(parents=True, exist_ok=True)
    all_stream = LogStream(serial, ["logcat", "-v", "threadtime", "-b", "all"],
                           out_dir / "logcat_all.txt")
    crash_stream = LogStream(serial, ["logcat", "-v", "threadtime", "-b", "crash"],
                             out_dir / "crash_stream.txt")
    all_stream.start()
    crash_stream.start()
    time.sleep(1.0)
    if not all_stream.alive():           # some devices reject -b all
        all_stream.stop()
        all_stream = LogStream(serial,
                               ["logcat", "-v", "threadtime",
                                "-b", "main,system,crash,events"],
                               out_dir / "logcat_all.txt")
        all_stream.start()
        print("! '-b all' rejected → fell back to main,system,crash,events")

    if not args.no_wake:
        sh(serial, "input keyevent KEYCODE_WAKEUP", 10)
        sh(serial, "wm dismiss-keyguard", 10)
        time.sleep(1.0)
    if not args.no_screen:
        screencap(serial, SHOTS_DIR / "00_before.png")

    launch_how = "not-launched"
    if not args.no_restart:
        sh(serial, f"am force-stop {pkg}", 12)
        time.sleep(0.6)
        if not args.no_clean:
            sh(serial, "logcat -c", 12)  # clean logs right around the cold start
        if launcher:
            out_l = sh(serial, f"am start -n {launcher}", 20)
            launch_how = "am start" if out_l.startswith("Starting") else "am FAILED"
        if launch_how != "am start":
            monkey_out = sh(
                serial, f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1", 30)
            launch_how = "monkey" if "Events injected: 1" in monkey_out else "FAILED"
        print(f"◆ launch  : {launch_how}")
    else:
        print("◆ --no-restart: recording current session, no relaunch")

    # wait (≤8s) for the process to appear so the pid timeline is truthful
    first_pid: int | None = None
    for _ in range(16):
        first_pid = pid_of(serial, pkg)
        if first_pid:
            break
        time.sleep(0.5)
    print(f"◆ pid     : {first_pid if first_pid else 'NO PROCESS'}")

    pid_log: list[str] = [f"t+0.0  pid={first_pid or 'DEAD'} (after launch)"]
    pid_died = False
    cur_pid = first_pid
    mem_series: list[str] = []

    start = time.monotonic()
    next_pid_check = start + 2.0
    idx = 1
    try:
        while (now := time.monotonic()) - start < seconds:
            if now >= next_pid_check:
                p_v = pid_of(serial, pkg)
                if p_v and p_v != cur_pid:
                    note = "restart" if cur_pid else "appeared"
                    pid_log.append(
                        f"t+{now - start:6.1f}  pid {cur_pid} → {p_v}  ({note})")
                    cur_pid = p_v
                elif p_v is None and cur_pid is not None:
                    pid_log.append(f"t+{now - start:6.1f}  pid {cur_pid} → DEAD")
                    pid_died = True
                    cur_pid = None
                next_pid_check = now + 2.0
            if args.interval > 0 and (now - start) >= idx * args.interval:
                mem_total = snapshot(serial, pkg, idx, now - start, args)
                if mem_total:
                    mem_series.append(mem_total)
                idx += 1
            time.sleep(0.4)
    except KeyboardInterrupt:
        print("\n• interrupted - packaging partial results")
        pid_log.append("interrupted by user")

    if not args.no_screen:
        screencap(serial, SHOTS_DIR / "99_after.png")

    excerpts = collect_excerpts(serial, pkg)
    ui_texts = ui_dump_texts(serial)

    all_stream.stop()
    crash_stream.stop()

    result = harvest(all_stream.lines, crash_stream.lines)
    pid_now = pid_of(serial, pkg)
    meta = {"ts": ts, "serial": serial, "release": release_v, "sdk": sdk_v,
            "pkg": pkg, "installed_version": installed_version,
            "gradle_version": gradle_version, "gradle_code": gradle_code,
            "launcher": launcher, "interval": args.interval,
            "seconds": seconds, "pid_died": pid_died,
            "pid_summary": f"launched pid={first_pid}, final pid={pid_now}, "
                           f"died={pid_died}"}
    top = top_error_tags(all_stream.lines)
    shot_names = sorted(p.name for p in SHOTS_DIR.glob("*.png"))
    md, rc = render_report(meta, result, pid_log, launch_how, mem_series,
                           excerpts, ui_texts, shot_names, top)
    REPORT_FILE.write_text(md, encoding="utf-8")      # overwrite, never append

    shutil.rmtree(out_dir, ignore_errors=True)        # all raw dumps are gone

    verdict, _ = verdict_of(result, pid_died)
    print("─" * 66)
    print(f"VERDICT: {verdict}")
    print(f"levels : " + " ".join(f"{k}:{result['levels'][k]}"
                                  for k in "VDIWEF"))
    print(f"anomaly lines: {len(result['bad'])}   app E/F: {result['app_errors']}")
    print(f"pid   : {meta['pid_summary']}")
    for ln in result["bad"][:8]:
        print(f"  {ln[:150]}")
    if len(result["bad"]) > 8:
        print(f"  … {len(result['bad']) - 8} more in the report")
    print("─" * 66)
    print(f"✓ report      → {REPORT_FILE}")
    print(f"✓ screenshots → {SHOTS_DIR}")
    print("✓ raw dumps deleted")
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\n• interrupted")
        sys.exit(130)
