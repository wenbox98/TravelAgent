from dataclasses import dataclass
import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    def __post_init__(self):
        object.__setattr__(self, "root", self.root.resolve())
        if self.root.is_relative_to(PROJECT_ROOT) and not self.root.is_relative_to(PROJECT_ROOT / ".local"):
            raise ValueError("开发运行目录只能位于 .local")

    def child(self, name: str) -> Path:
        if Path(name).is_absolute():
            raise ValueError("运行文件必须使用相对路径")
        result = (self.root / name).resolve()
        if not result.is_relative_to(self.root) or result == self.root:
            raise ValueError("运行文件超出受控目录")
        return result

    @property
    def database(self):
        return self.child("travel-agent.sqlite3")

    @property
    def profile(self):
        return self.child("profile")

    def ensure(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("profile", "logs", "cache"):
            self.child(name).mkdir(exist_ok=True)

    @classmethod
    def default(cls, *, development=True):
        if development:
            return cls(PROJECT_ROOT / ".local" / "runtime")
        location = os.environ.get("LOCALAPPDATA")
        if not location:
            raise ValueError("当前系统未配置应用数据目录")
        return cls(Path(location) / "TravelAgent")


@dataclass(frozen=True)
class Settings:
    mode: str
    bind_host: str
    preferred_port: int
    xhs_live_enabled: bool
    overview_budget: dict

    def __post_init__(self):
        if self.mode != "mock" or self.xhs_live_enabled is not False:
            raise ValueError("T00/T01 仅支持离线合成演示")
        if self.bind_host != "127.0.0.1":
            raise ValueError("只允许绑定 127.0.0.1")
        if type(self.preferred_port) is not int or not 1 <= self.preferred_port <= 65535:
            raise ValueError("端口必须在 1 到 65535 之间")
        if self.overview_budget != {"search_ops": 3, "detail_ops": 6, "vision_images": 2}:
            raise ValueError("当前 PoC 使用 3/6 护栏")

    @classmethod
    def load(cls, **overrides):
        values = json.loads((PROJECT_ROOT / "config/defaults.json").read_text(encoding="utf-8"))
        fields = cls.__dataclass_fields__
        if set(overrides) - set(fields):
            raise ValueError("未知配置字段")
        return cls(**({name: values[name] for name in fields} | overrides))
