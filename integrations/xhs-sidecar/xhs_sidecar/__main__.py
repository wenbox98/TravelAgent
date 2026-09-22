import os
import sys

import uvicorn
from pydantic import SecretStr, ValidationError

from .app import SidecarConfig, create_app


def main() -> int:
    try:
        config = SidecarConfig(
            secret=SecretStr(os.environ.get("TRAVEL_XHS_SIDECAR_SECRET", "")),
            port=int(os.environ.get("TRAVEL_XHS_SIDECAR_PORT", "18061")),
        )
    except ValueError, ValidationError:
        print("本地sidecar配置无效：检查专用凭证和端口。", file=sys.stderr)
        return 2
    # No arbitrary bind address, browser flags, live mode, or upstream command.
    uvicorn.run(
        create_app(config),
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
