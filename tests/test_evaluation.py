import unittest
from feedback_memory.engine import Engine
from feedback_memory.extractors import LocalExtractor
from feedback_memory.evaluation import scores, run_cases, summarize

class EvaluationTests(unittest.TestCase):
    def case(self):
        return dict(id='x',split='holdout',initial_memories=[],request=dict(user_id='u',feedback_id='f',request_id='r',batch_id='b',candidate_id='c',memory_version=0,feedback_revision=1,stance='reject',candidate={},messages=[{'message_id':'m','role':'user','text':'今天很累'}]),expected={'labels':['current_state'],'proposals':[]})
    def test_failed_model_counts_as_miss(self):
        class Broken:
            def extract(self,r):raise TimeoutError()
        result=summarize(run_cases([self.case()],Broken()))
        self.assertEqual(result['classification_micro']['fn'],1);self.assertEqual(result['failed_cases'],1)
    def test_fabricated_raw_evidence_measured_not_hidden(self):
        class Fake:
            def extract(self,r):
                return {'units':[dict(classification='general_preference',direction='demand',attribute_key='shared_leisure',value='quiet',scope='general',certainty='explicit',correction=False,source_message_ids=['m'],evidence_span=[{'message_id':'m','text':'不存在的原话'}])]},{}
        result=summarize(run_cases([self.case()],Fake()))
        self.assertEqual(result['evidence_substring_accuracy'],0);self.assertEqual(result['total_writes'],0)
    def test_wrong_semantic_write_is_counted(self):
        class Fake:
            def extract(self,r):
                return {'units':[dict(classification='general_preference',direction='demand',attribute_key='shared_leisure',value='quiet',scope='general',certainty='explicit',correction=False,source_message_ids=['m'],evidence_span=[{'message_id':'m','text':'今天很累'}])]},{}
        result=summarize(run_cases([self.case()],Fake()))
        # Exact text alone cannot establish entailment. This test deliberately exposes that boundary.
        self.assertEqual(result['wrong_writes'],1);self.assertEqual(result['wrong_long_term_write_rate'],1)
    def test_micro_counts(self):
        self.assertEqual(scores(2,1,2)['precision'],2/3);self.assertEqual(scores(2,1,2)['recall'],.5)
    def test_empty_denominator_not_perfect(self):
        self.assertIsNone(scores(0,0,0)['precision'])
