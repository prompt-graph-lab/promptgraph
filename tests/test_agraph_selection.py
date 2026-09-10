import unittest
from types import SimpleNamespace as NS
from core.agraph_selection import normalize_agraph_selection

class AgraphSelectionTests(unittest.TestCase):
    def test_shapes_precedence_order_and_duplicates(self):
        project=NS(nodes={'a':None,'b':None,0:None})
        self.assertEqual(['b','a',0],normalize_agraph_selection([{'node':'b'},'a',{'id':0,'node':'a'},NS(id='a'),'missing'],project))
        self.assertEqual([],normalize_agraph_selection({'id':'missing','node':'a'},project))
        self.assertEqual([],normalize_agraph_selection(('a','b'),project))

    def test_falsey_payload_short_circuits_project_access(self):
        for payload in [None,False,0,'',[]]: self.assertEqual([],normalize_agraph_selection(payload,None))
        with self.assertRaises(TypeError): normalize_agraph_selection([{'id':[]}],NS(nodes={}))
        with self.assertRaises(AttributeError): normalize_agraph_selection('a',None)

    def test_object_property_is_read_twice(self):
        reads=[]
        class Item:
            @property
            def id(self): reads.append(1); return 'a'
        self.assertEqual(['a'],normalize_agraph_selection(Item(),NS(nodes={'a':1})))
        self.assertEqual([1,1],reads)
