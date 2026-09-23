"""Human-operated login control; serve/status never launch a browser or visit XHS."""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/xhs-sidecar"))

from pydantic import SecretStr  # noqa: E402
from xhs_sidecar.app import SidecarConfig  # noqa: E402
from xhs_sidecar.models import LoginState  # noqa: E402


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("本地登录接口不允许重定向")


def main() -> int:
    parser = argparse.ArgumentParser(description="小红书本机登录；不提供搜索和详情命令")
    parser.add_argument(
        "command", choices=["serve", "status", "connect", "resume", "cancel", "disconnect"]
    )
    args = parser.parse_args()
    if args.command == "serve":
        from xhs_sidecar.__main__ import main as serve

        os.environ["TRAVEL_XHS_SIDECAR_MODE"] = "login"
        return serve()
    try:
        config = SidecarConfig(
            secret=SecretStr(os.environ.get("TRAVEL_XHS_SIDECAR_SECRET", "")),
            port=int(os.environ.get("TRAVEL_XHS_SIDECAR_PORT", "18061")),
        )
        request = Request(
            f"http://{config.host}:{config.port}/v1/login/{args.command}",
            headers={"Authorization": "Bearer " + config.secret.get_secret_value()},
            method="GET" if args.command == "status" else "POST",
        )
        # Never honor environment proxies or redirects for this local control channel.
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=50) as response:
            state = LoginState.model_validate(json.loads(response.read(16_384)))
        print(f"状态：{state.status}；generation：{state.generation}")
        if state.error_code:
            print(f"错误：{state.error_code}；请先 cancel/disconnect 完成清理，再重新 connect。")
        if state.stop_reason:
            print(f"停止原因：{state.stop_reason}；观察次数：{state.observation_attempts}")
        if state.evidence is not None:
            print("登录信号：" + json.dumps(state.evidence.model_dump(), ensure_ascii=False))
        if state.status in {"LOGIN_REQUIRED", "WAITING_USER"}:
            print("请在已打开的官方浏览器窗口正常登录；本地 status 不会刷新页面。")
        elif state.status == "VERIFICATION_REQUIRED":
            print("自动观察已暂停。请在官方窗口手工处理；完成后显式运行 resume。")
        return 1 if state.status in {"ERROR", "NOT_IMPLEMENTED"} else 0
    except Exception:
        # Do not print transport exception stacks, response content or Authorization headers.
        print("本地登录控制未完成：检查服务、专用凭证与端口。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
