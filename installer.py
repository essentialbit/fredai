#!/usr/bin/env python3
"""
FredAI — Autonomous Device Installer
Detects the running device/OS and creates native app shortcuts + icons
on the appropriate surfaces (Desktop, Dock, App Menu, Start Menu, etc.)

Callable standalone:   python3 installer.py
Or via Flask route:    POST /api/install
"""

import os
import sys
import stat
import shutil
import platform
import subprocess
import textwrap
from pathlib import Path
from typing import TypedDict

# ── Base paths (resolved relative to this file so it works after migration) ──
BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
ICONS_DIR = ASSETS_DIR / "icons"
STATIC_ICONS = BASE_DIR / "static" / "icons"


# ── Result type ───────────────────────────────────────────────────────────────

class InstallResult(TypedDict):
    platform: str
    device_type: str
    actions: list[str]
    warnings: list[str]
    instructions: str
    success: bool


# ── Platform detection ────────────────────────────────────────────────────────

def detect_device() -> dict:
    """Return a structured description of the current device."""
    uname = platform.uname()
    sys_platform = sys.platform
    machine = uname.machine.lower()
    node = uname.node

    # OS family
    if sys_platform == "darwin":
        os_family = "macos"
    elif sys_platform.startswith("win"):
        os_family = "windows"
    elif sys_platform.startswith("linux"):
        os_family = "linux"
    else:
        os_family = "unknown"

    # ARM / Raspberry Pi detection
    is_arm = "arm" in machine or "aarch" in machine
    is_pi = is_arm and (
        Path("/proc/device-tree/model").exists()
        or "raspberry" in node.lower()
        or "raspberrypi" in node.lower()
    )
    if is_pi:
        try:
            model_txt = Path("/proc/device-tree/model").read_text(errors="ignore").strip("\x00")
        except Exception:
            model_txt = "Raspberry Pi"
        device_type = "raspberry_pi"
        device_label = model_txt
    elif os_family == "macos":
        # Apple Silicon vs Intel
        device_type = "mac_arm" if machine == "arm64" else "mac_intel"
        device_label = f"Mac ({platform.mac_ver()[0]})"
    elif os_family == "windows":
        device_type = "windows"
        device_label = f"Windows {platform.win32_ver()[0]}"
    elif is_arm and os_family == "linux":
        device_type = "linux_arm"
        device_label = f"Linux ARM ({machine})"
    elif os_family == "linux":
        device_type = "linux"
        device_label = f"Linux ({machine})"
    else:
        device_type = "unknown"
        device_label = uname.system

    # Desktop environment (Linux)
    desktop_env = ""
    if os_family == "linux":
        desktop_env = (
            os.getenv("XDG_CURRENT_DESKTOP")
            or os.getenv("DESKTOP_SESSION")
            or os.getenv("GDMSESSION")
            or ""
        ).upper()

    import psutil
    ram_gb = round(psutil.virtual_memory().total / 1e9, 1)

    return {
        "os_family": os_family,
        "device_type": device_type,
        "device_label": device_label,
        "desktop_env": desktop_env,
        "is_arm": is_arm,
        "is_pi": is_pi,
        "ram_gb": ram_gb,
        "hostname": node,
        "machine": machine,
    }


# ── Icon path resolution ──────────────────────────────────────────────────────

def _best_icon(preference: list[str]) -> str | None:
    """Return the path to the first available icon from the preference list."""
    search_dirs = [ICONS_DIR, STATIC_ICONS, ASSETS_DIR]
    for name in preference:
        for d in search_dirs:
            p = d / name
            if p.exists():
                return str(p)
    return None


def _icon(size: int, ext: str = "png") -> str | None:
    return _best_icon([
        f"icon-{size}.{ext}",
        f"linux-{size}.{ext}",
        f"android-{size}.{ext}",
        f"ios-{size}.{ext}",
        "fredai-icon.svg",
    ])


# ── macOS installer ───────────────────────────────────────────────────────────

def _install_macos(port: int = 8080) -> InstallResult:
    actions: list[str] = []
    warnings: list[str] = []
    url = f"http://localhost:{port}"

    app_path = Path("/Applications/FredAI.app")
    app_contents = app_path / "Contents"
    app_macos = app_contents / "MacOS"
    app_resources = app_contents / "Resources"

    try:
        app_macos.mkdir(parents=True, exist_ok=True)
        app_resources.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Fall back to user Applications
        app_path = Path.home() / "Applications" / "FredAI.app"
        app_contents = app_path / "Contents"
        app_macos = app_contents / "MacOS"
        app_resources = app_contents / "Resources"
        app_macos.mkdir(parents=True, exist_ok=True)
        app_resources.mkdir(parents=True, exist_ok=True)
        warnings.append(f"No /Applications write access — installed to {app_path}")

    # Executable shell script
    exe = app_macos / "fredai"
    exe.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        open "{url}"
    """))
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Info.plist
    (app_contents / "Info.plist").write_text(textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
            "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>CFBundleExecutable</key><string>fredai</string>
            <key>CFBundleIdentifier</key><string>com.essentialbit.fredai</string>
            <key>CFBundleName</key><string>FredAI</string>
            <key>CFBundleDisplayName</key><string>FredAI</string>
            <key>CFBundleVersion</key><string>1.0</string>
            <key>CFBundleShortVersionString</key><string>1.0</string>
            <key>CFBundleIconFile</key><string>AppIcon</string>
            <key>NSHighResolutionCapable</key><true/>
            <key>LSMinimumSystemVersion</key><string>12.0</string>
        </dict>
        </plist>
    """))

    # Icon (.icns preferred, PNG fallback)
    icns = _best_icon(["macos.icns"])
    if icns:
        shutil.copy2(icns, app_resources / "AppIcon.icns")
    else:
        png = _icon(512) or _icon(256)
        if png:
            shutil.copy2(png, app_resources / "AppIcon.png")
    actions.append(f"Created .app bundle: {app_path}")

    # Desktop shortcut — symlink to .app
    desktop = Path.home() / "Desktop" / "FredAI.app"
    try:
        if desktop.is_symlink() or desktop.exists():
            desktop.unlink()
        desktop.symlink_to(app_path)
        actions.append("Created Desktop shortcut")
    except Exception as e:
        warnings.append(f"Desktop shortcut failed: {e}")

    # Dock — add via defaults + restart Dock
    try:
        tile = (
            f'<dict><key>tile-data</key><dict>'
            f'<key>file-data</key><dict>'
            f'<key>_CFURLString</key><string>{app_path}</string>'
            f'<key>_CFURLStringType</key><integer>0</integer>'
            f'</dict></dict></dict>'
        )
        subprocess.run(
            ["defaults", "write", "com.apple.dock", "persistent-apps",
             "-array-add", tile],
            check=True, capture_output=True,
        )
        subprocess.run(["killall", "Dock"], check=True, capture_output=True)
        actions.append("Added to Dock")
    except Exception as e:
        warnings.append(f"Dock pin failed (manual: drag FredAI.app to Dock): {e}")

    return InstallResult(
        platform="macOS",
        device_type="mac",
        actions=actions,
        warnings=warnings,
        instructions=(
            "FredAI is now in /Applications and pinned to your Dock. "
            "Open FredAI from Launchpad or the Desktop shortcut. "
            "The app opens your browser to FredAI running on this machine."
        ),
        success=True,
    )


# ── Windows installer ─────────────────────────────────────────────────────────

def _install_windows(port: int = 8080) -> InstallResult:
    actions: list[str] = []
    warnings: list[str] = []
    url = f"http://localhost:{port}"

    url_content = f"[InternetShortcut]\nURL={url}\nIconFile={_icon(256) or ''}\nIconIndex=0\n"

    # Desktop
    desktop = Path(os.path.expandvars(r"%USERPROFILE%\Desktop\FredAI.url"))
    try:
        desktop.write_text(url_content)
        actions.append(f"Created Desktop shortcut: {desktop}")
    except Exception as e:
        warnings.append(f"Desktop shortcut failed: {e}")

    # Start Menu
    start_menu = Path(os.path.expandvars(
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\FredAI.url"
    ))
    try:
        start_menu.parent.mkdir(parents=True, exist_ok=True)
        start_menu.write_text(url_content)
        actions.append(f"Created Start Menu entry: {start_menu}")
    except Exception as e:
        warnings.append(f"Start Menu shortcut failed: {e}")

    # Pin to Taskbar — not reliably automatable without C#/COM; skip
    warnings.append(
        "Taskbar pin: drag FredAI from Desktop to the Taskbar to pin it."
    )

    return InstallResult(
        platform="Windows",
        device_type="windows",
        actions=actions,
        warnings=warnings,
        instructions=(
            "FredAI shortcuts created on Desktop and Start Menu. "
            "To pin to Taskbar: right-click the Desktop shortcut → "
            "Pin to Taskbar."
        ),
        success=True,
    )


# ── Linux installer ───────────────────────────────────────────────────────────

def _install_linux(device: dict, port: int = 8080) -> InstallResult:
    actions: list[str] = []
    warnings: list[str] = []
    url = f"http://localhost:{port}"

    icon_path = _icon(256) or _icon(128) or _icon(512) or str(ASSETS_DIR / "fredai-icon.svg")

    # Try to start cmd: use systemd if service exists, else direct python
    start_cmd = f"xdg-open {url}"
    if shutil.which("systemctl"):
        start_cmd = f"bash -c 'systemctl --user start fredai 2>/dev/null || true; xdg-open {url}'"

    desktop_entry = textwrap.dedent(f"""\
        [Desktop Entry]
        Version=1.0
        Name=FredAI
        GenericName=Financial Intelligence
        Comment=AI-powered financial signals and portfolio tracking
        Exec={start_cmd}
        Icon={icon_path}
        Terminal=false
        Type=Application
        Categories=Finance;Office;
        StartupWMClass=FredAI
        Keywords=finance;stocks;trading;AI;portfolio;
    """)

    # App Menu (~/.local/share/applications)
    apps_dir = Path.home() / ".local" / "share" / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    app_entry = apps_dir / "fredai.desktop"
    app_entry.write_text(desktop_entry)
    app_entry.chmod(0o644)
    actions.append(f"Created app menu entry: {app_entry}")

    # Refresh desktop database
    try:
        subprocess.run(
            ["update-desktop-database", str(apps_dir)],
            check=False, capture_output=True,
        )
    except Exception:
        pass

    # Desktop shortcut
    desktop = Path.home() / "Desktop" / "fredai.desktop"
    try:
        if desktop.parent.exists():
            shutil.copy2(app_entry, desktop)
            desktop.chmod(0o755)
            # Mark trusted (GNOME / Nautilus)
            try:
                subprocess.run(
                    ["gio", "set", str(desktop), "metadata::trusted", "true"],
                    check=False, capture_output=True,
                )
            except Exception:
                pass
            actions.append(f"Created Desktop shortcut: {desktop}")
        else:
            warnings.append("No ~/Desktop directory — skipping Desktop shortcut")
    except Exception as e:
        warnings.append(f"Desktop shortcut failed: {e}")

    # Copy icon to user icon theme
    icon_theme_dir = Path.home() / ".local" / "share" / "icons" / "hicolor"
    for size, name in [(256, "256x256"), (128, "128x128"), (512, "512x512")]:
        src = _icon(size)
        if src:
            dest_dir = icon_theme_dir / name / "apps"
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_dir / "fredai.png")
    try:
        subprocess.run(
            ["gtk-update-icon-cache", "-f", str(icon_theme_dir)],
            check=False, capture_output=True,
        )
    except Exception:
        pass
    actions.append("Installed icons to user icon theme")

    device_type = device["device_type"]
    instr = "FredAI is now in your application menu and on the Desktop. "
    if "gnome" in device.get("desktop_env", "").lower():
        instr += "Search for 'FredAI' in Activities or the Applications grid."
    elif "kde" in device.get("desktop_env", "").lower():
        instr += "Find FredAI in the KDE application launcher under Finance."
    elif device["is_pi"]:
        instr += "Find FredAI in the Raspberry Pi application menu under Office/Finance."
    else:
        instr += "Find FredAI in your system application menu under Finance."

    return InstallResult(
        platform=f"Linux ({device.get('desktop_env') or 'desktop'})",
        device_type=device_type,
        actions=actions,
        warnings=warnings,
        instructions=instr,
        success=True,
    )


# ── PWA instructions (mobile / browser-only) ──────────────────────────────────

def _pwa_instructions(device: dict, port: int = 8080) -> InstallResult:
    dt = device["device_type"]
    if "ios" in dt or dt == "iphone" or dt == "ipad":
        instr = (
            "On iPhone/iPad: open FredAI in Safari → tap the Share button (box with arrow) "
            "→ 'Add to Home Screen' → tap Add. "
            "FredAI will appear as an app icon on your home screen and dock."
        )
        platform_name = "iOS"
    else:
        instr = (
            "On Android: open FredAI in Chrome → tap the 3-dot menu → "
            "'Add to Home screen' (or 'Install app' if prompted). "
            "FredAI will appear as an icon on your home screen."
        )
        platform_name = "Android"
    return InstallResult(
        platform=platform_name,
        device_type=dt,
        actions=[],
        warnings=[],
        instructions=instr,
        success=True,
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def install(port: int = 8080) -> InstallResult:
    """Detect device and install the appropriate shortcut/icon set."""
    device = detect_device()
    os_family = device["os_family"]

    if os_family == "macos":
        return _install_macos(port)
    elif os_family == "windows":
        return _install_windows(port)
    elif os_family == "linux":
        return _install_linux(device, port)
    else:
        return InstallResult(
            platform=os_family,
            device_type=device["device_type"],
            actions=[],
            warnings=["Unsupported platform — use browser 'Add to Home Screen'"],
            instructions=(
                "Open FredAI in your browser and use 'Add to Home Screen' "
                "or 'Install App' from the browser menu."
            ),
            success=False,
        )


# ── Standalone execution ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    result = install(port)
    print(json.dumps(result, indent=2))
    if result["actions"]:
        print("\nInstalled:")
        for a in result["actions"]:
            print(f"  + {a}")
    if result["warnings"]:
        print("\nWarnings:")
        for w in result["warnings"]:
            print(f"  ! {w}")
    print(f"\n{result['instructions']}")
