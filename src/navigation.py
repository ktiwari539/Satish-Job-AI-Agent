from urllib.parse import urlparse

from agent_trace import trace_event, trace_step


def bounded_goto(page, url: str, *, commit_timeout_ms: int = 12000, dom_timeout_ms: int = 3000):
    """Navigate without waiting indefinitely for SPA/network-heavy pages.

    A response commit is the hard requirement. DOMContentLoaded is best effort.
    If commit times out, only continue when the page has already reached the
    requested host (or a redirected non-empty host); otherwise re-raise.
    """
    trace_event(
        "navigation_start",
        requested_url=url,
        commit_timeout_ms=commit_timeout_ms,
        dom_timeout_ms=dom_timeout_ms,
    )
    with trace_step("navigation_commit", requested_url=url):
        try:
            page.goto(url, wait_until="commit", timeout=commit_timeout_ms)
        except Exception as exc:
            current = str(getattr(page, "url", "") or "")
            current_host = urlparse(current).netloc.lower()
            requested_host = urlparse(url).netloc.lower()
            trace_event(
                "navigation_commit_exception",
                requested_url=url,
                current_url=current,
                error_type=type(exc).__name__,
            )
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

    with trace_step("navigation_dom_ready", requested_url=url):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=dom_timeout_ms)
        except Exception as exc:
            trace_event(
                "navigation_dom_timeout_tolerated",
                requested_url=url,
                current_url=str(getattr(page, "url", "") or ""),
                error_type=type(exc).__name__,
            )
        try:
            page.wait_for_timeout(500)
        except Exception:
            pass

    final_url = str(getattr(page, "url", "") or url)
    trace_event("navigation_complete", requested_url=url, final_url=final_url)
    return final_url
