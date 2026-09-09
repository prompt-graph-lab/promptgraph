import unittest
from unittest.mock import patch
from core import comfyui
from core.comfy_workflow_injection import inject_prompt_to_workflow, logger


class WorkflowInjectionTests(unittest.TestCase):
    def test_order_merge_overwrite_and_identity(self):
        for wrapped in [False,True]:
            nodes={'1':{'inputs':{'text':' old, shared, '}}}
            workflow={'nodes':nodes} if wrapped else nodes
            mapping={'group_order':['b'], 'group_map':{'a':'positive','b':'positive'},
                     'positive':{'node_id':1,'input_key':'text'}}
            self.assertIs(inject_prompt_to_workflow(workflow,{'a':['shared','a'],'b':['b','b']},mapping),workflow)
            self.assertEqual(nodes['1']['inputs']['text'],'old, shared, b, a')
            mapping['merge_mode']='overwrite'
            inject_prompt_to_workflow(workflow,{'a':['shared','a'],'b':['b','b']},mapping)
            self.assertEqual(nodes['1']['inputs']['text'],'b, shared, a')
            inject_prompt_to_workflow(workflow,{},mapping,fallback_prompt='fallback')
            self.assertEqual(nodes['1']['inputs']['text'],'fallback')

    def test_legacy_logger_and_destination_failures_continue(self):
        self.assertIs(logger,comfyui.logger)
        workflow={'1':{'inputs':{'text':''}}, '2':{'inputs':{}}}
        mapping={'group_map':{'bad':'bad','missing':'missing','input':'input'},
                 'bad':{'node_id':'1','input_key':'text'},
                 'missing':{'node_id':'absent','input_key':'text'},
                 'input':{'node_id':'2','input_key':'text'},
                 'positive':{'node_id':'1','input_key':'text'}}
        with patch.object(comfyui.logger,'warning') as warning, patch.object(comfyui.logger,'info') as info:
            self.assertIs(inject_prompt_to_workflow(workflow,{'bad':[[]],'missing':[],'input':[],'other':['ok']},mapping),workflow)
        self.assertEqual(workflow['1']['inputs']['text'],'ok')
        info.assert_called_once_with("Unmapped group 'other' -> defaulting to positive")
        self.assertEqual(warning.call_count,3)
        self.assertTrue(warning.call_args_list[0].args[0].startswith('Failed to inject prompt to node 1: '))
        self.assertEqual(warning.call_args_list[1].args[0],'Node absent not found in workflow')
        self.assertEqual(warning.call_args_list[2].args[0],"input_key 'text' not found in node 2")
