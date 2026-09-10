import unittest
from core.comma_tag_text import _format_comma_tags, _parse_comma_tags

class CommaTagTextTests(unittest.TestCase):
    def test_format_list_only_preserves_duplicates_and_stringifies(self):
        self.assertEqual('',_format_comma_tags(('x',)))
        self.assertEqual('x, x, None, 0, False',_format_comma_tags([' x ','x',None,0,False,' ']))

    def test_parse_literal_commas_case_and_first_occurrence(self):
        self.assertEqual(['a','A','(b','c)'],_parse_comma_tags(' a, A,a,,(b,c) '))
        self.assertEqual([],_parse_comma_tags(False))
        self.assertEqual(['12'],_parse_comma_tags(12))

    def test_format_string_conversion_order_is_preserved(self):
        calls=[]
        class Tag:
            def __str__(self):
                calls.append(len(calls)); return str(len(calls))
        self.assertEqual('2',_format_comma_tags([Tag()]))
        self.assertEqual([0,1],calls)

    def test_conversion_exception_propagates(self):
        class Bad:
            def __str__(self): raise ValueError('bad')
        with self.assertRaises(ValueError): _format_comma_tags([Bad()])
        with self.assertRaises(ValueError): _parse_comma_tags(Bad())
