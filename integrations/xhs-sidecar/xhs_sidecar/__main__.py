import os
import sys
from pathlib import Path

import uvicorn
from pydantic import SecretStr

from .app import SidecarConfig, create_app
from .browser import BrowserManager, BrowserOptions
from .login import LoginLifecycle
from .ordinary_browser import OrdinaryBrowserBackend
from .profile import ProfileStore


def configured_login() -> LoginLifecycle | None:
    mode = os.environ.get("TRAVEL_XHS_SIDECAR_MODE", "offline")
    if mode == "offline":
        return None
    if mode != "login":
        raise ValueError("sidecar运行模式无效")
    engine = os.environ.get("TRAVEL_XHS_BROWSER", "chrome")
    if engine not in {"chrome", "chromium"}:
        raise ValueError("普通浏览器类型无效")
    profile = ProfileStore(project_root=Path(__file__).resolve().parents[3])
    return LoginLifecycle(
        BrowserManager(
            OrdinaryBrowserBackend(profile),
            BrowserOptions(engine="chrome" if engine == "chrome" else "chromium", headless=False),
        ),
        profile,
    )


def main() -> int:
    try:
        config = SidecarConfig(
            secret=SecretStr(os.environ.get("TRAVEL_XHS_SIDECAR_SECRET", "")),
            port=int(os.environ.get("TRAVEL_XHS_SIDECAR_PORT", "18061")),
        )
        login = configured_login()
    except Exception:
        # Includes filesystem errors: neither paths nor raw configuration may reach a traceback.
        print("本地sidecar配置无效：检查专用凭证和端口。", file=sys.stderr)
        return 2
    # Construction reads local profile metadata only. Explicit connect starts the browser.
    uvicorn.run(
        create_app(config, login=login),
        host=config.host,
        port=config.port,
        access_log=False,
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {
                "discard": {"class": "logging.NullHandler"},
                "safe": {"class": "logging.StreamHandler"},
            },
            "loggers": {
                "uvicorn": {"handlers": ["discard"], "propagate": False},
                "uvicorn.error": {"handlers": ["discard"], "propagate": False},
                "uvicorn.access": {"handlers": ["discard"], "propagate": False},
                "xhs_sidecar": {"handlers": ["safe"], "level": "INFO", "propagate": False},
            },
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
