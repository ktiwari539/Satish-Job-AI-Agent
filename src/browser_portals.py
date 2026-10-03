import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode, urljoin

from browser_extractors import RawJobCard, normalize_browser_cards
from portal_adapter import FormInspection, LoginState


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "jobs"


def linkedin_search_url(query: str, location: str = "") -> str:
    params = {"keywords": query.strip()}
    if location.strip():
        params["location"] = location.strip()
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)


def naukri_search_url(query: str, location: str = "") -> str:
    base = f"https://www.naukri.com/{_slug(query)}-jobs"
    if location.strip():
        base += f"-in-{_slug(location)}"
    return base


def classify_linkedin_probe(url: str, body_text: str = "") -> LoginState:
    lowered = url.lower()
    text = " ".join(body_text.lower().split())

    if "/checkpoint/" in lowered or "challenge" in lowered or any(
        marker in text
        for marker in ("verify your identity", "security verification", "captcha")
    ):
        return LoginState(False, True, "linkedin_security_checkpoint")

    if "/login" in lowered or "/signup" in lowered:
        return LoginState(False, False, "linkedin_login_required")

    login_markers = ("email or phone", "password", "sign in")
    if sum(marker in text for marker in login_markers) >= 2:
        return LoginState(False, False, "linkedin_login_required")

    authenticated_url_markers = ("linkedin.com/feed", "linkedin.com/jobs", "linkedin.com/mynetwork")
    authenticated_text_markers = (
        "my network",
        "messaging",
        "notifications",
        "jobs",
        "me",
    )
    if any(marker in lowered for marker in authenticated_url_markers) and any(
        marker in text for marker in authenticated_text_markers
    ):
        return LoginState(True, False, "")

    return LoginState(False, False, "linkedin_session_not_confirmed")


def classify_naukri_probe(url: str, body_text: str) -> LoginState:
    lowered_url = url.lower()
    text = " ".join(body_text.lower().split())

    if any(token in text for token in ("captcha", "verify you are human", "security check")):
        return LoginState(False, True, "naukri_security_challenge")
    if any(token in lowered_url for token in ("/login", "/nlogin")):
        return LoginState(False, False, "naukri_login_required")

    logged_in_markers = ("logout", "view profile", "my naukri", "profile performance")
    if any(marker in text for marker in logged_in_markers):
        return LoginState(True, False, "")

    login_markers = ("login", "register", "email id", "password")
    if sum(marker in text for marker in login_markers) >= 2:
        return LoginState(False, False, "naukri_login_required")

    return LoginState(False, False, "naukri_session_not_confirmed")


@dataclass(frozen=True)
class BrowserFormSnapshot:
    body_text: str
    required_field_names: tuple[str, ...] = ()
    captcha_selector_found: bool = False


KNOWN_APPLICATION_FIELDS = {
    "name",
    "full name",
    "first name",
    "last name",
    "email",
    "email address",
    "phone",
    "mobile",
    "mobile number",
    "location",
    "city",
    "resume",
    "cv",
    "linkedin",
    "notice period",
    "experience",
    "years of experience",
}


def inspect_form_snapshot(snapshot: BrowserFormSnapshot) -> FormInspection:
    text = " ".join(snapshot.body_text.lower().split())
    captcha = snapshot.captcha_selector_found or any(
        marker in text
        for marker in ("captcha", "i'm not a robot", "verify you are human")
    )
    manual_auth = any(
        marker in text
        for marker in (
            "enter otp",
            "one-time password",
            "verification code",
            "authenticator app",
            "security key",
        )
    )

    unknown: list[str] = []
    for field in snapshot.required_field_names:
        normalized = " ".join(field.lower().split())
        if normalized and normalized not in KNOWN_APPLICATION_FIELDS:
            unknown.append(field)

    return FormInspection(
        supported=not captcha and not manual_auth,
        required_unknown_fields=tuple(unknown),
        captcha_present=captcha,
        manual_auth_required=manual_auth,
    )


def _first_text(locator, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        try:
            target = locator.locator(selector).first
            if target.count() and target.is_visible():
                value = target.inner_text(timeout=1500).strip()
                if value:
                    return value
        except Exception:
            continue
    return ""


def _first_attr(locator, selectors: tuple[str, ...], name: str) -> str:
    for selector in selectors:
        try:
            target = locator.locator(selector).first
            if target.count():
                value = (target.get_attribute(name, timeout=1500) or "").strip()
                if value:
                    return value
        except Exception:
            continue
    return ""


def _safe_card_count(page, selectors: tuple[str, ...]) -> tuple[Optional[object], int]:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
            if count:
                return locator, min(count, 100)
        except Exception:
            continue
    return None, 0


def extract_linkedin_cards(page) -> list[RawJobCard]:
    cards, count = _safe_card_count(
        page,
        (
            "li.scaffold-layout__list-item",
            "li.jobs-search-results__list-item",
            "div.job-card-container",
        ),
    )
    if cards is None:
        return []

    results: list[RawJobCard] = []
    for index in range(count):
        card = cards.nth(index)
        title = _first_text(
            card,
            (
                "a.job-card-list__title--link",
                "a.job-card-list__title",
                ".job-card-container__link",
            ),
        )
        company = _first_text(
            card,
            (
                ".artdeco-entity-lockup__subtitle",
                ".job-card-container__primary-description",
            ),
        )
        location = _first_text(
            card,
            (
                ".artdeco-entity-lockup__caption",
                ".job-card-container__metadata-item",
            ),
        )
        href = _first_attr(
            card,
            (
                "a.job-card-list__title--link",
                "a.job-card-list__title",
                ".job-card-container__link",
            ),
            "href",
        )
        data_id = _first_attr(card, ("[data-job-id]",), "data-job-id")
        if title and href:
            results.append(
                RawJobCard(
                    title=title,
                    company=company,
                    location=location,
                    url=urljoin("https://www.linkedin.com", href),
                    external_id=data_id,
                )
            )
    return results


def extract_naukri_cards(page) -> list[RawJobCard]:
    cards, count = _safe_card_count(
        page,
        (
            "article.jobTuple",
            "div.srp-jobtuple-wrapper",
            "div.cust-job-tuple",
        ),
    )
    if cards is None:
        return []

    results: list[RawJobCard] = []
    for index in range(count):
        card = cards.nth(index)
        title = _first_text(card, ("a.title", "a[title]", ".title"))
        company = _first_text(card, ("a.comp-name", ".comp-name", ".subTitle"))
        location = _first_text(card, (".locWdth", ".loc-wrap", ".location"))
        href = _first_attr(card, ("a.title", "a[title]"), "href")
        job_id = _first_attr(card, ("[data-job-id]",), "data-job-id")
        if title and href:
            results.append(
                RawJobCard(
                    title=title,
                    company=company,
                    location=location,
                    url=urljoin("https://www.naukri.com", href),
                    external_id=job_id,
                )
            )
    return results


class LinkedInBrowserAdapter:
    portal_key = "linkedin"
    LOGIN_PROBE_URL = "https://www.linkedin.com/feed/"

    def __init__(self, page):
        self.page = page

    def login_state(self) -> LoginState:
        self.page.goto(self.LOGIN_PROBE_URL, wait_until="domcontentloaded")
        try:
            body_text = self.page.locator("body").inner_text(timeout=5000)
        except Exception:
            body_text = ""
        return classify_linkedin_probe(self.page.url, body_text)

    def open_search(self, query: str, location: str = "") -> str:
        url = linkedin_search_url(query, location)
        self.page.goto(url, wait_until="domcontentloaded")
        return url

    def extract_search_results(self, taxonomy: tuple[str, ...]):
        return normalize_browser_cards("linkedin", extract_linkedin_cards(self.page), taxonomy)


class NaukriBrowserAdapter:
    portal_key = "naukri"
    LOGIN_PROBE_URL = "https://www.naukri.com/"

    def __init__(self, page):
        self.page = page

    def login_state(self) -> LoginState:
        self.page.goto(self.LOGIN_PROBE_URL, wait_until="domcontentloaded")
        try:
            body_text = self.page.locator("body").inner_text(timeout=5000)
        except Exception:
            body_text = ""
        return classify_naukri_probe(self.page.url, body_text)

    def open_search(self, query: str, location: str = "") -> str:
        url = naukri_search_url(query, location)
        self.page.goto(url, wait_until="domcontentloaded")
        return url

    def extract_search_results(self, taxonomy: tuple[str, ...]):
        return normalize_browser_cards("naukri", extract_naukri_cards(self.page), taxonomy)
