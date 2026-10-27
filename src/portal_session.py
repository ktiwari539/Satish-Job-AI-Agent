"""Normal portal login and explicit email-code challenges; never bypass security."""
import getpass
import re
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from auth_bridge import AuthProviderUnavailable
from browser_auth import _first_usable
from browser_portals import classify_linkedin_probe, classify_naukri_probe
from browser_qa import classify_generic_session
from navigation import bounded_goto


LOGIN_URLS = {'linkedin':'https://www.linkedin.com/login','naukri':'https://www.naukri.com/nlogin/login',
              'indeed':'https://secure.indeed.com/account/login'}
HOSTS = {'linkedin':('www.linkedin.com','linkedin.com'), 'naukri':('www.naukri.com','naukri.com'),
         'indeed':('secure.indeed.com','auth.indeed.com','www.indeed.com','in.indeed.com')}
USERS = ("#username","input[name='session_key']","input[type='email']","input[autocomplete='username']",
         "input[name='email']","input[name='username']","input[placeholder*='Email']","input[placeholder*='email']")
PASSWORDS = ("#password","input[name='session_password']","input[type='password']")
SUBMITS = ("button[type='submit']","input[type='submit']","button:text-is('Sign in')",
           "button:text-is('Login')","button:text-is('Continue')")
CODES = ("input[autocomplete='one-time-code']","input[name='pin']","input[name='verificationCode']",
         "input[name='otp']","input[name='code']","#input__email_verification_pin")


@dataclass(frozen=True)
class SessionResult:
    authenticated: bool
    state: str
    reason: str = ''
    login_attempts: int = 0
    verification_source: str = ''


def _origin_allowed(url,portal):
    try:
        parsed = urlsplit(url)
        return (parsed.scheme=='https' and parsed.hostname in HOSTS[portal] and not parsed.username
                and not parsed.password and parsed.port in (None,443))
    except (KeyError,ValueError,TypeError):
        return False


def _body(page):
    try:
        return page.locator('body').inner_text(timeout=1500)
    except Exception:
        return ''


def _challenge(page,portal):
    if not _origin_allowed(page.url,portal):
        return 'untrusted_auth_origin'
    text = _body(page).lower()
    if re.search(r'\bcaptcha\b|verify you are human|unusual traffic|access denied|authenticator app|security key',text):
        return 'security_challenge_requires_human'
    return ''


def auth_structure(page):
    """Counts only; never expose field values, email addresses or page text."""
    try:
        raw=page.evaluate("""() => {
          const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);
            return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
          const count=selector=>[...document.querySelectorAll(selector)].filter(visible).length;
          return {email_inputs:count('input[type="email"],input[autocomplete="username"]'),
            password_inputs:count('input[type="password"]'),code_inputs:count('input[autocomplete="one-time-code"]'),
            forms:count('form'),post_forms:count('form[method="post" i]'),
            submit_controls:count('button[type="submit"],input[type="submit"]'),iframes:count('iframe')};
        }""")
    except Exception:
        raw={}
    return {key:min(max(raw.get(key,0),0),100) if isinstance(raw,dict) and type(raw.get(key)) is int else 0
            for key in ('email_inputs','password_inputs','code_inputs','forms','post_forms','submit_controls','iframes')}


def _authenticated(page,portal):
    if not _origin_allowed(page.url,portal) or _challenge(page,portal):
        return False
    if portal == 'linkedin':
        text=_body(page).lower()
        return (classify_linkedin_probe(page.url,text).authenticated and
                sum(marker in text for marker in ('my network','messaging','notifications'))>=2)
    if portal == 'naukri':
        return classify_naukri_probe(page.url,_body(page)).authenticated
    return classify_generic_session(portal,page.url,_body(page)).status=='SESSION_CONFIRMED'


def _form_safe(control,portal):
    try:
        meta = control.evaluate("el => ({action: el.form?.action || '', method: (el.form?.method || '').toLowerCase()})")
        return isinstance(meta,dict) and meta.get('method')=='post' and _origin_allowed(meta.get('action',''),portal)
    except Exception:
        return False


def _settle(page,portal):
    # Rendering is retried, never the password/verification submit click.
    for _ in range(13):
        if _authenticated(page,portal) or _challenge(page,portal) or _first_usable(page,CODES)[0] is not None:
            return
        page.wait_for_timeout(250)


def terminal_code(portal):
    if not sys.stdin.isatty():
        return ''
    try:
        return getpass.getpass('Enter the current '+portal+' email verification code (hidden; Enter skips): ').strip()
    except (EOFError,KeyboardInterrupt):
        return ''


def ensure_portal_session(page,portal,provider,*,initial_authenticated=False,allow_login=True,otp_mode='auto',prompt=terminal_code):
    if initial_authenticated:
        return SessionResult(True,'AUTHENTICATED',verification_source='existing_session')
    if not allow_login:
        return SessionResult(False,'SESSION_REQUIRED','automatic_login_disabled')
    if portal not in LOGIN_URLS:
        return SessionResult(False,'SESSION_REQUIRED','login_adapter_unverified')
    # A challenge left from an earlier login has no trustworthy current-login
    # timestamp. Do not reload it or send the password again to get around it.
    current_path=urlsplit(str(page.url)).path.lower()
    if '/checkpoint' in current_path or '/challenge' in current_path or _first_usable(page,CODES)[0] is not None:
        return SessionResult(False,'HUMAN_ACTION_REQUIRED','existing_login_challenge_requires_human')
    # Do not put credentials onto a pre-existing CAPTCHA or a foreign domain.
    if _challenge(page,portal):
        return SessionResult(False,'HUMAN_ACTION_REQUIRED',_challenge(page,portal))
    try:
        account = provider.credentials(portal)
    except AuthProviderUnavailable as exc:
        return SessionResult(False,'CREDENTIALS_REQUIRED',str(exc))
    started = int(time.time()*1000)
    attempts = 0
    try:
        bounded_goto(page,LOGIN_URLS[portal])
        for stage in range(2):
            reason = _challenge(page,portal)
            if reason:
                return SessionResult(False,'HUMAN_ACTION_REQUIRED',reason,attempts)
            if _authenticated(page,portal):
                return SessionResult(True,'AUTHENTICATED',login_attempts=attempts,verification_source='password')
            user,_ = _first_usable(page,USERS)
            password,_ = _first_usable(page,PASSWORDS)
            submit,_ = _first_usable(page,SUBMITS)
            if submit is None or not _form_safe(submit,portal):
                return SessionResult(False,'LOGIN_BLOCKED','login_form_not_verified',attempts)
            action_label = submit.inner_text(timeout=1500).strip().lower()
            if re.search(r'create.?account|sign.?up|register|join now',action_label):
                return SessionResult(False,'ACCOUNT_REVIEW_REQUIRED','account_creation_requires_verified_adapter',attempts)
            if user is not None:
                if not _form_safe(user,portal):
                    return SessionResult(False,'LOGIN_BLOCKED','login_form_not_verified',attempts)
                user.fill(account.email,timeout=3000)
            if password is not None:
                if not _form_safe(password,portal) or attempts:
                    return SessionResult(False,'LOGIN_BLOCKED','password_retry_blocked',attempts)
                password.fill(account.password,timeout=3000)
                attempts += 1
            elif stage or user is None:
                return SessionResult(False,'LOGIN_BLOCKED','login_controls_unverified',attempts)
            submit.click(timeout=4000)
            _settle(page,portal)
            if password is not None or _first_usable(page,CODES)[0] is not None or _authenticated(page,portal):
                break
        if _authenticated(page,portal):
            return SessionResult(True,'AUTHENTICATED',login_attempts=attempts,verification_source='password')
        reason = _challenge(page,portal)
        if reason:
            return SessionResult(False,'HUMAN_ACTION_REQUIRED',reason,attempts)
        code_control,_ = _first_usable(page,CODES)
        submit,_ = _first_usable(page,SUBMITS)
        text = _body(page).lower()
        if (code_control is None or submit is None or not _form_safe(code_control,portal) or not _form_safe(submit,portal)
                or not re.search(r'email|e-mail',text) or re.search(r'sms|text message|phone number|reset.*password|create.*account',text)):
            return SessionResult(False,'LOGIN_BLOCKED','login_not_confirmed_or_unsupported_challenge',attempts)
        code,source = '',''
        if otp_mode=='auto':
            for _ in range(3):
                try:
                    code = provider.email_otp(portal,account.email,started)
                except AuthProviderUnavailable:
                    break
                if code:
                    source='email_bridge'; break
                page.wait_for_timeout(1000)
        if not code and otp_mode in ('auto','manual'):
            code = prompt(portal)
            source='manual'
        if not re.fullmatch(r'\d{4,8}',code or ''):
            return SessionResult(False,'EMAIL_OTP_REQUIRED','current_email_code_required',attempts)
        # The page may have changed during mailbox lookup or user input.
        if _challenge(page,portal) or not _form_safe(code_control,portal) or not _form_safe(submit,portal):
            return SessionResult(False,'HUMAN_ACTION_REQUIRED','verification_form_changed',attempts)
        code_control.fill(code,timeout=3000)
        submit.click(timeout=4000)
        _settle(page,portal)
        if _authenticated(page,portal):
            return SessionResult(True,'AUTHENTICATED',login_attempts=attempts,verification_source=source)
        return SessionResult(False,'LOGIN_BLOCKED','verification_not_confirmed',attempts)
    except Exception:
        return SessionResult(False,'LOGIN_BLOCKED','login_adapter_action_failed',attempts)
