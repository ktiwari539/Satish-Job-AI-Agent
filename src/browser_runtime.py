from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import sys


class BrowserRuntimeUnavailable(RuntimeError):
    def __init__(self, message="Browser runtime unavailable", *, reason_code="browser_runtime_unavailable"):
        super().__init__(message)
        self.reason_code = reason_code

    def diagnostics(self):
        """Static remediation only; never expose browser errors, profile paths or PII."""
        return {
            "reason_code": self.reason_code,
            "reason": {
                "playwright_import_failed": "Playwright cannot be imported by the active Python interpreter.",
                "chromium_not_installed": "The Chromium executable for this Playwright installation is missing.",
                "browser_profile_in_use": "The saved agent browser profile is already open.",
            }.get(self.reason_code, "The local browser runtime could not start."),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "virtual_environment_active": sys.prefix != sys.base_prefix,
            "project_virtualenv_available": Path(".venv/bin/python").is_file(),
            "next_action": {
                "playwright_import_failed": "use_project_virtualenv_or_install_playwright_in_this_interpreter",
                "chromium_not_installed": "install_chromium_with_the_same_python_interpreter",
                "browser_profile_in_use": "close_the_agent_browser_then_retry_without_deleting_profile",
            }.get(self.reason_code, "inspect_browser_runtime_setup"),
        }


def _load_sync_playwright():
    from playwright.sync_api import sync_playwright
    return sync_playwright


def check_browser_runtime():
    """Fail once before certification considers any job; no browser/profile access."""
    try:
        _load_sync_playwright()
    except ImportError as exc:
        raise BrowserRuntimeUnavailable(
            "This Python interpreter cannot import Playwright. Use the project's virtual environment.",
            reason_code="playwright_import_failed",
        ) from exc


def _launch_failure(exc):
    message = str(exc).lower()
    if "executable doesn't exist" in message or "executable does not exist" in message:
        code = "chromium_not_installed"
    elif any(token in message for token in ("processsingleton", "singletonlock", "user data directory is already in use")):
        code = "browser_profile_in_use"
    else:
        code = "browser_launch_failed"
    return BrowserRuntimeUnavailable("Chromium could not start; check the reported setup action.", reason_code=code)


@dataclass(frozen=True)
class BrowserRuntimeConfig:
    user_data_dir: str = "browser-profile"
    headless: bool = False
    slow_mo_ms: int = 125


class PlaywrightSession:
    """Optional local browser runtime.

    Playwright is intentionally imported lazily so CI/unit tests do not need a
    browser package. The persistent profile must stay outside Git and on a
    user-controlled machine or approved private runner.
    """

    def __init__(self, config: Optional[BrowserRuntimeConfig] = None):
        self.config = config or BrowserRuntimeConfig()
        self._pw = None
        self.context = None
        self.page = None

    def __enter__(self):
        check_browser_runtime()
        sync_playwright = _load_sync_playwright()

        profile_dir = Path(self.config.user_data_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._pw = sync_playwright().start()
            self.context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=self.config.headless,
                slow_mo=self.config.slow_mo_ms,
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        except Exception as exc:
            # __exit__ is not called when __enter__ raises. Stop the driver
            # here so missing executables/profile locks cannot leak processes.
            self.__exit__(type(exc), exc, None)
            raise _launch_failure(exc) from exc
        return self

    def __exit__(self, exc_type, exc, tb):
        # KeyboardInterrupt can disconnect the Playwright driver while the
        # interactive debug checkpoint is open. Do not replace the original
        # result with a redundant "connection closed" cleanup traceback.
        unexpected = None
        try:
            if self.context is not None:
                try:
                    self.context.close()
                except Exception as cleanup_exc:
                    if not self._driver_already_disconnected(cleanup_exc):
                        unexpected = cleanup_exc
        finally:
            if self._pw is not None:
                try:
                    self._pw.stop()
                except Exception as cleanup_exc:
                    if (
                        unexpected is None
                        and not self._driver_already_disconnected(cleanup_exc)
                    ):
                        unexpected = cleanup_exc
        if unexpected is not None and exc_type is None:
            raise unexpected
        return False

    @staticmethod
    def _driver_already_disconnected(exc):
        message = str(exc).lower()
        return (
            "connection closed" in message
            or "event loop is closed" in message
            or "target page, context or browser has been closed" in message
        )
