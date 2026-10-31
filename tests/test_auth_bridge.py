import hashlib
import hmac
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from urllib.request import Request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from auth_bridge import AuthProvider, AuthProviderUnavailable, AccountSecret, _GoogleResponseRedirect


class AuthBridgeTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.config=Path(self.folder.name)/'bridge.json'
        self.local=Path(self.folder.name)/'accounts.json'
        self.key='fixture-shared-key-with-at-least-32-characters'
        self.config.write_text(json.dumps(dict(endpoint='https://script.google.com/macros/s/FIXTURE/exec',shared_key=self.key)))

    def provider(self): return AuthProvider(str(self.config),str(self.local))

    def test_secret_values_are_not_in_representations(self):
        self.assertNotIn(self.key,repr(self.provider()))
        self.assertNotIn('private@example.invalid',repr(AccountSecret('private@example.invalid','private-pass')))
        self.assertNotIn('private-pass',repr(AccountSecret('private@example.invalid','private-pass')))

    def test_signed_post_contains_no_shared_key_or_query_credentials(self):
        response=MagicMock(); response.read.return_value=b'{"ok":true,"data":{"email":"fixture@example.invalid","password":"fixture-pass"}}'
        opener=MagicMock(); opener.open.return_value.__enter__.return_value=response
        with patch('auth_bridge.build_opener',return_value=opener):
            account=self.provider().credentials('linkedin')
        request=opener.open.call_args.args[0]
        data=json.loads(request.data)
        canonical='\n'.join(str(data[k]) for k in ('version','operation','portal','requested_at_ms','nonce','issued_after_ms','account_email'))
        self.assertEqual(data['signature'],hmac.new(self.key.encode(),canonical.encode(),hashlib.sha256).hexdigest())
        self.assertNotIn(self.key,request.data.decode())
        self.assertEqual(request.get_method(),'POST')
        self.assertEqual(account.password,'fixture-pass')

    def test_only_reviewed_google_deployments_are_accepted(self):
        for endpoint in ('http://script.google.com/macros/s/FIXTURE/exec','https://evil.invalid/macros/s/FIXTURE/exec',
                         'https://script.google.com/macros/s/FIXTURE/dev','https://script.google.com/macros/s/FIXTURE/exec?key=x'):
            self.config.write_text(json.dumps(dict(endpoint=endpoint,shared_key=self.key)))
            with self.assertRaises(AuthProviderUnavailable): self.provider()

    def test_bridge_failure_is_sanitized_and_never_tries_another_password(self):
        self.local.write_text(json.dumps({'linkedin':{'email':'old@example.invalid','password':'old-pass'}}))
        with patch('auth_bridge.build_opener',side_effect=RuntimeError('private-pass private@example.invalid')):
            with self.assertRaises(AuthProviderUnavailable) as failure: self.provider().credentials('linkedin')
        self.assertEqual(str(failure.exception),'bridge_request_unavailable')

    def test_shared_local_account_requires_explicit_portal_opt_in(self):
        self.config.unlink()
        payload={'external_default':{'email':'fixture@example.invalid','password':'fixture-pass'}}
        self.local.write_text(json.dumps(payload))
        with self.assertRaises(AuthProviderUnavailable): self.provider().credentials('indeed')
        payload['shared_portals']=['indeed']; self.local.write_text(json.dumps(payload))
        self.assertEqual(self.provider().credentials('indeed').password,'fixture-pass')
        with self.assertRaises(AuthProviderUnavailable): self.provider().credentials('linkedin')

    def test_old_future_or_malformed_email_codes_are_rejected(self):
        provider=self.provider()
        for data in ({'code':'123456','issued_at_ms':999}, {'code':'123456','issued_at_ms':2000001},
                     {'code':'123456','issued_at_ms':1000000}, {'code':'not-a-code','issued_at_ms':1999999}):
            with patch.object(provider,'_request',return_value=data),patch('auth_bridge.time.time',return_value=2000):
                with self.assertRaises(AuthProviderUnavailable): provider.email_otp('linkedin','fixture@example.invalid',1990000)
        with patch.object(provider,'_request',return_value={'code':'123456','issued_at_ms':1999999}),patch('auth_bridge.time.time',return_value=2000):
            self.assertEqual(provider.email_otp('linkedin','fixture@example.invalid',1990000),'123456')

    def test_response_redirect_drops_post_and_rejects_foreign_hosts(self):
        redirect=_GoogleResponseRedirect(); request=Request('https://script.google.com/macros/s/FIXTURE/exec',data=b'private-request')
        approved=redirect.redirect_request(request,None,302,'',{},'https://script.googleusercontent.com/macros/echo?fixture=1')
        self.assertEqual(approved.get_method(),'GET'); self.assertIsNone(approved.data)
        for url in ('https://evil.invalid/','http://script.googleusercontent.com/x','https://script.googleusercontent.com.evil.invalid/x'):
            with self.assertRaises(AuthProviderUnavailable): redirect.redirect_request(request,None,302,'',{},url)
