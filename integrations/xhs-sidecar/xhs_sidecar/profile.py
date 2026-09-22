"""An owned profile with a narrow, independently checked deletion boundary."""

import os
from pathlib import Path
import shutil
import stat
import time

from platformdirs import user_data_path


class ProfileError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("专用浏览器资料目录不可安全使用或清理失败")


class ProfileStore:
    _marker_name = ".travelagent-xhs-profile"
    _marker_value = "TravelAgent XHS owned profile v1\n"

    def __init__(self, project_root: Path, root: Path | None = None) -> None:
        configured = os.environ.get("TRAVEL_XHS_PROFILE_ROOT")
        self._root = root or (
            Path(configured)
            if configured
            else user_data_path("TravelAgent", appauthor=False) / "xhs"
        )
        # Reject network-share syntax before resolve/stat can contact a remote host.
        if str(self._root).startswith(("\\\\", "//")):
            raise ProfileError()
        self._project = project_root.resolve()
        self._validate_path()

    def _validate_path(self) -> None:
        root = self._root
        if not root.is_absolute() or ".." in root.parts:
            raise ProfileError()
        resolved = root.resolve()
        if resolved.is_relative_to(self._project) or self._project.is_relative_to(resolved):
            raise ProfileError()
        # A developer override must never turn a daily-browser directory into ours.
        if any(
            part.casefold() in {"user data", "google", "chrome", "chromium", "edge"}
            for part in root.parts
        ):
            raise ProfileError()
        for path in (root / "browser-profile", root, *root.parents):
            try:
                attributes = path.lstat()
            except FileNotFoundError:
                continue
            except OSError:
                raise ProfileError() from None
            if stat.S_ISLNK(attributes.st_mode) or (
                getattr(attributes, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise ProfileError()
            if (path / ".git").exists():
                raise ProfileError()
        if root.exists() and not root.is_dir():
            raise ProfileError()

    def _is_owned(self) -> bool:
        self._validate_path()
        marker = self._root / self._marker_name
        try:
            if marker.is_symlink():
                raise ProfileError()
            return marker.read_text(encoding="utf-8") == self._marker_value
        except FileNotFoundError:
            return False
        except OSError, UnicodeError:
            raise ProfileError() from None

    def get_profile_path(self) -> Path:
        self._validate_path()
        return self._root / "browser-profile"

    def exists(self) -> bool:
        """Read local filesystem metadata only; never initialize a browser."""
        owned = self._is_owned()
        profile = self.get_profile_path()
        if profile.exists() and not owned:
            raise ProfileError()
        return owned and profile.is_dir()

    def prepare(self) -> Path:
        self._validate_path()
        try:
            if self._root.exists() and not self._is_owned() and any(self._root.iterdir()):
                raise ProfileError()
            self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._validate_path()
            marker = self._root / self._marker_name
            if not self._is_owned():
                # Exclusive creation avoids overwriting someone else's ownership data.
                with marker.open("x", encoding="utf-8") as stream:
                    stream.write(self._marker_value)
            profile = self.get_profile_path()
            profile.mkdir(exist_ok=True, mode=0o700)
            return profile
        except OSError, UnicodeError:
            raise ProfileError() from None

    def clear_profile(self) -> None:
        """Delete only the fixed owned child, after the caller closes the browser."""
        self._validate_path()
        profile = self.get_profile_path()
        if not profile.exists():
            return
        if not self._is_owned() or profile.resolve().parent != self._root.resolve():
            raise ProfileError()
        for attempt in range(3):
            self._validate_path()
            if not self._is_owned():
                raise ProfileError()
            try:
                shutil.rmtree(profile)
                return
            except FileNotFoundError:
                return
            except OSError:
                if attempt == 2:
                    raise ProfileError() from None
                time.sleep(0.1 * (attempt + 1))
