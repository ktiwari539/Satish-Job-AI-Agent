from urllib.parse import urlparse


def bounded_goto(page, url: str, *, commit_timeout_ms: int = 12000, dom_timeout_ms: int = 3000):
    """Navigate without waiting indefinitely for SPA/network-heavy pages.

    A response commit is the hard requirement. DOMContentLoaded is best effort.
    If commit times out, only continue when the page has already reached the
    requested host (or a redirected non-empty host); otherwise re-raise.
    """
    try:
        page.goto(url, wait_until="commit", timeout=commit_timeout_ms)
    except Exception:
        current = str(getattr(page, "url", "") or "")
        current_host = urlparse(current).netloc.lower()
        requested_host = urlparse(url).netloc.lower()
        if not current_host:
            raise
        if requested_host and current_host == requested_host:
            pass
        elif requested_host and current_host and current_host != requested_host:
            # Redirects are allowed only after the browser has actually left
            # the source URL; caller-specific validation still applies later.
            pass
        else:
            raise

    try:
        page.wait_for_load_state("domcontentloaded", timeout=dom_timeout_ms)
    except Exception:
        pass
    try:
        page.wait_for_timeout(500)
    except Exception:
        pass
    return str(getattr(page, "url", "") or url)
