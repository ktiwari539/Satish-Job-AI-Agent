from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import sys
import json
import re
import platform
from importlib import metadata


def runtime_metadata(profile_dir=None):
    """Version numbers only; never return paths, cookies or profile contents."""
    info = {"system": platform.system(), "architecture": platform.machine()}
    try:
        info["playwright_version"] = metadata.version("playwright")
        import playwright
        path = Path(playwright.__file__).parent / "driver/package/browsers.json"
        browsers = json.loads(path.read_text(encoding="utf-8"))["browsers"]
        chromium = next(item for item in browsers if item.get("name") == "chromium")
        for field, key in (("revision", "chromium_revision"), ("browserVersion", "chromium_version")):
            value = str(chromium.get(field, ""))
            if re.fullmatch(r"[0-9.]{1,40}", value):
                info[key] = value
    except (ImportError, OSError, ValueError, KeyError, StopIteration, metadata.PackageNotFoundError):
        pass
    if profile_dir is not None:
        try:
            path = Path(profile_dir) / "Last Version"
            if path.stat().st_size <= 128:
                version = path.read_text(encoding="utf-8").strip()
                if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,4}", version):
                    info["profile_browser_version"] = version
        except (OSError, UnicodeError):
            pass
    return info


class BrowserRuntimeUnavailable(RuntimeError):
    def __init__(self, message="Browser runtime unavailable", *, reason_code="browser_runtime_unavailable", details=None):
        super().__init__(message)
        self.reason_code = reason_code
        self.details = details or {}

    def diagnostics(self):
        """Static remediation only; never expose browser errors, profile paths or PII."""
        result = {
            "reason_code": self.reason_code,
            "reason": {
                "playwright_import_failed": "Playwright cannot be imported by the active Python interpreter.",
                "chromium_not_installed": "The Chromium executable for this Playwright installation is missing.",
                "browser_profile_in_use": "The saved agent browser profile is already open.",
                "playwright_outdated": "The installed Playwright predates the supported local runtime.",
                "browser_profile_version_newer": "This browser is older than the saved profile's browser version.",
                "browser_architecture_mismatch": "The browser or driver cannot execute on this architecture.",
                "browser_profile_permission_denied": "The browser profile cannot be opened with current permissions.",
                "browser_os_dependency_missing": "A required operating-system browser component is missing.",
                "browser_launch_timeout": "The browser did not launch within the bounded startup deadline.",
                "browser_connection_lost": "The browser closed or disconnected during the run.",
            }.get(self.reason_code, "The local browser runtime could not start."),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "virtual_environment_active": sys.prefix != sys.base_prefix,
            "project_virtualenv_available": Path(".venv/bin/python").is_file(),
            "next_action": {
                "playwright_import_failed": "use_project_virtualenv_or_install_playwright_in_this_interpreter",
                "chromium_not_installed": "install_chromium_with_the_same_python_interpreter",
                "browser_profile_in_use": "close_the_agent_browser_then_retry_without_deleting_profile",
                "playwright_outdated": "run_setup_to_upgrade_playwright_without_clearing_profile",
                "browser_profile_version_newer": "upgrade_browser_runtime_to_match_profile_do_not_delete_profile",
                "browser_architecture_mismatch": "install_a_browser_runtime_matching_this_system_architecture",
                "browser_profile_permission_denied": "restore_local_profile_access_do_not_clear_profile",
                "browser_os_dependency_missing": "repair_local_browser_os_dependencies",
                "browser_launch_timeout": "inspect_safe_launch_signals_and_close_stuck_agent_browser",
                "browser_connection_lost": "restart_the_agent_with_the_saved_profile",
            }.get(self.reason_code, "inspect_browser_runtime_setup"),
            "runtime": self.details or runtime_metadata(),
        }
        if self.details.get("clean_profile_launch") == "passed":
            result["next_action"] = "inspect_saved_profile_launch_without_resetting_it"
        return result


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
    info = runtime_metadata()
    version = str(info.get("playwright_version", ""))
    if re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version) and tuple(map(int, version.split(".")[:2])) < (1, 55):
        raise BrowserRuntimeUnavailable("Playwright runtime upgrade required.", reason_code="playwright_outdated", details=info)


def _launch_failure(exc, *, details=None, phase="browser_launch"):
    message = str(exc).lower()
    if "executable doesn't exist" in message or "executable does not exist" in message:
        code = "chromium_not_installed"
    elif any(token in message for token in ("processsingleton", "singletonlock", "user data directory is already in use")):
        code = "browser_profile_in_use"
    elif any(token in message for token in ("profile is from a newer version", "profile was created by a newer version", "profile cannot be used because it is from a newer version")):
        code = "browser_profile_version_newer"
    elif "bad cpu type" in message or "exec format error" in message:
        code = "browser_architecture_mismatch"
    elif "permission denied" in message or "eacces" in message:
        code = "browser_profile_permission_denied"
    elif "error while loading shared libraries" in message or "library not loaded" in message:
        code = "browser_os_dependency_missing"
    elif "timeout" in message or "timed out" in message:
        code = "browser_launch_timeout"
    else:
        code = "browser_launch_failed"
    info = dict(details or {})
    info["launch_phase"] = phase
    info["launch_signals"] = {
        "target_closed": "target page, context or browser has been closed" in message,
        "browser_process_exited": "process did exit" in message or "process exited" in message,
        "crashpad_database_required": "crashpad" in message and "--database is required" in message,
        "os_version_unsupported": "unsupported macos" in message or "requires macos" in message,
    }
    match = re.search(r"exitcode[=: ]+(-?\d{1,5})", message)
    if match:
        info["browser_exit_code"] = int(match.group(1))
    match = re.search(r"\b(SIGKILL|SIGTRAP|SIGABRT|SIGSEGV|SIGTERM|SIGBUS)\b", str(exc))
    if match:
        info["browser_exit_signal"] = match.group(1)
    return BrowserRuntimeUnavailable("Chromium could not start; check the reported setup action.", reason_code=code, details=info)


def _probe_clean_browser(*, headless):
    """Isolate an unknown startup failure using one blank ephemeral browser.

    Never opens the saved profile or visits a portal. This is diagnosis, not
    an automatic retry of an application or a claim that authentication works.
    """
    driver = browser = None
    try:
        driver = _load_sync_playwright()().start()
        browser = driver.chromium.launch(headless=headless, timeout=8000)
        return {"clean_profile_launch": "passed"}
    except Exception as exc:
        return {"clean_profile_launch": "failed",
                "clean_profile_reason_code": _launch_failure(exc).reason_code}
    finally:
        for instance, method in ((browser, "close"), (driver, "stop")):
            if instance is not None:
                try:
                    getattr(instance, method)()
                except Exception:
                    pass


@dataclass(frozen=True)
class BrowserRuntimeConfig:
    user_data_dir: str = "browser-profile"
    headless: bool = False
    slow_mo_ms: int = 125
    launch_timeout_ms: int = 15000


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
        info = runtime_metadata(profile_dir)
        phase = "profile_preflight"
        try:
            profile_dir.mkdir(parents=True, exist_ok=True)
            previous = str(info.get("profile_browser_version", ""))
            current = str(info.get("chromium_version", ""))
            if previous and current and int(previous.split(".")[0]) > int(current.split(".")[0]):
                raise BrowserRuntimeUnavailable("Browser/profile downgrade blocked before launch.",
                    reason_code="browser_profile_version_newer", details=info)
            phase = "driver_start"
            self._pw = sync_playwright().start()
            phase = "browser_launch"
            self.context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=self.config.headless,
                slow_mo=self.config.slow_mo_ms,
                timeout=max(1000, min(60000, int(getattr(self.config, "launch_timeout_ms", 15000)))),
            )
            phase = "page_creation"
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        except Exception as exc:
            # __exit__ is not called when __enter__ raises. Stop the driver
            # here so missing executables/profile locks cannot leak processes.
            self.__exit__(type(exc), exc, None)
            if isinstance(exc, BrowserRuntimeUnavailable):
                raise
            failure = _launch_failure(exc, details=info, phase=phase)
            if failure.reason_code == "browser_launch_failed" and phase == "browser_launch":
                failure.details.update(_probe_clean_browser(headless=self.config.headless))
            raise failure from exc
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
