import unittest
from core.generation_duration import _format_duration

class GenerationDurationTests(unittest.TestCase):
    def test_units_rounding_and_hour_seconds_suppression(self):
        for seconds,expected in [(0,'不明'),(-1,'不明'),(0.1,'約0秒'),(0.5,'約0秒'),(1.5,'約2秒'),(59.5,'約1分00秒'),(61,'約1分01秒'),(3601,'約1時間0分'),(3661,'約1時間1分'),(True,'約1秒')]:
            self.assertEqual(expected,_format_duration(seconds))

    def test_invalid_values_preserve_exceptions(self):
        for value,error in [(None,TypeError),('2',TypeError),(float('nan'),ValueError),(float('inf'),OverflowError)]:
            with self.subTest(value=value), self.assertRaises(error): _format_duration(value)
        self.assertEqual('不明',_format_duration(float('-inf')))
