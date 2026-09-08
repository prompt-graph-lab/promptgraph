import copy
import unittest

from core.comfyui import _looks_like_comfy_image_record as recognizes
from core.comfyui import _collect_image_outputs as collect
from core.comfyui import _extract_history_images as extract


class ImageOutputTests(unittest.TestCase):
    def test_recognition_exact_extensions_and_paths(self):
        for value in [None, [], 'x.png', {}, {'filename': ''}, {'filename': 3}]:
            self.assertFalse(recognizes(value))
        for name in ['a.' + ext for ext in ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'PNG', 'JpEg']] + ['../a.png', 'dir/a.png', 'C:\\a.png', ' .png', 'a\n.png']:
            with self.subTest(name=name):
                self.assertTrue(recognizes({'filename': name}))
        for name in ['a', '.png', 'a.svg', 'a.png ', 'a.png?x', 'a.tiff']:
            self.assertFalse(recognizes({'filename': name}))

    def test_collection_order_paths_defaults_and_fields(self):
        value = {'gifs': [{'filename': 'a.gif', 'extra': 1}],
                 'nested': [{'images': [None, {'filename': 'b.png', 'subfolder': None, 'type': ''}]}],
                 'images': [{'filename': 'c.jpg', 'subfolder': 'sub', 'type': 'temp'}]}
        before = copy.deepcopy(value)
        images, paths = collect(value, 'root')
        self.assertEqual(paths, ['root.gifs[0]', 'root.nested[0].images[1]', 'root.images[0]'])
        self.assertEqual(images, [
            dict(filename='a.gif', subfolder='', type='output', _debug_path=paths[0]),
            dict(filename='b.png', subfolder=None, type='', _debug_path=paths[1]),
            dict(filename='c.jpg', subfolder='sub', type='temp', _debug_path=paths[2])])
        self.assertEqual(value, before)

    def test_list_key_stops_recursion_but_other_containers_recurse(self):
        self.assertEqual(collect({'images': [{'images': [{'filename': 'hidden.png'}]}, [{'filename': 'also.png'}]]}), ([], []))
        images, paths = collect([{'images': {'nested': {'gifs': [{'filename': 'a.gif'}]}}}])
        self.assertEqual(paths, ['[0].images.nested.gifs[0]'])
        self.assertEqual(images[0]['filename'], 'a.gif')
        for value in [{'filename': 'direct.png'}, [{'filename': 'direct.png'}], {'unrelated': [1, {}]}]:
            self.assertEqual(collect(value), ([], []))

    def test_empty_result_structure(self):
        expected = dict(images=[], image_like_fields=[], save_nodes_with_outputs=[], save_node_output_keys={}, output_node_ids=[], output_keys_by_node={})
        for outputs in [None, [], '', {}]:
            self.assertEqual(extract(outputs, []), expected)

    def test_save_nodes_precedence_and_all_ordered_metadata(self):
        outputs = {'preview': {'images': [{'filename': 'preview.png'}]},
                   '2': {'text': [], 'images': [{'filename': 'two.png'}]},
                   '1': {'gifs': [{'filename': 'one.gif'}]}, 'bad': None,
                   'empty': {'text': []}}
        before = copy.deepcopy(outputs)
        result = extract(outputs, [1, 'empty', 2, 'absent', 'bad'])
        self.assertEqual(result['output_node_ids'], ['preview', '2', '1', 'bad', 'empty'])
        self.assertEqual(list(result['output_keys_by_node']), ['preview', '2', '1', 'empty'])
        self.assertEqual(result['output_keys_by_node']['2'], ['text', 'images'])
        self.assertEqual(list(result['save_node_output_keys']), ['1', 'empty', '2'])
        self.assertEqual(result['save_nodes_with_outputs'], ['1', '2'])
        self.assertEqual([i['filename'] for i in result['images']], ['one.gif', 'two.png'])
        self.assertEqual(result['image_like_fields'], ['outputs.1.gifs[0]', 'outputs.2.images[0]'])
        self.assertEqual(outputs, before)

    def test_fallback_only_when_no_configured_images(self):
        outputs = {'save': {'text': []}, 'preview': {'images': [{'filename': 'p.png'}]}, 'bad': 4}
        for ids in [[], None, ['save', 'absent', 'bad']]:
            result = extract(outputs, ids)
            self.assertEqual([i['_node_id'] for i in result['images']], ['preview'])
            self.assertEqual(result['save_nodes_with_outputs'], [])
        self.assertEqual(extract(outputs, ['save'])['save_node_output_keys'], {'save': ['text']})

    def test_dedup_first_wins_and_default_interaction(self):
        outputs = {'a': {'images': [{'filename': 'same.png'}, {'filename': 'same.png', 'subfolder': '', 'type': 'output'},
                                    {'filename': 'same.png', 'subfolder': 'sub'}, {'filename': 'same.png', 'type': 'temp'}]},
                   'b': {'images': [{'filename': 'same.png'}]}}
        result = extract(outputs, [])
        self.assertEqual(len(result['images']), 3)
        self.assertEqual([i['_node_id'] for i in result['images']], ['a'] * 3)
        self.assertEqual([i['_debug_path'] for i in result['images']], ['outputs.a.images[0]', 'outputs.a.images[2]', 'outputs.a.images[3]'])
        self.assertEqual(len(result['image_like_fields']), 5)
        result = extract(outputs, ['b', 'a', 'b'])
        self.assertEqual(result['images'][0]['_node_id'], 'b')
        self.assertEqual(result['save_nodes_with_outputs'], ['b', 'a', 'b'])

    def test_numeric_output_ids_are_not_normalized_for_lookup(self):
        outputs = {1: {'images': [{'filename': 'numeric.png'}]}, '1': {'images': [{'filename': 'string.png'}]}}
        result = extract(outputs, [1])
        self.assertEqual([i['filename'] for i in result['images']], ['string.png'])
        self.assertEqual(result['output_node_ids'], ['1', '1'])
        self.assertEqual(list(result['output_keys_by_node']), ['1'])
        fallback = extract({1: outputs[1]}, [1])
        self.assertEqual(fallback['images'][0]['_node_id'], 1)
        self.assertEqual(fallback['save_nodes_with_outputs'], [])

    def test_malformed_fields_preserved_and_unhashable_fields_raise(self):
        for field in ['subfolder', 'type']:
            for value in [None, 0, False]:
                record = {'filename': 'x.png', field: value}
                self.assertIs(extract({'n': {'images': [record]}}, [])['images'][0][field], value)
            for value in [[], {}]:
                record = {'filename': 'x.png', field: value}
                self.assertIs(collect({'images': [record]})[0][0][field], value)
                with self.assertRaises(TypeError):
                    extract({'n': {'images': [record]}}, [])
        with self.assertRaises(TypeError):
            extract({}, 1)
