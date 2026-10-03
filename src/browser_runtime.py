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
        if self.context is not None:
            self.context.close()
        if self._pw is not None:
            self._pw.stop()
