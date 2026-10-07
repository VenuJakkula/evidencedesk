import csv
import io
import tempfile
import unittest
from pathlib import Path
from app.core import Store

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name)/'test.db')
    def seed(self, tenant='a', expiry='2099-01-01'):
        return self.store.add_document(tenant, 'Policy', 'Customer data is encrypted at rest using AES-256.', '1', expiry)
    def test_evidence_and_restart(self):
        doc = self.seed()
        answer = self.store.draft('a', 'Is customer data encrypted at rest?')
        self.assertEqual(answer['evidence'][0]['document_id'], doc)
        reopened = Store(self.store.path)
        self.assertEqual(reopened.get('a', answer['id'])['status'], 'needs_review')
    def test_tenant_isolation(self):
        self.seed('a')
        answer = self.store.draft('b', 'Is customer data encrypted at rest?')
        self.assertEqual(answer['status'], 'needs_evidence')
        with self.assertRaises(KeyError):
            self.store.get('a', answer['id'])
    def test_expired_evidence_excluded(self):
        self.seed(expiry='2000-01-01')
        self.assertEqual(self.store.draft('a', 'Is customer data encrypted?')['status'], 'needs_evidence')
    def test_unknown_abstains_and_cannot_approve(self):
        self.seed()
        answer = self.store.draft('a', 'Is biometric authentication available?')
        with self.assertRaises(ValueError):
            self.store.approve('a', answer['id'], 'reviewer', 'Yes')
        self.assertEqual(len(list(csv.reader(io.StringIO(self.store.export('a'))))), 1)
    def test_export_requires_approval_and_sanitizes_formula(self):
        self.seed()
        answer = self.store.draft('a', '= Is customer data encrypted?')
        self.assertNotIn(answer['question'], self.store.export('a'))
        self.store.approve('a', answer['id'], 'reviewer', '=HYPERLINK("bad")')
        rows = list(csv.reader(io.StringIO(self.store.export('a'))))
        self.assertTrue(rows[1][0].startswith("'="))
        self.assertTrue(rows[1][1].startswith("'="))
        with self.assertRaises(ValueError):
            self.store.approve('a', answer['id'], 'reviewer', 'repeated')
    def test_other_tenant_cannot_approve(self):
        self.seed()
        answer = self.store.draft('a', 'Is customer data encrypted?')
        with self.assertRaises(ValueError):
            self.store.approve('b', answer['id'], 'reviewer', 'Yes')

if __name__ == '__main__':
    unittest.main()
