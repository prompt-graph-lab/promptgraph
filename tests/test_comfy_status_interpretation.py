import unittest
from core.comfy_status_interpretation import _comfy_status_summary, _comfy_status_is_failure


class StatusInterpretationTests(unittest.TestCase):
    def test_summary_none_vs_falsey_and_message_alias(self):
        messages = [('ok', {})]
        self.assertIs(_comfy_status_summary({'status': {'messages': messages}})[1], messages)
        for value, expected in [(None, 'completed'), ('', 'unknown'), (False, 'unknown'), (0, 'unknown')]:
            self.assertEqual(_comfy_status_summary({'status': {'status_str': value, 'completed': True}}), (expected, []))
        self.assertEqual(_comfy_status_summary({'status': {'messages': ('error',)}}), ('unknown', []))
        self.assertEqual(_comfy_status_summary({'status': 7}), ('7', []))

    def test_exact_failure_vocabulary_and_message_shapes(self):
        for value in ['ERROR', 'failed', 'Failure']:
            self.assertTrue(_comfy_status_is_failure({'status': value}))
        for value in [' error ', 'execution_error', 'not_completed']:
            self.assertFalse(_comfy_status_is_failure({'status': value}))
        for message in [['EXECUTION_ERROR'], ('Error',), ['failed']]:
            self.assertTrue(_comfy_status_is_failure({'status': {'messages': [message]}}))
        for message in [[], (), 'error', None, ['failure'], [' failed ']]:
            self.assertFalse(_comfy_status_is_failure({'status': {'messages': [message]}}))
