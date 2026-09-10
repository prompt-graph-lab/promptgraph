import unittest
from core.consistency_presentation import _format_percent, _compact_label_list

class ConsistencyPresentationTests(unittest.TestCase):
    def test_percentage_falsey_numeric_and_special_values(self):
        for value,expected in [(None,'0.0%'),('', '0.0%'),(True,'100.0%'),('0.125','12.5%'),(-1,'-100.0%'),(float('inf'),'inf%')]:
            self.assertEqual(expected,_format_percent(value))
        with self.assertRaises(ValueError): _format_percent('bad')

    def test_labels_keep_duplicates_and_legacy_limits(self):
        self.assertEqual('a, a, None',_compact_label_list(['a','', 'a',None]))
        self.assertEqual('a, +2 more',_compact_label_list(['a','b','c'],1))
        self.assertEqual(', +2 more',_compact_label_list(['a','b'],0))
        self.assertEqual('a, +3 more',_compact_label_list(['a','b'],-1))
        with self.assertRaises(TypeError): _compact_label_list(['a','b'],0.5)

    def test_repeated_conversion_and_exception(self):
        calls=[]
        class Label:
            def __str__(self): calls.append(1); return str(len(calls))
        self.assertEqual('2',_compact_label_list([Label()]))
        self.assertEqual([1,1],calls)
        with self.assertRaises(TypeError): _compact_label_list(None)
