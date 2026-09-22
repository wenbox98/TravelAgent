import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from _bootstrap import enter


def main():
    enter()
    from travel_agent.settings import Settings
    def version(name):
        executable = shutil.which(name)
        if not executable:
            return "UNAVAILABLE"
        result = subprocess.run([executable, "--version"], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else "FAILED"
    browser = any((Path(os.environ.get(env, "__absent__")) / suffix).is_file() for env, suffix in (
        ("PROGRAMFILES(X86)", "Microsoft/Edge/Application/msedge.exe"),
        ("PROGRAMFILES", "Google/Chrome/Application/chrome.exe"),
        ("PROGRAMFILES", "Microsoft/Edge/Application/msedge.exe")))
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", Settings.load().preferred_port))
            port = "AVAILABLE"
        except OSError:
            port = "IN_USE"
    dpapi = "UNAVAILABLE"
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.WinDLL("crypt32").CryptProtectData
            dpapi = "API_PRESENT_UNVERIFIED"
        except (OSError, AttributeError):
            pass
    print(json.dumps({"python": sys.version.split()[0], "node": version("node"), "browser": "DETECTED_UNVERIFIED" if browser else "UNAVAILABLE", "port_8765": port, "secret_store": dpapi, "credential_persistence": "DISABLED", "xhs": "DISABLED", "model": "UNCONFIGURED", "amap": "UNCONFIGURED", "quotes": "UNSUPPORTED"}, ensure_ascii=False, indent=2))
    return 0 if port == "AVAILABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
