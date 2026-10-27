"""Local secret provider and authenticated Google Apps Script transport.

No secrets are accepted on command lines, logged, included in reprs or reports.
"""
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from local_credentials import load_portal_credentials


class AuthProviderUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class AccountSecret:
    email: str = field(repr=False)
    password: str = field(repr=False)


class _GoogleResponseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if (parsed.scheme != 'https' or parsed.hostname != 'script.googleusercontent.com'
                or parsed.username or parsed.password or parsed.port not in (None,443)):
            raise AuthProviderUnavailable('bridge_redirect_rejected')
        # ContentService's response redirect is GET; never forward the signed POST.
        if code not in (301,302,303):
            raise AuthProviderUnavailable('bridge_redirect_rejected')
        return Request(newurl,method='GET',headers={'Accept':'application/json'})


class AuthProvider:
    def __init__(self, config_path='data/auth_bridge.json', credentials_path='data/portal_credentials.json'):
        self.credentials_path = str(credentials_path)
        path = Path(config_path)
        self.config = {}
        if path.exists():
            try:
                self.config = json.loads(path.read_text())
                if not isinstance(self.config,dict):
                    raise ValueError()
                parsed = urlsplit(self.config.get('endpoint',''))
                import re
                if (parsed.scheme != 'https' or parsed.hostname != 'script.google.com' or parsed.query or parsed.fragment
                        or parsed.username or parsed.password or parsed.port not in (None,443)
                        or not re.fullmatch(r'/macros/s/[A-Za-z0-9_-]+/exec',parsed.path)
                        or not isinstance(self.config.get('shared_key'),str) or len(self.config['shared_key']) < 32):
                    raise ValueError()
            except (OSError,ValueError,TypeError,AttributeError):
                raise AuthProviderUnavailable('bridge_configuration_invalid') from None

    def __repr__(self):
        return 'AuthProvider(configured='+str(bool(self.config))+')'

    def _request(self,operation,portal,*,issued_after_ms=0,account_email=''):
        if portal not in ('linkedin','naukri','indeed') or operation not in ('credentials','email_otp'):
            raise AuthProviderUnavailable('unsupported_auth_operation')
        payload = dict(version=1,operation=operation,portal=portal,requested_at_ms=int(time.time()*1000),
                       nonce=secrets.token_hex(16),issued_after_ms=int(issued_after_ms),account_email=account_email)
        canonical = '\n'.join(str(payload[k]) for k in ('version','operation','portal','requested_at_ms','nonce','issued_after_ms','account_email'))
        payload['signature'] = hmac.new(self.config['shared_key'].encode(),canonical.encode(),hashlib.sha256).hexdigest()
        request = Request(self.config['endpoint'],data=json.dumps(payload).encode(),method='POST',
                          headers={'Content-Type':'application/json','Accept':'application/json'})
        try:
            with build_opener(_GoogleResponseRedirect()).open(request,timeout=12) as response:
                raw = response.read(65537)
            if len(raw)>65536:
                raise ValueError()
            result = json.loads(raw)
            if not isinstance(result,dict) or result.get('ok') is not True or not isinstance(result.get('data'),dict):
                raise ValueError()
            return result['data']
        except Exception:
            raise AuthProviderUnavailable('bridge_request_unavailable') from None

    def credentials(self,portal):
        if self.config:
            data = self._request('credentials',portal)
            email,password = data.get('email'),data.get('password')
            if not isinstance(email,str) or not isinstance(password,str) or not email.strip() or not password:
                raise AuthProviderUnavailable('portal_credentials_missing')
            return AccountSecret(email.strip(),password)
        try:
            try:
                local = load_portal_credentials(self.credentials_path,portal)
            except ValueError:
                payload = json.loads(Path(self.credentials_path).read_text())
                # Existing external_default is not implicitly a password for another service.
                allowed = payload.get('shared_portals',[]) if isinstance(payload,dict) else []
                if portal not in allowed:
                    raise ValueError()
                local = load_portal_credentials(self.credentials_path,'external_default')
            return AccountSecret(local.email,local.password)
        except (OSError,ValueError,TypeError):
            raise AuthProviderUnavailable('portal_credentials_missing') from None

    def email_otp(self,portal,email,issued_after_ms):
        if not self.config:
            return ''
        data = self._request('email_otp',portal,issued_after_ms=issued_after_ms,account_email=email)
        code = data.get('code','')
        stamp = data.get('issued_at_ms',0)
        import re
        if code == '':
            return ''
        now = int(time.time()*1000)
        if (not isinstance(code,str) or not re.fullmatch(r'\d{4,8}',code) or type(stamp) is not int
                or not issued_after_ms <= stamp <= now or now-stamp>300000):
            raise AuthProviderUnavailable('email_verification_evidence_invalid')
        return code
