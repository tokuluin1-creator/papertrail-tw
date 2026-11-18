import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from papertrail.agents import (Ollama, NoRedirect, Paragraph, inspect_draft,
                               plan_sections)
from papertrail.materials import Project, Source, reference_cards
from pathlib import Path


class SafetyTests(unittest.TestCase):
    def test_remote_rejected_before_network(self):
        with patch('papertrail.agents.build_opener') as network:
            for host in ('https://example.org', 'http://192.168.1.10:11434',
                         'http://localhost.example.org'):
                with self.assertRaisesRegex(ValueError, 'allow_remote'):
                    Ollama('m', host)
            network.assert_not_called()
        self.assertEqual(Ollama('m', 'https://example.org', allow_remote=True).url,
                         'https://example.org/api/chat')

    def test_loopback_and_invalid_hosts(self):
        self.assertEqual(Ollama('m', 'http://localhost:11434/').url,
                         'http://127.0.0.1:11434/api/chat')
        Ollama('m', 'http://[::1]:11434')
        for host in ('http://user:secret@localhost', 'http://localhost/path',
                     'http://localhost?x=1', 'http://localhost:wrong'):
            with self.assertRaises(ValueError):
                Ollama('m', host)

    def test_redirect_never_reaches_destination(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                received.append(self.path)
                self.send_response(302)
                self.send_header('Location', '/leaked')
                self.end_headers()
            def do_GET(self):
                received.append(self.path)
                self.send_response(200)
                self.end_headers()
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = Ollama('m', f'http://127.0.0.1:{server.server_port}')
                with self.assertRaisesRegex(ValueError, '重新導向'):
                    client.ask('writer', {'secret': 'private research'}, {})
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(received, ['/api/chat'])

    def test_reading_status_legacy_and_validation(self):
        card = dict(id='R-a', title='Title', reading_note='An author note',
                    locator='p. 1', note_citation='Citation', bibliography='Bibliography')
        self.assertEqual(next(reference_cards(json.dumps([card]))).reading_status, 'unverified')
        card['reading_status'] = 'full_text_read'
        self.assertEqual(next(reference_cards(json.dumps([card]))).reading_status, 'full_text_read')
        card['reading_status'] = 'verified'
        with self.assertRaisesRegex(ValueError, 'reading_status'):
            list(reference_cards(json.dumps([card])))

    def test_question_is_not_fact_evidence(self):
        q = '改革如何影響人員？'
        project = Project(Path('.'), 'Title', q, '', [], False, '', '', '',
                          {'Q': Source('Q', 'question', 'intro', q, 'project')}, [], {})
        plan = plan_sections(project, None)
        body = {r['id']: [] for r in plan}
        body['intro'] = [Paragraph(q, ['Q'])]
        body['results'] = [Paragraph('改革提升所有人員績效。', ['Q'])]
        findings = inspect_draft(project, plan, Paragraph(q, ['Q']), body, None)
        self.assertTrue(any(f[0] == 'results.1' and f[1] == '證據不足' for f in findings))
        self.assertFalse(any(f[0] == 'intro.1' and f[1] == '證據不足' for f in findings))


if __name__ == '__main__':
    unittest.main()
