from dataclasses import dataclass
from pathlib import Path
from typing import Optional


class BrowserRuntimeUnavailable(RuntimeError):
    pass


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
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserRuntimeUnavailable(
                "Playwright is not installed. Install the optional local browser runtime first."
            ) from exc

        profile_dir = Path(self.config.user_data_dir)
        profile_dir.mkdir(parents=True, exist_ok=True)

        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=self.config.headless,
            slow_mo=self.config.slow_mo_ms,
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
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
