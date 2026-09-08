import unittest
from unittest.mock import patch

from core import comfyui


class HistoryPollingTests(unittest.TestCase):
    workflow = {'9': {'class_type': 'SaveImage'}}

    def success(self):
        return {'p': {'outputs': {'9': {'images': [{'filename': 'test.png'}]}}}}

    def poll(self, replies, **kwargs):
        events = []
        iterator = iter(replies)
        def fetch(*args):
            events.append(('fetch', args))
            reply = next(iterator)
            if isinstance(reply, Exception):
                raise reply
            return reply
        with patch.object(comfyui, '_fetch_comfy_history', side_effect=fetch), \
                patch.object(comfyui.time, 'sleep', side_effect=lambda seconds: events.append(('sleep', seconds))):
            result = comfyui._poll_comfy_output_history('host', 'p', self.workflow, **kwargs)
        return result, events

    def test_first_success_pins_result_and_aliases(self):
        history = self.success()
        result, events = self.poll([history])
        self.assertEqual(set(result), {'history', 'prompt_history', 'outputs', 'extraction', 'image_infos', 'attempt_logs', 'last_history_fetch_error', 'save_image_node_ids'})
        self.assertIs(result['history'], history)
        self.assertIs(result['prompt_history'], history['p'])
        self.assertIs(result['outputs'], history['p']['outputs'])
        self.assertIs(result['image_infos'], result['extraction']['images'])
        self.assertEqual(result['extraction'], {
            'images': [{'filename': 'test.png', 'subfolder': '', 'type': 'output', '_debug_path': 'outputs.9.images[0]', '_node_id': '9'}],
            'image_like_fields': ['outputs.9.images[0]'],
            'save_nodes_with_outputs': ['9'], 'save_node_output_keys': {'9': ['images']},
            'output_node_ids': ['9'], 'output_keys_by_node': {'9': ['images']}})
        self.assertEqual(result['attempt_logs'], [{'attempt': 1, 'history_found': True, 'outputs_keys': ['9'], 'save_image_nodes_with_outputs': ['9']}])
        self.assertEqual(result['save_image_node_ids'], ['9'])
        self.assertEqual(result['last_history_fetch_error'], '')
        self.assertEqual(events, [('fetch', ('host', 'p'))])

    def test_retries_until_success_and_exact_sleep_order(self):
        result, events = self.poll([{}, {'p': {'status': 'success'}}, self.success()], max_attempts=5, interval_seconds=.25)
        self.assertEqual(events, [('fetch', ('host', 'p')), ('sleep', .25), ('fetch', ('host', 'p')), ('sleep', .25), ('fetch', ('host', 'p'))])
        self.assertEqual([x['attempt'] for x in result['attempt_logs']], [1, 2, 3])
        self.assertEqual([x['history_found'] for x in result['attempt_logs']], [False, True, True])

    def test_no_images_retries_for_empty_missing_and_nonfailure_records(self):
        for history in [None, {}, {'p': {}}, {'p': {'status': 'success'}},
                        {'p': {'status': {'completed': True}}},
                        {'p': {'outputs': {'9': {'text': ['no image']}}}}]:
            with self.subTest(history=history):
                result, events = self.poll([history] * 3, max_attempts=3, interval_seconds=0)
                self.assertEqual(result['image_infos'], [])
                self.assertEqual(len(result['attempt_logs']), 3)
                self.assertEqual(events.count(('sleep', 0)), 2)
                self.assertEqual(events[-1][0], 'fetch')
                self.assertIs(result['history'], history)
                self.assertEqual(result['last_history_fetch_error'], '')

    def test_fetch_error_clears_on_later_success_even_without_images(self):
        for later in [{}, self.success()]:
            with self.subTest(later=later), patch.object(comfyui.logger, 'debug') as log:
                result, events = self.poll([ValueError('offline'), later], max_attempts=2)
                self.assertEqual(result['last_history_fetch_error'], '')
                self.assertIs(result['history'], later)
                self.assertFalse(result['attempt_logs'][0]['history_found'])
                self.assertEqual(len(events), 3)
                self.assertEqual(log.call_count, 3)

    def test_repeated_fetch_errors_return_last_error_and_empty_state(self):
        result, events = self.poll([ValueError('first'), RuntimeError('last')], max_attempts=2)
        self.assertEqual(result['last_history_fetch_error'], 'last')
        for key in ['history', 'prompt_history', 'outputs']:
            self.assertEqual(result[key], {})
        self.assertEqual(result['image_infos'], [])
        self.assertEqual(result['attempt_logs'], [dict(attempt=i, history_found=False, outputs_keys=[], save_image_nodes_with_outputs=[]) for i in [1, 2]])
        self.assertEqual(events, [('fetch', ('host', 'p')), ('sleep', .75), ('fetch', ('host', 'p'))])

    def test_failure_status_exits_without_sleep(self):
        for status in ['failed', {'status_str': 'error'}, {'messages': [['execution_error', {}]]}]:
            with self.subTest(status=status):
                result, events = self.poll([{'p': {'status': status}}])
                self.assertEqual(len(result['attempt_logs']), 1)
                self.assertEqual(events, [('fetch', ('host', 'p'))])

    def test_images_take_precedence_over_status_check(self):
        with patch.object(comfyui, '_comfy_status_is_failure', side_effect=AssertionError('must not check')):
            result, _ = self.poll([self.success()])
        self.assertTrue(result['image_infos'])

    def test_single_attempt_and_nonpositive_attempts(self):
        result, events = self.poll([{}], max_attempts=1)
        self.assertEqual(events, [('fetch', ('host', 'p'))])
        self.assertEqual(len(result['attempt_logs']), 1)
        for attempts in [0, -1, False]:
            result, events = self.poll([], max_attempts=attempts)
            self.assertEqual(events, [])
            self.assertEqual(result['attempt_logs'], [])
            self.assertEqual(result['history'], {})
            self.assertEqual(result['last_history_fetch_error'], '')
            self.assertEqual(result['save_image_node_ids'], ['9'])
        with self.assertRaises(TypeError):
            self.poll([], max_attempts=1.5)

    def test_single_record_fallback_and_output_key_order(self):
        history = {'other': {'outputs': {'z': {'text': []}, 'a': {'text': []}}}}
        result, _ = self.poll([history], max_attempts=1)
        self.assertIs(result['prompt_history'], history['other'])
        self.assertEqual(result['attempt_logs'][0], dict(attempt=1, history_found=True, outputs_keys=['z', 'a'], save_image_nodes_with_outputs=[]))

    def test_downstream_exceptions_propagate_without_retry(self):
        for target in ['_history_prompt_record', '_history_outputs', '_extract_history_images', '_comfy_status_is_failure']:
            error = RuntimeError(target)
            with self.subTest(target=target), patch.object(comfyui, target, side_effect=error), \
                    patch.object(comfyui, '_fetch_comfy_history', return_value={'p': {'status': 'running'}}) as fetch, \
                    patch.object(comfyui.time, 'sleep') as sleep:
                with self.assertRaises(RuntimeError) as caught:
                    comfyui._poll_comfy_output_history('host', 'p', self.workflow)
                self.assertIs(caught.exception, error)
                fetch.assert_called_once()
                sleep.assert_not_called()

    def test_sleep_exception_propagates(self):
        error = ValueError('invalid interval')
        with patch.object(comfyui, '_fetch_comfy_history', return_value={}) as fetch, \
                patch.object(comfyui.time, 'sleep', side_effect=error) as sleep:
            with self.assertRaises(ValueError) as caught:
                comfyui._poll_comfy_output_history('host', 'p', {}, interval_seconds=-1)
            self.assertIs(caught.exception, error)
            sleep.assert_called_once_with(-1)
            fetch.assert_called_once()
