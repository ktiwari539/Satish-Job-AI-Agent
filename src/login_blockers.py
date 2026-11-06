"""Observe Google's browser rejection without navigating or exposing OAuth data."""
from urllib.parse import urlsplit


GOOGLE_BROWSER_REJECTED = 'google_browser_security_rejection'


def google_browser_rejection(url, text):
    try:
        parsed = urlsplit(str(url))
        trusted = (parsed.scheme == 'https' and parsed.hostname == 'accounts.google.com'
                   and not parsed.username and not parsed.password and parsed.port in (None, 443))
    except (TypeError, ValueError):
        return ''
    normalized = ' '.join(str(text).lower().split())
    if trusted and 'this browser or app may not be secure' in normalized:
        return GOOGLE_BROWSER_REJECTED
    return ''


def login_pages(page):
    try:
        return list(page.context.pages)[:20]
    except Exception:
        return [page]


def detect_login_blocker(page, *, extra_pages=(), include_popups=True):
    """Read the main page and at most four related/new login popups.

    Unrelated existing tabs cannot invalidate another portal's saved session.
    New pages may have no opener because of cross-origin opener isolation.
    Callers supply only tabs created during the current manual login.
    """
    candidates = [page]
    for candidate in login_pages(page) if include_popups else ():
        if candidate is page:
            continue
        try:
            parent = candidate.opener()
            related = parent is page or (parent is not None and parent.opener() is page)
        except Exception:
            related = False
        if related:
            candidates.append(candidate)
    candidates.extend(list(extra_pages)[:4])
    seen = set()
    for candidate in candidates:
        if id(candidate) in seen:
            continue
        seen.add(id(candidate))
        if len(seen) > 5:
            break
        try:
            # Avoid reading unrelated portal/account text at all.
            url = str(candidate.url)
            if urlsplit(url).hostname != 'accounts.google.com':
                continue
            text = candidate.locator('body').inner_text(timeout=1000)[:16000]
            reason = google_browser_rejection(url, text)
            if reason:
                return reason
        except Exception:
            continue
    return ''
