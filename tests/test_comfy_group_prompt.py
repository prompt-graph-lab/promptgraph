from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
from core import comfyui
from core.comfy_group_prompt import build_prompt_by_group, logger


class GroupPromptTests(unittest.TestCase):
    def test_nested_disabled_stack_and_token_fallback(self):
        project = NS(nodes={'n': NS(word='word', original='original', group='g'), 'tail': NS(word='tail')})
        line = NS(id='L', node_path=['m','m','n','m','n','m','n','missing','tail'],
                  tokens=['<mod:a>','<mod:a>','word','</mod:a>','word','</mod:a>','word'])
        self.assertEqual(build_prompt_by_group(project,line,{'a'}), {'g':['original'], 'default':['tail']})
        self.assertEqual(build_prompt_by_group(project,line), {'g':['original']*3, 'default':['tail']})

    def test_warning_logger_identity_and_eager_word_default(self):
        self.assertIs(logger, comfyui.logger)
        line=NS(id='L', node_path=['a','b'], tokens=['</mod:x>','<mod:y>'])
        with patch.object(comfyui.logger,'warning') as warning:
            self.assertEqual(build_prompt_by_group(NS(nodes={}),line),{})
        self.assertEqual([c.args[0] for c in warning.call_args_list], [
            'Malformed module marker: closing tag </mod:x> found without matching opening tag in line L.',
            "Malformed module marker: unclosed tags ['y'] at end of line L."])
        with self.assertRaises(AttributeError):
            build_prompt_by_group(NS(nodes={'n':NS(original='x')}),NS(id='L',node_path=['n'],tokens=[]))
