import ssl
import unittest
from unittest.mock import patch

from mvision.network import tls_context, https_open


class HTTPSVerificationTests(unittest.TestCase):
    def tearDown(self):
        tls_context.cache_clear()

    def test_context_requires_valid_certificate_and_hostname(self):
        context = tls_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_missing_truststore_keeps_verified_standard_context(self):
        tls_context.cache_clear()
        with patch.dict('sys.modules', {'truststore': None}):
            context = tls_context()
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_request_receives_explicit_verified_context(self):
        with patch('mvision.network.urlopen') as opener:
            https_open('https://example.org', timeout=12)
        self.assertEqual(opener.call_args.kwargs['timeout'], 12)
        self.assertIs(opener.call_args.kwargs['context'], tls_context())
