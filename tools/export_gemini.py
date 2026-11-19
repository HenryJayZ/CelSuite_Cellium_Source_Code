#!/usr/bin/env python3
"""
Universal Cellium → Gemini export script (auto-discovers Python files).

Usage:
    python export_gemini.py              # full export (9 .md files)
    python export_gemini.py --clean      # delete existing gemini_export/ first
    python export_gemini.py --list       # show what would be included

Auto-groups .py files by their package directory. JSON configs are explicit
(because only specific ones should be shared). Animation JSONs in Anim/ are
always excluded. Secrets (settings, sessions) always excluded.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "gemini_export"

# ─── EXCLUSIONS ──────────────────────────────────────────────────────────────
EXCLUDE_DIRS = {
    "_legacy", "Android", "dist", "__pycache__", ".git", "build",
    "opencodetmp", "_patch_backups", "delete", "ColabVM", "bin",
    "Apps", "Games", "Images", "Music", "Pictures", "Videos",
    "Wallpapers", "node_modules", "assignment_venv", "my_keybinder_venv",
}
EXCLUDE_FILES = {
    "banner.webp", "banner_footer.webp", "icon.webp", "celmoji.py",
    "build_nuitka.py", "RunCelliumApp.sh", "requirements.txt",
    "CHANGELOG.md", "PROGRESS.md", "README.md", "MEMORY.md",
    "DECISIONS.md", "ARCHIVE_AUDIT.md", "CELAS_LIVE_MODE_SPEC.md",
    "Full Android Conversion Plan.md", "Cellium Personas.md",
    "REFACTOR_MAP.md", "AGENTS Persona.md", "0_build.txt",
    "GUI Get's broken when you run a command block it gives you.png",
    "packaging_final.log", "packaging_log.txt",
    "touchpad-ghost-killer.sh", "touchpad-toggle-tap.sh",
    "uca7.xml", "opencode_auto_send.log", "opencode_auto_send.py",
    "OpenCode_History_Display.py", "OpenCode_History_Viewer_Modern.py",
    "opencode_history_viewer.py", "OpenCode_History_Viewer.py",
    "update_github_token_gui.py", "start_new_wallpaper.sh",
    "start_wallpaper.sh", "gemmy_linux_optimizer.sh",
    "isomaster_1.3.13-1+b2_amd64.deb", "packages.microsoft.gpg",
    "packages-microsoft-prod.deb", "package.json", "package-lock.json",
    "oblivion.spec", "scary_logs.txt", "last_ip.txt", "manual_apps.txt",
    "photorec.se2", "photorec.ses", "testdisk.log", "shared_drive.img",
    "andronix-installer.sh", "andronix-setup.sh", "LICENSE",
}

# Never export these JSONs (secrets/sessions/animations)
EXCLUDE_JSON = {
    "cellium/core/cerebrium_settings.json",
    "cellium/core/cerebrium_sessions.json",
}

# JSON configs TO include (explicit - only these specific ones)
INCLUDE_JSON = {
    "cellium/core/cerebrium_analytics.json",
    "cellium/core/cerebrium_presets.json",
    "cellium/core/cerebrium_memory_presets.json",
    "cellium/ui/settings/cerebrium_presets.json",
    "cellium/ui/settings/cerebrium_memory_presets.json",
}

# Extra markdown docs to append to the last group
EXTRA_MD = [
    "AGENTS.md",
]


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    if path.name in EXCLUDE_FILES:
        return True
    return False


def discover_python_groups() -> dict:
    """
    Walk cellium/ and tools/, group .py files by their parent package directory.
    Returns {markdown_filename: [relative_paths]}.
    """
    groups: dict[str, list[str]] = {}

    # Directories to scan for .py files (relative to ROOT)
    scan_dirs = [
        "cellium/core",
        "cellium/services",
        "cellium/ui/main_window.py",  # special: single file
        "cellium/ui/chat",
        "cellium/ui/settings",
        "cellium/ui/avatar",
        "cellium/ui/live",
        "cellium/ui/widgets",
        "tools",
    ]

    for entry in scan_dirs:
        path = ROOT / entry
        if not path.exists():
            continue

        if path.is_file():  # single file (main_window.py)
            rel = path.relative_to(ROOT)
            if should_skip(path):
                continue
            group_key = "03_ui_main_window.md"
            groups.setdefault(group_key, []).append(str(rel))
            continue

        # Directory: collect all .py files recursively
        py_files = sorted(path.rglob("*.py"))
        if not py_files:
            continue

        # Determine group name from directory structure
        rel_dir = path.relative_to(ROOT)
        parts = list(rel_dir.parts)

        # Map directory → output markdown file
        if parts[:2] == ["cellium", "core"]:
            group_key = "01_core_config_and_utils.md"
        elif parts[:2] == ["cellium", "services"]:
            group_key = "02_services_ai_audio.md"
        elif parts[:2] == ["cellium", "ui"]:
            if len(parts) >= 3:
                sub = parts[2]
                if sub == "chat":
                    group_key = "04_ui_chat_system.md"
                elif sub == "settings":
                    group_key = "05_ui_settings_dialog.md"
                elif sub == "avatar":
                    group_key = "06_ui_avatar_subsystem.md"
                elif sub == "live":
                    group_key = "07_ui_live_mode.md"
                elif sub == "widgets":
                    group_key = "08_ui_widgets.md"
                else:
                    group_key = f"08_ui_widgets.md"  # fallback
            else:
                group_key = "08_ui_widgets.md"
        elif parts[0] == "tools":
            group_key = "09_tests_tools_and_project_docs.md"
        else:
            group_key = "09_tests_tools_and_project_docs.md"

        for py_file in py_files:
            if should_skip(py_file):
                continue
            rel = py_file.relative_to(ROOT)
            groups.setdefault(group_key, []).append(str(rel))

    # Ensure consistent ordering within each group
    for k in groups:
        groups[k].sort()

    return groups


def write_md(md_path: Path, title: str, py_files: list, json_files: list, extra_md: list = None):
    with md_path.open("w", encoding="utf-8") as md:
        md.write(f"# {title}\n\n")
        md.write(f"*Auto-exported from Cellium for Gemini review*\n\n---\n\n")

        # Python files
        for rel in py_files:
            abs_path = ROOT / rel
            if not abs_path.exists():
                md.write(f"## `{rel}` - **NOT FOUND**\n\n---\n\n")
                continue
            if should_skip(abs_path):
                md.write(f"## `{rel}` - **EXCLUDED**\n\n---\n\n")
                continue
            try:
                content = abs_path.read_text(encoding="utf-8")
            except Exception as e:
                content = f"<<ERROR READING: {e}>>"
            md.write(f"## `{rel}`\n\n```python\n{content}\n```\n\n---\n\n")

        # JSON files (pretty-printed)
        for rel in json_files:
            abs_path = ROOT / rel
            if not abs_path.exists():
                md.write(f"## `{rel}` - **NOT FOUND**\n\n---\n\n")
                continue
            if str(abs_path.relative_to(ROOT)) in EXCLUDE_JSON:
                md.write(f"## `{rel}` - **EXCLUDED (secrets/sessions)**\n\n---\n\n")
                continue
            try:
                parsed = json.loads(abs_path.read_text(encoding="utf-8"))
                pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            except Exception as e:
                pretty = f"<<ERROR READING: {e}>>"
            md.write(f"## `{rel}`\n\n```json\n{pretty}\n```\n\n---\n\n")

        # Extra markdown files (AGENTS.md, etc.)
        for rel in extra_md or []:
            abs_path = ROOT / rel
            if not abs_path.exists():
                md.write(f"## `{rel}` - **NOT FOUND**\n\n---\n\n")
                continue
            try:
                content = abs_path.read_text(encoding="utf-8")
            except Exception as e:
                content = f"<<ERROR READING: {e}>>"
            md.write(f"## `{rel}`\n\n```markdown\n{content}\n```\n\n---\n\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Export Cellium project for Gemini (auto-discovers .py files)")
    parser.add_argument("--clean", action="store_true", help="Delete gemini_export/ first")
    parser.add_argument("--list", action="store_true", help="List files that would be included")
    args = parser.parse_args()

    if args.clean and OUT.exists():
        import shutil
        shutil.rmtree(OUT)
        print(f"Cleaned {OUT}")

    # Auto-discover Python files
    py_groups = discover_python_groups()

    # Attach explicit JSON files to the right groups
    json_by_group = {
        "01_core_config_and_utils.md": [
            "cellium/core/cerebrium_analytics.json",
            "cellium/core/cerebrium_presets.json",
            "cellium/core/cerebrium_memory_presets.json",
        ],
        "05_ui_settings_dialog.md": [
            "cellium/ui/settings/cerebrium_presets.json",
            "cellium/ui/settings/cerebrium_memory_presets.json",
        ],
    }

    if args.list:
        print("Files that would be exported (auto-discovered):")
        for md_name in sorted(py_groups.keys()):
            print(f"\n  {md_name}")
            for f in py_groups[md_name]:
                p = ROOT / f
                status = "✓" if p.exists() and not should_skip(p) else "✗"
                print(f"    {status} {f}")
            for f in json_by_group.get(md_name, []):
                p = ROOT / f
                status = "✓" if p.exists() and str(p.relative_to(ROOT)) not in EXCLUDE_JSON else "✗"
                print(f"    {status} {f} (json)")
        for f in EXTRA_MD:
            p = ROOT / f
            status = "✓" if p.exists() else "✗"
            print(f"    {status} {f} (md) -> 09_tests_tools_and_project_docs.md")
        return

    OUT.mkdir(exist_ok=True)

    # Write each group
    for md_name in sorted(py_groups.keys()):
        title = md_name.replace(".md", "").replace("_", " ").title()
        extra = EXTRA_MD if md_name == "09_tests_tools_and_project_docs.md" else None
        write_md(
            OUT / md_name,
            title,
            py_groups[md_name],
            json_by_group.get(md_name, []),
            extra,
        )
        size = (OUT / md_name).stat().st_size / 1024
        print(f"  {md_name}: {size:.1f} KB")

    total = sum((OUT / f).stat().st_size for f in OUT.glob("*.md")) / 1024
    print(f"\n✅ Done! {len(list(OUT.glob('*.md')))} files, {total:.1f} KB total in {OUT}")


if __name__ == "__main__":
    main()