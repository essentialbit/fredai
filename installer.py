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

# Bump whenever a generator function's launcher-script content changes in a way
# that existing installs should pick up (e.g. the check-if-running/auto-start
# logic added here) — see needs_install().
# v3: launcher scripts no longer hardcode the port. They resolve it fresh on
# every launch from data/.runtime_port.json (written by main.py's dynamic
# find_free_port() at startup), so a shortcut created today keeps working
# after the server gets reassigned to a different port on some future run.
INSTALLER_VERSION = "3"
RUNTIME_PORT_FILE_NAME = "data/.runtime_port.json"


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

    # Executable shell script — resolves the live port fresh on every launch
    # instead of trusting the port this shortcut happened to be created for.
    exe = app_macos / "fredai"
    exe.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        # FREDAI_INSTALLER_VERSION={INSTALLER_VERSION}
        cd "{BASE_DIR}"
        PORT_FILE="{BASE_DIR}/{RUNTIME_PORT_FILE_NAME}"
        get_port() {{
            python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['port'])" "$PORT_FILE" 2>/dev/null
        }}
        LIVE_PORT="$(get_port)"
        if [ -z "$LIVE_PORT" ] || ! nc -z 127.0.0.1 "$LIVE_PORT" >/dev/null 2>&1; then
            ./venv/bin/python3 main.py >/dev/null 2>&1 &
            for i in $(seq 1 30); do
                sleep 1
                LIVE_PORT="$(get_port)"
                [ -n "$LIVE_PORT" ] && nc -z 127.0.0.1 "$LIVE_PORT" >/dev/null 2>&1 && break
            done
        fi
        open "http://localhost:${{LIVE_PORT:-{port}}}"
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

    startup_script = BASE_DIR / "FredAI-Start.bat"
    icon_path = _icon(256) or str(ICONS_DIR / "windows-256.ico")
    port_file = BASE_DIR / RUNTIME_PORT_FILE_NAME

    try:
        # Write FredAI-Start.bat — resolves the live port fresh on every
        # launch from data/.runtime_port.json instead of the port this
        # shortcut happened to be created for.
        startup_script.write_text(textwrap.dedent(f"""\
            @echo off
            setlocal enabledelayedexpansion
            rem FREDAI_INSTALLER_VERSION={INSTALLER_VERSION}
            cd /d "{BASE_DIR}"
            set "PORT_FILE={port_file}"
            set "PYEXE=venv\\Scripts\\python.exe"
            for /f "usebackq delims=" %%P in (`"%PYEXE%" -c "import json;print(json.load(open(r'%PORT_FILE%'))['port'])" 2^>nul`) do set "LIVE_PORT=%%P"
            if not defined LIVE_PORT set "LIVE_PORT={port}"
            netstat -ano | findstr LISTENING | findstr :%LIVE_PORT% >nul
            if errorlevel 1 (
                start "" "%PYEXE%" main.py
                for /l %%i in (1,1,20) do (
                    timeout /t 1 >nul
                    set "LIVE_PORT="
                    for /f "usebackq delims=" %%P in (`"%PYEXE%" -c "import json;print(json.load(open(r'%PORT_FILE%'))['port'])" 2^>nul`) do set "LIVE_PORT=%%P"
                    if defined LIVE_PORT (
                        netstat -ano | findstr LISTENING | findstr :!LIVE_PORT! >nul && goto :ready
                    )
                )
                :ready
            )
            start "" "http://localhost:!LIVE_PORT!"
        """))
        actions.append(f"Created/updated startup script: {startup_script}")
    except Exception as e:
        warnings.append(f"Startup script failed: {e}")

    # Desktop
    desktop_lnk = Path(os.path.expandvars(r"%USERPROFILE%\Desktop\FredAI.lnk"))
    # Start Menu
    start_menu_lnk = Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\FredAI.lnk"))

    try:
        ps_cmd = f"""
        $wsh = New-Object -ComObject WScript.Shell
        
        # Desktop
        $s = $wsh.CreateShortcut('{desktop_lnk}')
        $s.TargetPath = '{startup_script}'
        $s.WorkingDirectory = '{BASE_DIR}'
        $s.Description = 'FredAI Financial Intelligence'
        if (Test-Path '{icon_path}') {{ $s.IconLocation = '{icon_path}' }}
        $s.Save()
        
        # Start Menu
        $s2 = $wsh.CreateShortcut('{start_menu_lnk}')
        $s2.TargetPath = '{startup_script}'
        $s2.WorkingDirectory = '{BASE_DIR}'
        $s2.Description = 'FredAI Financial Intelligence'
        if (Test-Path '{icon_path}') {{ $s2.IconLocation = '{icon_path}' }}
        $s2.Save()
        """
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], check=True)
        actions.append(f"Created Desktop shortcut: {desktop_lnk}")
        actions.append(f"Created Start Menu entry: {start_menu_lnk}")
    except Exception as e:
        warnings.append(f"PowerShell shortcut creation failed: {e}")

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

    icon_path = _icon(256) or _icon(128) or _icon(512) or str(ASSETS_DIR / "fredai-icon.svg")

    launcher_path = BASE_DIR / "fredai-launcher.sh"
    try:
        # Resolves the live port fresh on every launch from
        # data/.runtime_port.json instead of the port this shortcut happened
        # to be created for.
        launcher_path.write_text(textwrap.dedent(f"""\
            #!/bin/bash
            # FREDAI_INSTALLER_VERSION={INSTALLER_VERSION}
            cd "{BASE_DIR}"
            PORT_FILE="{BASE_DIR}/{RUNTIME_PORT_FILE_NAME}"
            get_port() {{
                python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['port'])" "$PORT_FILE" 2>/dev/null
            }}
            LIVE_PORT="$(get_port)"
            if [ -z "$LIVE_PORT" ] || ! nc -z 127.0.0.1 "$LIVE_PORT" >/dev/null 2>&1; then
                ./venv/bin/python3 main.py >/dev/null 2>&1 &
                for i in $(seq 1 30); do
                    sleep 1
                    LIVE_PORT="$(get_port)"
                    [ -n "$LIVE_PORT" ] && nc -z 127.0.0.1 "$LIVE_PORT" >/dev/null 2>&1 && break
                done
            fi
            xdg-open "http://localhost:${{LIVE_PORT:-{port}}}"
        """))
        launcher_path.chmod(launcher_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        actions.append(f"Created Linux launcher script: {launcher_path}")
    except Exception as e:
        warnings.append(f"Linux launcher script failed: {e}")

    start_cmd = str(launcher_path)

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


# ── Install-state checks ──────────────────────────────────────────────────────

def _embedded_version(script_path: Path) -> str | None:
    """Read back the FREDAI_INSTALLER_VERSION marker embedded in a generated launcher script."""
    try:
        content = script_path.read_text()
    except Exception:
        return None
    for line in content.splitlines():
        if "FREDAI_INSTALLER_VERSION=" in line:
            return line.split("FREDAI_INSTALLER_VERSION=", 1)[1].strip()
    return None


def is_installed() -> bool:
    """Return True if FredAI shortcuts exist on disk for this OS (existence only, not version)."""
    import sys as _sys
    p = _sys.platform
    if p == "darwin":
        return (
            Path("/Applications/FredAI.app/Contents/MacOS/fredai").exists()
            or (Path.home() / "Applications/FredAI.app/Contents/MacOS/fredai").exists()
        )
    elif p.startswith("win"):
        return (BASE_DIR / "FredAI-Start.bat").exists()
    elif p.startswith("linux"):
        return (Path.home() / ".local/share/applications/fredai.desktop").exists()
    return False


def needs_install(force: bool = False) -> bool:
    """Return True if shortcuts are missing OR were generated by an older installer version.

    Existence-only checks (the old is_installed()) meant any improvement to the
    generator logic silently never reached users who installed before that change —
    e.g. the check-if-running/auto-start logic added in version 2 never reached
    anyone who installed under version 1's launcher scripts.
    """
    if force:
        return True
    import sys as _sys
    p = _sys.platform
    if p == "darwin":
        for candidate in (
            Path("/Applications/FredAI.app/Contents/MacOS/fredai"),
            Path.home() / "Applications/FredAI.app/Contents/MacOS/fredai",
        ):
            if candidate.exists():
                return _embedded_version(candidate) != INSTALLER_VERSION
        return True
    elif p.startswith("win"):
        script = BASE_DIR / "FredAI-Start.bat"
        if not script.exists():
            return True
        return _embedded_version(script) != INSTALLER_VERSION
    elif p.startswith("linux"):
        script = BASE_DIR / "fredai-launcher.sh"
        if not script.exists():
            return True
        return _embedded_version(script) != INSTALLER_VERSION
    return True


# ── Main entry point ──────────────────────────────────────────────────────────

def install(port: int = 8080, force: bool = False) -> InstallResult:
    """Detect device and install the appropriate shortcut/icon set.

    Idempotent: skips if all shortcuts are already in place unless force=True.
    """
    device = detect_device()
    os_family = device["os_family"]

    if not needs_install(force=force):
        return InstallResult(
            platform=os_family,
            device_type=device["device_type"],
            actions=[],
            warnings=[],
            instructions="FredAI shortcuts already installed and up to date.",
            success=True,
        )

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
