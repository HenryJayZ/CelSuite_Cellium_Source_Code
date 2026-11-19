#!/usr/bin/env python3
"""Cellium bundle exporter - regenerates the 5 share bundles in the project root.

Usage:
    /home/henry/Documents/Projects/Python/venv/bin/python tools/bundle_export.py

Produces exactly 5 files (for the 5-upload limit), all verified byte-for-byte:
    Android_bundle.md, cellium_ui_bundle.md, cellium_core_bundle.md,
    tools_bundle.md, junk_bundle.md

Rules: no size caps · secrets redacted · __pycache__/.git/_backups/.kotlin ignored ·
avatar Anim JSONs summarized · binaries listed only.
"""
import re
import sys
from pathlib import Path
from collections import Counter
from datetime import date

ROOT = Path(__file__).resolve().parent.parent
IGNORE_DIRS = {'.git', '__pycache__', '.venv', 'venv', 'build', 'dist', '_backups'}
SECRET_FILES = {'cerebrium_settings.json', 'cerebrium_sessions.json', 'celstudio_app.log'}
SECRET_PAT = re.compile(r'(keystore|\.jks$|token|credential|secret|password)', re.I)
TEXT_EXTS = {'.py', '.json', '.kv', '.qss', '.toml', '.yaml', '.yml', '.md', '.txt', '.sh', '.cfg', '.ini',
             '.svg', '.spec', '.kt', '.java', '.xml', '.gradle', '.kts', '.aidl', '.properties', '.pro',
             '.gitignore', '.gitattributes', '.gitkeep', '.html', '.css', '.csv', '.np', '.bak'}
LANG = {'.py': 'python', '.json': 'json', '.kv': 'python', '.qss': 'css', '.toml': 'toml', '.yaml': 'yaml',
        '.yml': 'yaml', '.md': 'markdown', '.txt': 'text', '.sh': 'bash', '.cfg': 'ini', '.ini': 'ini',
        '.svg': 'svg', '.spec': 'python', '.kt': 'kotlin', '.java': 'java', '.xml': 'xml',
        '.gradle': 'groovy', '.kts': 'groovy', '.aidl': 'java', '.properties': 'properties',
        '.pro': 'properties', '.html': 'html', '.css': 'css', '.csv': 'csv', '.bak': 'python'}


def ignored(p):
    for part in p.parts:
        if part in IGNORE_DIRS:
            return True
        if part.startswith('.'):
            return True
    return False


def is_secret(name):
    return name in SECRET_FILES or SECRET_PAT.search(name) is not None


def write_section(out, rel, fp):
    if 'Anim' in rel.parts:
        return 'animskip'
    if is_secret(fp.name):
        out.write(f"### `{rel}`\n\n> ⚠️ REDACTED - secret/private file removed ({fp.stat().st_size:,} bytes).\n\n---\n\n")
        return 'secret'
    e = fp.suffix.lower()
    if e in TEXT_EXTS:
        try:
            content = fp.read_text(encoding='utf-8')
        except Exception as ex:
            out.write(f"### `{rel}` (READ FAILED: {ex})\n\n---\n\n")
            return 'fail'
        fence = '```' if '```' not in content else '````'
        out.write(f"### `{rel}`\n\n{fence}{LANG.get(e, e.lstrip('.'))}\n")
        out.write(content)
        if not content.endswith('\n'):
            out.write('\n')
        out.write(f"{fence}\n\n---\n\n")
        return 'dump'
    out.write(f"- Asset/Binary: `{rel}` ({fp.stat().st_size:,} bytes)\n")
    return 'bin'


def bundle(title, out_name, files, note=""):
    cnt = Counter()
    out_path = ROOT / out_name
    with open(out_path, 'w', encoding='utf-8') as out:
        out.write(f"# Bundle for: {title}\n\n")
        out.write(f"_Repacked {date.today().isoformat()} · NO size caps · secrets redacted · "
                  "`__pycache__`/`.git`/`_backups`/`.kotlin` ignored · Anim JSONs summarized · binaries listed only_\n")
        if note:
            out.write(f"_{note}_\n")
        out.write("\n---\n\n")
        for fp in files:
            cnt[write_section(out, fp.relative_to(ROOT), fp)] += 1
        anim = [f for f in files if 'Anim' in f.relative_to(ROOT).parts]
        if anim:
            per = Counter()
            perb = Counter()
            for f in anim:
                parts = f.relative_to(ROOT).parts
                gi = parts.index('Anim')
                g = parts[gi + 1] if gi + 1 < len(parts) else '?'
                per[g] += 1
                perb[g] += f.stat().st_size
            out.write("\n## Avatar Anim payload (summarized - never dumped)\n\n| Style dir | JSON files | Bytes |\n|---|---|---|\n")
            for g in sorted(per):
                out.write(f"| {g} | {per[g]} | {perb[g]:,} |\n")
            out.write("\n> Per-expression dot-matrix JSONs summarized. Use `AvatarLibrary.load_gender()` incremental loading.\n\n---\n\n")
            cnt['anim'] = sum(per.values())
    return out_path, cnt


def collect(*subs, exclude_avatar=False):
    out = []
    for s in subs:
        p = ROOT / s if isinstance(s, str) else s
        if not p.exists():
            print(f"  !! MISSING: {p}")
            continue
        for f in (p.rglob('*') if p.is_dir() else [p]):
            if not f.is_file() or ignored(f.relative_to(ROOT)):
                continue
            if exclude_avatar and 'avatar' in f.relative_to(ROOT).parts:
                continue
            out.append(f)
    return sorted(out, key=lambda x: str(x).lower())


def extract_sections(text):
    out = []
    lines = text.split('\n')
    n = len(lines)
    i = 0
    while i < n:
        m = re.match(r'^### `([^`]+)`\s*$', lines[i])
        if not m:
            i += 1
            continue
        path = m.group(1)
        j = i + 1
        while j < n and lines[j].strip() == '':
            j += 1
        if j < n and lines[j].lstrip().startswith('> ⚠️ REDACTED'):
            i = j
            continue
        if j >= n or not lines[j].startswith('```'):
            i = j
            continue
        fence = lines[j]
        flen = len(fence) - len(fence.lstrip('`'))
        k = j + 1
        buf = []
        while k < n:
            if lines[k].startswith('`' * flen) and (len(lines[k]) - len(lines[k].lstrip('`'))) >= flen and lines[k].strip('`').strip() == '':
                break
            buf.append(lines[k])
            k += 1
        if k >= n:
            i = k
            continue
        out.append((path, '\n'.join(buf)))
        i = k + 1
    return out


def main():
    results = {}
    and_all = collect('Android')
    results['Android_bundle.md'] = bundle(
        "Android/ (Kotlin app - code + assets)", "Android_bundle.md",
        [f for f in and_all], "Kotlin source + assets/binaries listed (never dumped).")

    results['cellium_ui_bundle.md'] = bundle(
        "cellium/ui/ - window, chat, live, settings, widgets, avatar + shared assets", "cellium_ui_bundle.md",
        collect('cellium/ui', 'cellium/assets', exclude_avatar=False),
        "All of ui/ including avatar/ (Anim summarized), plus cellium/assets/.")

    results['cellium_core_bundle.md'] = bundle(
        "cellium/ core engine + audio + AI workers", "cellium_core_bundle.md",
        collect('cellium/core', 'cellium/services', 'cellium/__init__.py', 'cellium/main.py'),
        "Headless engine (Qt-free), audio/STT/TTS/wake, AI workers + llama. Secrets redacted.")

    results['tools_bundle.md'] = bundle(
        "tools/ + tests/ (audit, regression, screenshots)", "tools_bundle.md",
        collect('tools', 'tests'),
        "audit.py, regression.py (85 checks), test screenshots.")

    results['junk_bundle.md'] = bundle(
        "project-root files (junk, docs, scripts)", "junk_bundle.md",
        sorted([p for p in ROOT.iterdir() if p.is_file() and not p.name.endswith('_bundle.md')],
               key=lambda p: p.name.lower()),
        "Includes REFACTOR_MAP.md, README, AGENTS, specs, scripts, etc.")

    print("== 5 bundles ==")
    for k, (p, c) in sorted(results.items()):
        print(f"  {p.name:26s} {p.stat().st_size:>10,}  {dict(c)}")

    print("\n== verify (byte-compared to disk) ==")
    tok = tbad = 0
    for k, (p, c) in sorted(results.items()):
        txt = p.read_text(encoding='utf-8')
        ok = bad = 0
        for path_str, code in extract_sections(txt):
            fp = ROOT / path_str
            if fp.exists() and fp.read_text(encoding='utf-8').rstrip('\n') == code.rstrip('\n'):
                ok += 1
            else:
                bad += 1
                print(f"  MISMATCH/MISSING: {p.name} -> {path_str}")
        tok += ok
        tbad += bad
        print(f"  {p.name:26s} OK={ok:>4} BAD={bad} redacted={txt.count('⚠️ REDACTED')}")
    print(f"\nTOTAL OK={tok} BAD={tbad}  ->  {'ALL CLEAN' if tbad == 0 else 'ISSUES'}")

    cov_txt = set()
    cov_bin = set()
    cov_red = set()
    for k in ('Android_bundle.md', 'cellium_ui_bundle.md', 'cellium_core_bundle.md'):
        txt = results[k][0].read_text(encoding='utf-8')
        for path_str, _ in extract_sections(txt):
            cov_txt.add(path_str)
        for line in txt.splitlines():
            if line.startswith('- Asset/Binary: `'):
                cov_bin.add(line.split('`')[1])
        for m in re.finditer(r'(?m)^### `([^`]+)`\n\n> ⚠️ REDACTED', txt):
            cov_red.add(m.group(1))
    miss = []
    for base in ('cellium', 'Android'):
        for f in collect(base):
            rel = str(f.relative_to(ROOT))
            if 'Anim' in f.relative_to(ROOT).parts:
                continue
            if rel in cov_txt or rel in cov_bin or rel in cov_red:
                continue
            miss.append(rel)
    print(f"== coverage: {len(miss)} uncovered (cellium+Android) ==")
    for m in miss[:15]:
        print("   ", m)
    return 1 if tbad else 0


if __name__ == '__main__':
    sys.exit(main())
