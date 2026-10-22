import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import notify


class NotificationTests(unittest.TestCase):
    def test_retry_only_failed_recipient(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'data.json'
            output.write_text(json.dumps({'pending_notifications': {'url': {'title': 'Vídeo', 'url': 'https://www.jw.org/es/test/', 'kind': 'Nuevo', 'detected': '2026-10-22', 'delivered': []}}}), encoding='utf-8')
            env = {'SMTP_USERNAME': 'sender@example.com', 'SMTP_PASSWORD': 'test', 'MAIL_TO': 'one@example.com,two@example.com'}
            with patch.object(notify, 'OUTPUT', output), patch.dict(os.environ, env), patch.object(notify.smtplib, 'SMTP') as factory:
                smtp = factory.return_value.__enter__.return_value
                smtp.send_message.side_effect = [{}, OSError('failed')]
                with self.assertRaises(RuntimeError):
                    notify.run()
                self.assertEqual(len(json.loads(output.read_text())['pending_notifications']['url']['delivered']), 1)
                smtp.send_message.reset_mock()
                smtp.send_message.side_effect = None
                smtp.send_message.return_value = {}
                notify.run()
                self.assertEqual(smtp.send_message.call_count, 1)
                self.assertEqual(smtp.send_message.call_args.args[0]['To'], 'two@example.com')
                self.assertEqual(json.loads(output.read_text())['pending_notifications'], {})

    def test_no_news_does_not_connect(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'data.json'
            output.write_text('{"pending_notifications": {}}')
            with patch.object(notify, 'OUTPUT', output), patch.object(notify.smtplib, 'SMTP') as smtp:
                notify.run()
                smtp.assert_not_called()
