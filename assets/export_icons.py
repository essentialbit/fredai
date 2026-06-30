#!/usr/bin/env python3
"""
Export FredAI SVG icons to all required platform formats.

Requires: pip install cairosvg pillow
On macOS: brew install cairo

Outputs:
  icons/
    favicon.ico               (16,32,48,64px — browser)
    icon-16.png .. icon-512.png  (web / PWA)
    icon-1024.png             (macOS App Store)
    macos.icns                (macOS Dock / Finder)
    windows-256.ico           (Windows taskbar / Start Menu / desktop)
    windows-tile-150.png      (Windows Live Tile 150x150)
    windows-tile-310.png      (Windows Live Tile 310x310)
    ios-60.png                (iPhone home screen @2x)
    ios-87.png                (iPhone home screen @3x)
    ios-120.png               (iPhone home screen @2x Retina)
    ios-180.png               (iPhone home screen @3x Retina)
    ios-1024.png              (App Store)
    android-48.png            (mdpi)
    android-72.png            (hdpi)
    android-96.png            (xhdpi)
    android-144.png           (xxhdpi)
    android-192.png           (xxxhdpi)
    android-512.png           (Play Store)
    linux-128.png             (Desktop / app menu)
    linux-256.png             (Desktop / app menu)
    notification-20.png       (notification badge)
    notification-40.png       (notification badge @2x)
"""

import os
import struct
import zlib
from pathlib import Path

ASSETS_DIR = Path(__file__).parent
ICONS_DIR = ASSETS_DIR / "icons"
ICONS_DIR.mkdir(exist_ok=True)

ICON_SVG = ASSETS_DIR / "fredai-icon.svg"
TILE_SVG = ASSETS_DIR / "fredai-windows-tile.svg"
NOTIF_SVG = ASSETS_DIR / "fredai-notification.svg"
FAVICON_SVG = ASSETS_DIR / "fredai-favicon.svg"


def export_with_cairosvg():
    """Primary export method using cairosvg."""
    import cairosvg
    from PIL import Image
    import io

    def svg_to_png(svg_path: Path, size: int, output: Path):
        cairosvg.svg2png(
            url=str(svg_path),
            write_to=str(output),
            output_width=size,
            output_height=size,
        )
        print(f"  ✓ {output.name} ({size}x{size})")

    def svg_to_png_bytes(svg_path: Path, size: int) -> bytes:
        return cairosvg.svg2png(url=str(svg_path), output_width=size, output_height=size)

    # ── Web / PWA ────────────────────────────────────────────────
    for sz in [16, 32, 48, 64, 128, 192, 256, 512, 1024]:
        svg_to_png(ICON_SVG, sz, ICONS_DIR / f"icon-{sz}.png")

    # ── Favicon .ico (multi-size) ─────────────────────────────────
    favicon_sizes = [16, 32, 48, 64]
    imgs = []
    for sz in favicon_sizes:
        data = svg_to_png_bytes(FAVICON_SVG, sz)
        imgs.append(Image.open(io.BytesIO(data)).convert("RGBA"))
    imgs[0].save(
        str(ICONS_DIR / "favicon.ico"),
        format="ICO",
        sizes=[(s, s) for s in favicon_sizes],
        append_images=imgs[1:],
    )
    print(f"  ✓ favicon.ico ({','.join(str(s) for s in favicon_sizes)}px)")

    # ── Windows ICO (256px, high quality) ─────────────────────────
    win_sizes = [16, 24, 32, 48, 64, 128, 256]
    win_imgs = []
    for sz in win_sizes:
        data = svg_to_png_bytes(ICON_SVG, sz)
        win_imgs.append(Image.open(io.BytesIO(data)).convert("RGBA"))
    win_imgs[0].save(
        str(ICONS_DIR / "windows-256.ico"),
        format="ICO",
        sizes=[(s, s) for s in win_sizes],
        append_images=win_imgs[1:],
    )
    print(f"  ✓ windows-256.ico ({','.join(str(s) for s in win_sizes)}px)")

    # ── Windows Live Tiles ─────────────────────────────────────────
    cairosvg.svg2png(url=str(TILE_SVG), write_to=str(ICONS_DIR / "windows-tile-150.png"), output_width=150, output_height=150)
    cairosvg.svg2png(url=str(TILE_SVG), write_to=str(ICONS_DIR / "windows-tile-310.png"), output_width=310, output_height=310)
    print("  ✓ windows-tile-150.png, windows-tile-310.png")

    # ── macOS (1024px for App Store, .icns) ───────────────────────
    svg_to_png(ICON_SVG, 1024, ICONS_DIR / "icon-1024.png")
    _build_icns(ICON_SVG, svg_to_png_bytes)

    # ── iOS ───────────────────────────────────────────────────────
    ios_sizes = {
        "ios-60.png": 60,
        "ios-87.png": 87,
        "ios-120.png": 120,
        "ios-167.png": 167,
        "ios-180.png": 180,
        "ios-1024.png": 1024,
    }
    for fname, sz in ios_sizes.items():
        svg_to_png(ICON_SVG, sz, ICONS_DIR / fname)

    # ── Android ───────────────────────────────────────────────────
    android_sizes = {
        "android-48.png": 48,
        "android-72.png": 72,
        "android-96.png": 96,
        "android-144.png": 144,
        "android-192.png": 192,
        "android-512.png": 512,
    }
    for fname, sz in android_sizes.items():
        svg_to_png(ICON_SVG, sz, ICONS_DIR / fname)

    # ── Linux ─────────────────────────────────────────────────────
    svg_to_png(ICON_SVG, 128, ICONS_DIR / "linux-128.png")
    svg_to_png(ICON_SVG, 256, ICONS_DIR / "linux-256.png")
    svg_to_png(ICON_SVG, 512, ICONS_DIR / "linux-512.png")

    # ── Notifications ─────────────────────────────────────────────
    svg_to_png(NOTIF_SVG, 20, ICONS_DIR / "notification-20.png")
    svg_to_png(NOTIF_SVG, 40, ICONS_DIR / "notification-40.png")
    svg_to_png(NOTIF_SVG, 64, ICONS_DIR / "notification-64.png")

    print(f"\n  All icons exported to: {ICONS_DIR}")


def _build_icns(svg_path: Path, png_fn):
    """Build a macOS .icns file from the icon SVG."""
    # icns format: 4-byte type + 4-byte length + data
    ICNS_SIZES = {
        "icp4": 16, "icp5": 32, "icp6": 64,
        "ic07": 128, "ic08": 256, "ic09": 512, "ic10": 1024,
        "ic11": 32, "ic12": 64, "ic13": 256, "ic14": 512,
    }
    # Deduplicate sizes
    unique = {v: k for k, v in ICNS_SIZES.items()}

    icns_data = b""
    for sz, tag in sorted(unique.items()):
        png = png_fn(svg_path, sz)
        entry = tag.encode() + struct.pack(">I", len(png) + 8) + png
        icns_data += entry

    header = b"icns" + struct.pack(">I", len(icns_data) + 8)
    icns_path = ICONS_DIR / "macos.icns"
    icns_path.write_bytes(header + icns_data)
    print(f"  ✓ macos.icns ({len(unique)} sizes)")


def export_fallback_svg_copies():
    """If cairosvg isn't available, copy SVGs with platform naming."""
    import shutil
    copies = {
        "favicon.svg": FAVICON_SVG,
        "icon-512.svg": ICON_SVG,
        "windows-tile.svg": TILE_SVG,
        "notification.svg": NOTIF_SVG,
        "logo-full.svg": ASSETS_DIR / "fredai-logo.svg",
    }
    for dest, src in copies.items():
        shutil.copy2(src, ICONS_DIR / dest)
        print(f"  ✓ {dest} (SVG copy)")
    print(f"\n  SVG icons in: {ICONS_DIR}")
    print("  To export PNGs: pip install cairosvg pillow && python3 export_icons.py")


if __name__ == "__main__":
    print("FredAI Icon Export\n" + "="*40)
    try:
        import cairosvg
        from PIL import Image
        print("Using cairosvg for high-quality PNG export...\n")
        export_with_cairosvg()
    except ImportError as e:
        print(f"cairosvg/pillow not installed ({e})")
        print("Copying SVG source files (usable directly in web/Electron)...\n")
        export_fallback_svg_copies()

    print("\nPlatform reference:")
    print("  macOS      → macos.icns, icon-512.png, icon-1024.png")
    print("  Windows    → windows-256.ico, windows-tile-150.png, windows-tile-310.png")
    print("  iOS        → ios-60/87/120/167/180/1024.png")
    print("  Android    → android-48/72/96/144/192/512.png")
    print("  Linux      → linux-128/256/512.png")
    print("  Web/PWA    → favicon.ico, icon-192.png, icon-512.png")
    print("  Notify     → notification-20/40/64.png")
