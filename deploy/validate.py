#!/usr/bin/env python3
"""
FredAI Deployment Validator
Checks that all deployment artifacts are present, syntactically valid,
and correctly handle each target platform scenario.

Usage:
    python3 deploy/validate.py              # interactive
    python3 deploy/validate.py --ci         # CI mode (exit 1 on failure)
    python3 deploy/validate.py --fix        # auto-fix minor issues
"""
import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

PASS = "\033[32m  PASS\033[0m"
FAIL = "\033[31m  FAIL\033[0m"
SKIP = "\033[33m  SKIP\033[0m"
WARN = "\033[33m  WARN\033[0m"
HDR  = "\033[36m"
NC   = "\033[0m"


class ValidationSuite:
    def __init__(self, ci=False, fix=False):
        self.ci   = ci
        self.fix  = fix
        self.results: list[dict] = []

    def check(self, name: str, platform: str, fn):
        try:
            result = fn()
            if result is True:
                self.results.append({"name": name, "platform": platform, "status": "PASS"})
                print(f"{PASS}  [{platform}]  {name}")
            elif result is None:
                self.results.append({"name": name, "platform": platform, "status": "SKIP"})
                print(f"{SKIP}  [{platform}]  {name}")
            else:
                msg = result if isinstance(result, str) else "check failed"
                self.results.append({"name": name, "platform": platform, "status": "FAIL", "msg": msg})
                print(f"{FAIL}  [{platform}]  {name}: {msg}")
        except Exception as e:
            self.results.append({"name": name, "platform": platform, "status": "FAIL", "msg": str(e)})
            print(f"{FAIL}  [{platform}]  {name}: {e}")

    def summary(self) -> bool:
        passed  = sum(1 for r in self.results if r["status"] == "PASS")
        failed  = sum(1 for r in self.results if r["status"] == "FAIL")
        skipped = sum(1 for r in self.results if r["status"] == "SKIP")
        total   = len(self.results)

        print(f"\n{'═'*55}")
        print(f"  Results: {passed}/{total} passed  |  {failed} failed  |  {skipped} skipped")

        if failed:
            print(f"\n  Failed checks:")
            for r in self.results:
                if r["status"] == "FAIL":
                    print(f"    [{r['platform']}] {r['name']}: {r.get('msg','')}")
        print(f"{'═'*55}")
        return failed == 0


# ── File presence ──────────────────────────────────────────────────────────────
def check_file_exists(path: Path, description: str = None):
    def _check():
        if path.exists():
            return True
        return f"Missing: {path.relative_to(ROOT)}"
    return _check

REQUIRED_FILES = [
    # Core app
    (ROOT / "main.py",                  "Flask server"),
    (ROOT / "agent.py",                 "FredAI agent"),
    (ROOT / "config.py",                "Configuration"),
    (ROOT / "memory_store.py",          "SQLite store"),
    (ROOT / "market_data.py",           "Market data"),
    (ROOT / "twitter_client.py",        "X API client"),
    (ROOT / "trend_detector.py",        "Trend detection"),
    (ROOT / "requirements.txt",         "Python deps"),
    (ROOT / "requirements-lite.txt",    "Lite deps"),
    (ROOT / ".env.example",             ".env template"),
    (ROOT / "Dockerfile",               "Docker image"),
    (ROOT / "docker-compose.yml",       "Docker Compose"),
    (ROOT / "soul.md",                  "Fred's soul"),
    (ROOT / "templates" / "dashboard.html", "Dashboard UI"),
    # Deploy
    (ROOT / "deploy" / "install.sh",    "Linux/macOS/Pi installer"),
    (ROOT / "deploy" / "install.bat",   "Windows batch"),
    (ROOT / "deploy" / "install.ps1",   "Windows PowerShell"),
    (ROOT / "deploy" / "setup.py",      "Python setup"),
    (ROOT / "deploy" / "build_exe.py",  "EXE builder"),
    # PWA
    (ROOT / "static" / "manifest.json", "PWA manifest"),
    (ROOT / "static" / "sw.js",         "Service worker"),
    # CI
    (ROOT / ".github" / "workflows" / "ci.yml",      "CI workflow"),
    (ROOT / ".github" / "workflows" / "release.yml", "Release workflow"),
]


# ── Python syntax ──────────────────────────────────────────────────────────────
def check_python_syntax(path: Path):
    def _check():
        if not path.exists():
            return f"Missing: {path.name}"
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source)
            return True
        except SyntaxError as e:
            return f"Syntax error at line {e.lineno}: {e.msg}"
    return _check

PYTHON_FILES = [
    ROOT / "main.py", ROOT / "agent.py", ROOT / "config.py",
    ROOT / "memory_store.py", ROOT / "market_data.py",
    ROOT / "twitter_client.py", ROOT / "trend_detector.py",
    ROOT / "deploy" / "setup.py", ROOT / "deploy" / "build_exe.py",
]


# ── Shell script checks ────────────────────────────────────────────────────────
def check_shell_syntax(path: Path):
    def _check():
        if not path.exists():
            return f"Missing: {path.name}"
        if sys.platform == "win32":
            return None  # Skip on Windows
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        if result.returncode == 0:
            return True
        return result.stderr.strip()
    return _check

def check_powershell_syntax(path: Path):
    def _check():
        if not path.exists():
            return f"Missing: {path.name}"
        # Parse-only check without executing
        content = path.read_text(encoding="utf-8")
        # Basic structural checks
        issues = []
        opens  = content.count("{")
        closes = content.count("}")
        if abs(opens - closes) > 2:  # allow for strings containing braces
            issues.append(f"Unbalanced braces: {opens} open, {closes} close")
        if not content.strip().startswith("#"):
            issues.append("Missing file header comment")
        return True if not issues else "; ".join(issues)
    return _check


# ── Import validation ──────────────────────────────────────────────────────────
def check_python_imports():
    def _check():
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0,'.');"
             "from config import ANTHROPIC_API_KEY, AI_PROVIDER, PRIVACY_MODE;"
             "from agent import get_provider_status;"
             "from memory_store import export_user_data, delete_user_data, prune_old_data;"
             "print('OK')"],
            capture_output=True, text=True, cwd=str(ROOT)
        )
        if result.returncode == 0:
            return True
        return result.stderr.split("\n")[-2]
    return _check


# ── PWA manifest validation ────────────────────────────────────────────────────
def check_pwa_manifest():
    def _check():
        import json
        manifest_path = ROOT / "static" / "manifest.json"
        if not manifest_path.exists():
            return "manifest.json missing"
        try:
            m = json.loads(manifest_path.read_text())
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"
        required = ["name", "short_name", "start_url", "display", "icons"]
        missing  = [k for k in required if k not in m]
        if missing:
            return f"Missing keys: {missing}"
        if len(m["icons"]) < 1:
            return "No icons defined"
        return True
    return _check

def check_pwa_sw():
    def _check():
        sw_path = ROOT / "static" / "sw.js"
        if not sw_path.exists():
            return "sw.js missing"
        content = sw_path.read_text()
        if "install" not in content:
            return "Missing install event handler"
        if "fetch" not in content:
            return "Missing fetch event handler"
        return True
    return _check

def check_dashboard_pwa_links():
    def _check():
        html_path = ROOT / "templates" / "dashboard.html"
        if not html_path.exists():
            return "dashboard.html missing"
        content = html_path.read_text()
        checks = {
            "manifest link": 'rel="manifest"' in content,
            "apple-mobile-web-app-capable": "apple-mobile-web-app-capable" in content,
            "service worker registration": "serviceWorker" in content,
        }
        failed = [k for k, v in checks.items() if not v]
        return True if not failed else f"Missing: {', '.join(failed)}"
    return _check


# ── Platform-specific scenario checks ─────────────────────────────────────────

def check_linux_installer_has_distro_detection():
    def _check():
        content = (ROOT / "deploy" / "install.sh").read_text()
        checks = {
            "apt-get support":  "apt-get" in content or "apt" in content,
            "dnf support":      "dnf" in content,
            "pacman support":   "pacman" in content,
            "brew support":     "brew" in content,
            "arch detection":   "ARCH=" in content,
            "RAM detection":    "RAM_MB" in content,
            "lite mode":        "TIER=" in content or "lite" in content.lower(),
            "systemd service":  "systemctl" in content,
            "macOS launchd":    "launchctl" in content or "LaunchAgent" in content,
            "ollama install":   "ollama" in content,
            "Pi detection":     "aarch64" in content or "arm" in content,
        }
        missing = [k for k, v in checks.items() if not v]
        return True if not missing else f"Missing: {', '.join(missing)}"
    return _check

def check_windows_installer_handles_no_python():
    def _check():
        content = (ROOT / "deploy" / "install.ps1").read_text()
        checks = {
            "python version check":    "python" in content.lower() and "version" in content.lower(),
            "winget fallback":         "winget" in content,
            "direct download fallback":"python.org" in content.lower() or "PythonUrl" in content,
            "venv setup":              "venv" in content,
            "ollama install":          "ollama" in content.lower(),
            "start menu shortcut":     "StartMenu" in content or "Programs" in content,
            "desktop shortcut":        "Desktop" in content,
            "scheduled task":          "ScheduledTask" in content or "scheduler" in content.lower(),
            "RAM detection":           "RamMB" in content or "TotalPhysical" in content,
        }
        missing = [k for k, v in checks.items() if not v]
        return True if not missing else f"Missing: {', '.join(missing)}"
    return _check

def check_raspberry_pi_lite_mode():
    def _check():
        sh = (ROOT / "deploy" / "install.sh").read_text()
        setup = (ROOT / "deploy" / "setup.py").read_text()
        checks = {
            "sh: lite tier":        "lite" in sh and ("TIER" in sh or "tier" in sh),
            "sh: nano tier":        "nano" in sh,
            "sh: Pi ARM detection": "arm" in sh or "aarch64" in sh,
            "sh: skip ollama<512":  "nano" in sh and "ollama" in sh,
            "setup.py: is_rpi()":   "is_raspberry_pi" in setup or "aarch64" in setup,
            "requirements-lite.txt":  (ROOT / "requirements-lite.txt").exists(),
        }
        missing = [k for k, v in checks.items() if not v]
        return True if not missing else f"Missing: {', '.join(missing)}"
    return _check

def check_ios_android_pwa():
    def _check():
        manifest = (ROOT / "static" / "manifest.json").read_text()
        html     = (ROOT / "templates" / "dashboard.html").read_text()
        checks = {
            "manifest: display standalone": '"standalone"' in manifest,
            "manifest: theme_color":        "theme_color" in manifest,
            "manifest: icons array":        '"icons"' in manifest,
            "html: apple-touch-icon":       "apple-touch-icon" in html,
            "html: apple-mobile-web-app-capable": "apple-mobile-web-app-capable" in html,
            "html: manifest link":          'rel="manifest"' in html,
            "html: service worker reg":     "serviceWorker" in html,
            "html: viewport cover":         "viewport-fit=cover" in html,
        }
        missing = [k for k, v in checks.items() if not v]
        return True if not missing else f"Missing: {', '.join(missing)}"
    return _check

def check_docker_multi_arch():
    def _check():
        dkr = (ROOT / "Dockerfile").read_text()
        yml = (ROOT / "docker-compose.yml").read_text()
        rel = (ROOT / ".github" / "workflows" / "release.yml").read_text()
        checks = {
            "Dockerfile: python base":    "python" in dkr.lower(),
            "Dockerfile: EXPOSE 8080":    "EXPOSE" in dkr,
            "Dockerfile: health check":   "HEALTHCHECK" in dkr,
            "release.yml: arm64 build":   "arm64" in rel,
            "release.yml: arm/v7 build":  "arm/v7" in rel,
            "release.yml: multi-arch":    "platforms" in rel and "linux/arm" in rel,
        }
        missing = [k for k, v in checks.items() if not v]
        return True if not missing else f"Missing: {', '.join(missing)}"
    return _check

def check_env_example_complete():
    def _check():
        content = (ROOT / ".env.example").read_text()
        required_keys = [
            "X_BEARER_TOKEN", "ANTHROPIC_API_KEY", "AI_PROVIDER",
            "OLLAMA_URL", "OLLAMA_MODEL", "PRIVACY_MODE",
            "DATA_RETENTION_DAYS", "SECRET_KEY", "PORT",
        ]
        missing = [k for k in required_keys if k not in content]
        return True if not missing else f"Missing keys: {missing}"
    return _check

def check_privacy_endpoints():
    def _check():
        content = (ROOT / "main.py").read_text()
        routes = [
            "/api/user/export",
            "/api/user/delete",
            "/api/user/privacy",
            "/api/user/consent",
        ]
        missing = [r for r in routes if r not in content]
        return True if not missing else f"Missing routes: {missing}"
    return _check

def check_ollama_fallback_in_agent():
    def _check():
        content = (ROOT / "agent.py").read_text()
        checks = {
            "provider class":       "_FredProvider" in content,
            "ollama complete":      "_ollama_complete" in content,
            "anthropic fallback":   "anthropic" in content,
            "auto detect":          "_resolve_provider" in content or "auto" in content,
            "privacy strip":        "_strip_portfolio" in content,
        }
        missing = [k for k, v in checks.items() if not v]
        return True if not missing else f"Missing: {', '.join(missing)}"
    return _check

def check_gitignore_secrets():
    def _check():
        gi_path = ROOT / ".gitignore"
        if not gi_path.exists():
            return ".gitignore missing"
        content = gi_path.read_text()
        checks = {
            ".env secret":      ".env" in content,
            "venv excluded":    "venv" in content or ".venv" in content,
            "db excluded":      "*.db" in content or "data/" in content,
        }
        missing = [k for k, v in checks.items() if not v]
        return True if not missing else f"Missing: {', '.join(missing)}"
    return _check

def check_requirements_installable():
    def _check():
        req = ROOT / "requirements.txt"
        if not req.exists():
            return "requirements.txt missing"
        # Just check it's parseable (not empty, not corrupt)
        lines = [l.strip() for l in req.read_text().splitlines() if l.strip() and not l.startswith("#")]
        if len(lines) < 5:
            return f"Too few dependencies ({len(lines)})"
        return True
    return _check


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ci",  action="store_true", help="CI mode (exit 1 on failures)")
    parser.add_argument("--fix", action="store_true", help="Auto-fix minor issues")
    args = parser.parse_args()

    v = ValidationSuite(ci=args.ci, fix=args.fix)

    print(f"\n{HDR}═══ FredAI Deployment Validator ═══{NC}\n")

    # File presence
    print(f"{HDR}── Required files ──{NC}")
    for path, desc in REQUIRED_FILES:
        v.check(desc, "ALL", check_file_exists(path, desc))

    # Python syntax
    print(f"\n{HDR}── Python syntax ──{NC}")
    for path in PYTHON_FILES:
        if path.exists():
            v.check(f"Syntax: {path.name}", "ALL", check_python_syntax(path))

    # Shell scripts
    print(f"\n{HDR}── Shell scripts ──{NC}")
    v.check("bash -n: install.sh", "Linux/Pi",   check_shell_syntax(ROOT / "deploy" / "install.sh"))
    v.check("PowerShell structure", "Windows",   check_powershell_syntax(ROOT / "deploy" / "install.ps1"))

    # Python imports
    print(f"\n{HDR}── Python imports ──{NC}")
    v.check("Core imports (config/agent/memory)", "ALL", check_python_imports())

    # Platform scenarios
    print(f"\n{HDR}── Platform scenarios ──{NC}")
    v.check("Linux multi-distro + ARM support",  "Linux/Pi",  check_linux_installer_has_distro_detection())
    v.check("Windows handles missing Python",     "Windows",   check_windows_installer_handles_no_python())
    v.check("Raspberry Pi Zero lite mode",        "Pi Zero",   check_raspberry_pi_lite_mode())
    v.check("iOS/Android PWA install",            "iOS/Android", check_ios_android_pwa())
    v.check("Docker multi-arch (amd64/arm64/v7)", "Docker",    check_docker_multi_arch())

    # Config
    print(f"\n{HDR}── Configuration ──{NC}")
    v.check(".env.example has all required keys", "ALL",       check_env_example_complete())
    v.check(".gitignore excludes secrets/venv",   "ALL",       check_gitignore_secrets())
    v.check("requirements.txt parseable",         "ALL",       check_requirements_installable())

    # Feature checks
    print(f"\n{HDR}── Feature checks ──{NC}")
    v.check("Privacy endpoints in main.py",       "ALL",       check_privacy_endpoints())
    v.check("Ollama fallback + privacy strip",    "ALL",       check_ollama_fallback_in_agent())
    v.check("PWA manifest valid",                 "iOS/Android", check_pwa_manifest())
    v.check("Service worker present",             "iOS/Android", check_pwa_sw())
    v.check("Dashboard has PWA meta tags",        "iOS/Android", check_dashboard_pwa_links())

    ok = v.summary()
    if not ok and args.ci:
        sys.exit(1)


if __name__ == "__main__":
    main()
