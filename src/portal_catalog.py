from dataclasses import dataclass
from urllib.parse import urlencode

from browser_portals import linkedin_search_url, naukri_search_url


@dataclass(frozen=True)
class PortalTarget:
    key: str
    name: str
    start_url: str
    authenticated: bool
    search_mode: str


PORTAL_TARGETS: dict[str, PortalTarget] = {
    "linkedin": PortalTarget("linkedin", "LinkedIn", "https://www.linkedin.com/jobs/", True, "query_url"),
    "naukri": PortalTarget("naukri", "Naukri", "https://www.naukri.com/", True, "query_url"),
    "indeed": PortalTarget("indeed", "Indeed", "https://in.indeed.com/jobs", True, "query_url"),
    "foundit": PortalTarget("foundit", "Foundit", "https://www.foundit.in/search/", True, "browser_form"),
    "instahyre": PortalTarget("instahyre", "Instahyre", "https://www.instahyre.com/", True, "authenticated_opportunities"),
    "cutshort": PortalTarget("cutshort", "Cutshort", "https://cutshort.io/jobs", True, "browser_form"),
    "wellfound": PortalTarget("wellfound", "Wellfound", "https://wellfound.com/jobs", True, "browser_form"),
    "hirist": PortalTarget("hirist", "Hirist", "https://www.hirist.tech/", True, "browser_form"),
    "glassdoor": PortalTarget("glassdoor", "Glassdoor", "https://www.glassdoor.co.in/Job/index.htm", True, "browser_form"),
    "greenhouse": PortalTarget("greenhouse", "Greenhouse", "", False, "public_feed"),
    "lever": PortalTarget("lever", "Lever", "", False, "public_feed"),
    "workday": PortalTarget("workday", "Workday", "", False, "company_specific"),
}


def build_search_url(portal: str, query: str, location: str = "") -> str:
    portal = portal.lower().strip()
    if portal == "linkedin":
        return linkedin_search_url(query, location)
    if portal == "naukri":
        return naukri_search_url(query, location)
    if portal == "indeed":
        params = {"q": query.strip()}
        if location.strip():
            params["l"] = location.strip()
        return "https://in.indeed.com/jobs?" + urlencode(params)
    if portal == "cutshort":
        params = {"q": query.strip()}
        if location.strip():
            params["location"] = location.strip()
        return "https://cutshort.io/jobs?" + urlencode(params)

    target = PORTAL_TARGETS.get(portal)
    if target is None:
        raise KeyError(f"unsupported portal: {portal}")
    return target.start_url
