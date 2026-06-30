"""
Build FredAI-Setup.exe for Windows — a self-contained bootstrapper.
The EXE doesn't bundle the full app; it downloads and installs it.
This keeps the .exe small (~5MB) and always pulls the latest code.

Run on Windows CI:
    python deploy/build_exe.py
"""
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT     = Path(__file__).parent.parent
DIST_DIR = ROOT / "dist"
DIST_DIR.mkdir(exist_ok=True)

# Bootstrap script embedded into the EXE
BOOTSTRAP = textwrap.dedent("""
import os, sys, subprocess, urllib.request, tempfile, webbrowser, time

REPO  = "https://github.com/essentialbit/fredai"
ZIP   = "https://github.com/essentialbit/fredai/archive/refs/heads/main.zip"
DEST  = os.path.join(os.path.expanduser("~"), "FredAI")

def banner(msg):
    print("\\n" + "="*50)
    print(f"  {msg}")
    print("="*50)

def run(*args, **kw):
    return subprocess.run(list(args), check=True, **kw)

banner("FredAI Installer")
print(f"Installing to: {DEST}")
print()

# Download ZIP
print("[1/5] Downloading FredAI...")
with tempfile.TemporaryDirectory() as tmp:
    zip_path = os.path.join(tmp, "fredai.zip")
    urllib.request.urlretrieve(ZIP, zip_path)
    print("      Extracting...")
    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    import shutil, glob
    extracted = glob.glob(os.path.join(tmp, "fredai-*"))[0]
    if os.path.exists(DEST):
        shutil.rmtree(DEST)
    shutil.copytree(extracted, DEST)

# Run PowerShell installer
print("[2/5] Running installer...")
ps1 = os.path.join(DEST, "deploy", "install.ps1")
run("powershell.exe", "-ExecutionPolicy", "Bypass", "-File", ps1)

print("[3/5] Done! FredAI is starting...")
time.sleep(4)
webbrowser.open("http://localhost:8080")
input("\\nPress Enter to close this window...")
""").strip()

# Write bootstrap script
bootstrap_path = DIST_DIR / "_bootstrap.py"
bootstrap_path.write_text(BOOTSTRAP)

# PyInstaller command
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onefile",
    "--clean",
    "--noconsole",  # Windows: no console window flash
    "--name", "FredAI-Setup",
    "--distpath", str(DIST_DIR),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(DIST_DIR),
]

# Add icon if available
icon = ROOT / "assets" / "icons" / "windows-256.ico"
if icon.exists():
    cmd += ["--icon", str(icon)]
else:
    print("No .ico found — building without icon")

# Add version info
cmd += ["--version-file", str(DIST_DIR / "_version.txt")]
version_txt = """
VSVersionInfo(
  ffi=FixedFileInfo(filevers=(1,0,0,0),prodvers=(1,0,0,0),
    mask=0x3f,flags=0x0,OS=0x40004,fileType=0x1,subtype=0x0,date=(0,0)),
  kids=[StringFileInfo([StringTable(u'040904B0',[
    StringStruct(u'CompanyName',u'EssentialBit'),
    StringStruct(u'FileDescription',u'FredAI Financial Intelligence Installer'),
    StringStruct(u'FileVersion',u'1.0.0'),
    StringStruct(u'ProductName',u'FredAI'),
    StringStruct(u'ProductVersion',u'1.0.0'),
  ])]),VarFileInfo([VarStruct(u'Translation',[1033,1200])])]
)
""".strip()
(DIST_DIR / "_version.txt").write_text(version_txt)

cmd.append(str(bootstrap_path))

print("Building FredAI-Setup.exe...")
result = subprocess.run(cmd, cwd=str(ROOT))
if result.returncode == 0:
    exe = DIST_DIR / "FredAI-Setup.exe"
    print(f"\nBuilt: {exe} ({exe.stat().st_size // 1024 // 1024}MB)")
else:
    print("Build failed")
    sys.exit(1)
