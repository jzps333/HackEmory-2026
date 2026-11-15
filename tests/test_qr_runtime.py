"""Offline regression coverage for the retained scanner and isolation guards."""
import unittest
from unittest.mock import patch
import httpx
from fastapi import HTTPException
from api import scan
from api.schema import JevChecks
from sandbox.netguard import is_public_ip, url_allowed

class QRRuntimeTest(unittest.TestCase):
    def test_sensitive_network_destinations_are_refused(self):
        for address in ('127.0.0.1','10.0.0.1','169.254.169.254','::1','fc00::1','100.64.0.1'):
            with self.subTest(address=address):
                self.assertFalse(is_public_ip(address))
        for url in ('http://localhost','http://2130706433','http://0x7f000001','file:///etc/passwd','http://user:pass@example.com'):
            with self.subTest(url=url):
                self.assertFalse(url_allowed(url, lambda host:['8.8.8.8'])[0])
        self.assertTrue(url_allowed('https://example.com',lambda host:['8.8.8.8'])[0])
        self.assertFalse(url_allowed('https://example.com',lambda host:['8.8.8.8','10.0.0.1'])[0])
    def test_scan_refuses_non_web_payloads(self):
        for url in ('solana:wallet','javascript:alert(1)','https://user:pass@example.com','https://['):
            with self.subTest(url=url), self.assertRaises(HTTPException):
                scan.scan(url)
    def test_worker_errors_are_never_safe(self):
        with patch('api.config.SANDBOX_URL','http://worker.invalid'):
            with patch('api.scan.run_sandbox',side_effect=httpx.ConnectError('offline')):
                self.assertEqual(scan.scan('https://example.com').verdict,'suspicious')
            for evidence in ({'error':'blocked: non-public address'}, {}, [], {'page_text': ''}):
                with patch('api.scan.run_sandbox',return_value=evidence):
                    self.assertEqual(scan.scan('https://example.com').verdict,'suspicious')
    def test_ai_cannot_override_hard_risk_floors(self):
        low=JevChecks(malicious_p=.01)
        self.assertEqual(scan.decide(low,tried_download=True)[0],'malicious')
        self.assertEqual(scan.decide(JevChecks(malicious_p=.01,prompt_injection_p=.8))[0],'malicious')
        self.assertEqual(scan.decide(low,bot_check=True)[0],'suspicious')

if __name__=='__main__':
    unittest.main()
