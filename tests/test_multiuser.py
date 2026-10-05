import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pipeline import db, report


class MultiUserAuthTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(db.SCHEMA)

    def test_user_signup_approval_and_password_verification(self):
        user = db.create_user(
            self.conn,
            email='alice@example.com',
            password='secret-pass',
            full_name='Alice Example',
            role='user',
            status='pending',
        )
        self.assertEqual(user['email'], 'alice@example.com')
        self.assertEqual(user['status'], 'pending')
        self.assertTrue(db.verify_password(self.conn, user['id'], 'secret-pass'))
        self.assertFalse(db.verify_password(self.conn, user['id'], 'wrong-pass'))

        db.approve_user(self.conn, user['id'], approved_by='admin@example.com')
        updated = db.get_user_by_email(self.conn, 'alice@example.com')
        self.assertEqual(updated['status'], 'approved')

        self.assertRaises(ValueError, db.create_user, self.conn,
                          'alice@example.com', 'anotherpass', 'Alice 2', 'user', 'pending')

    def test_export_is_scoped_and_uses_user_specific_files(self):
        alice = db.create_user(self.conn, 'alice@example.com', 'alice-pass',
                               username='alice', status='approved')
        bob = db.create_user(self.conn, 'bob@example.com', 'bob-pass',
                             username='bob', status='approved')
        for user, name, handle in ((alice, 'Alice Author', 'alicewrites'),
                                   (bob, 'Bob Author', 'bobwrites')):
            author = self.conn.execute(
                "INSERT INTO authors(user_id, display_name, heat_score, first_seen) VALUES (?,?,?,?)",
                (user['id'], name, 75, '2026-01-01'),
            ).lastrowid
            self.conn.execute(
                "INSERT INTO identities(user_id, author_id, platform, handle, norm, platform_url, spotted_count) VALUES (?,?,?,?,?,?,?)",
                (user['id'], author, 'reddit', handle, handle, f'https://reddit.com/u/{handle}', 1),
            )
        self.conn.commit()

        with tempfile.TemporaryDirectory() as output_dir:
            cfg = {'export': {
                'out_dir': output_dir,
                'csv': 'leads.csv',
                'report': 'leads_report.md',
            }}
            csv_path, md_path, total = report.export_all(
                self.conn, cfg, user_id=alice['id'])

            self.assertEqual(total, 1)
            self.assertIn(f'_user_{alice["id"]}', os.path.basename(csv_path))
            self.assertIn(f'_user_{alice["id"]}', os.path.basename(md_path))
            with open(csv_path, encoding='utf-8', newline='') as exported_csv:
                csv_text = exported_csv.read()
            with open(md_path, encoding='utf-8') as exported_report:
                report_text = exported_report.read()
            self.assertIn('Alice Author', csv_text)
            self.assertNotIn('Bob Author', csv_text)
            self.assertIn('Alice Author', report_text)
            self.assertNotIn('Bob Author', report_text)

    def test_legacy_records_are_assigned_to_default_admin(self):
        author_id = self.conn.execute(
            "INSERT INTO authors(display_name, first_seen) VALUES (?,?)",
            ('Legacy Author', '2026-01-01'),
        ).lastrowid
        self.conn.execute(
            "INSERT INTO identities(author_id, platform, handle, norm) VALUES (?,?,?,?)",
            (author_id, 'reddit', 'legacywriter', 'legacywriter'),
        )
        self.conn.commit()

        with patch.dict(os.environ, {
            'AUTHOR_OUTREACH_ADMIN_USERNAME': 'Tremendous',
            'AUTHOR_OUTREACH_ADMIN_PASSWORD': 'test-admin-password',
            'AUTHOR_OUTREACH_ADMIN_EMAIL': 'admin@example.com',
        }):
            admin = db.ensure_default_admin(self.conn)
        author = self.conn.execute(
            "SELECT user_id FROM authors WHERE id=?", (author_id,)
        ).fetchone()
        identity = self.conn.execute(
            "SELECT user_id FROM identities WHERE author_id=?", (author_id,)
        ).fetchone()

        self.assertEqual(admin['username'], 'Tremendous')
        self.assertEqual(admin['email'], 'admin@example.com')
        self.assertEqual(author['user_id'], admin['id'])
        self.assertEqual(identity['user_id'], admin['id'])

    def test_missing_admin_secret_does_not_crash_database_initialization(self):
        with patch.dict(os.environ, {}, clear=True):
            admin = db.ensure_default_admin(self.conn)

        self.assertIsNone(admin)


if __name__ == '__main__':
    unittest.main()
