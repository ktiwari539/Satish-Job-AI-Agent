"""Validate browser-export job identity without preserving tracking tokens."""
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


def canonical_export_job_url(portal, raw):
    if portal not in ('naukri', 'indeed') or not isinstance(raw, str) or len(raw) > 10000:
        return ''
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname or ''
        domain = portal + '.com'
        if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
                or not (host == domain or host.endswith('.' + domain))):
            return ''
        if portal == 'naukri':
            if not parsed.path.startswith(('/job-listings-', '/job-listings/')):
                return ''
            return urlunsplit(('https', parsed.netloc.lower(), parsed.path, '', ''))
        if host in ('secure.indeed.com', 'auth.indeed.com', 'accounts.indeed.com'):
            return ''
        if parsed.path not in ('/viewjob', '/m/viewjob', '/rc/clk', '/jobs', '/'):
            return ''
        query = parse_qs(parsed.query, keep_blank_values=True)
        keys, selected = query.get('jk', []), query.get('vjk', [])
        if len(keys) > 1 or len(selected) > 1 or (keys and selected and keys != selected):
            return ''
        identity = (keys or selected or [''])[0]
        if not re.fullmatch('[a-fA-F0-9]{16}', identity):
            return ''
        return urlunsplit(('https', parsed.netloc.lower(), '/viewjob', urlencode({'jk': identity.lower()}), ''))
    except (ValueError, TypeError):
        return ''
