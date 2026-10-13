import copy
import json
import tempfile
import unittest
from pathlib import Path
from feedback_memory.engine import Engine, Conflict
from feedback_memory.extractors import LocalExtractor, unit


def req(text='我希望伴侣安静一点', **kw):
    r=dict(user_id='u',feedback_id='f',request_id='r',batch_id='b',candidate_id='c',memory_version=0,feedback_revision=1,stance='reject',candidate={'likes':'聚会'},messages=[{'message_id':'m','role':'user','text':text}]);r.update(kw);return r

def mem(value='social',**kw):
    r=dict(memory_id='old',direction='demand',attribute_key='shared_leisure',value=value,scope='general');r.update(kw);return r


class Tests(unittest.TestCase):
    def setUp(self):self.e=Engine();self.e.seed('u');self.x=LocalExtractor()
    def tearDown(self):self.e.close()
    def run_req(self,r):return self.e.process(r,self.x)
    def active(self):return [m for m in self.e.state('u')[1] if m['status']=='active']
    def test_exact_duplicate_submission(self):
        r=req();a=self.run_req(r);b=self.run_req(r)
        self.assertEqual(a,b);self.assertEqual(len(self.active()),1);self.assertEqual(a['memory_version'],1)
    def test_idempotency_conflict(self):
        self.run_req(req())
        with self.assertRaises(Conflict):self.run_req(req('我希望伴侣喜欢聚会'))
    def test_repeated_evidence_new_feedback_no_write(self):
        self.run_req(req());r=self.run_req(req(feedback_id='f2',request_id='r2',memory_version=1))
        self.assertEqual(r['memory_version'],1);self.assertEqual(r['memory_proposals'][0]['memory_action'],'no_change')
    def test_explicit_correction_replaces(self):
        self.run_req(req('我希望伴侣喜欢聚会'))
        r=self.run_req(req('我改变想法现在更希望伴侣安静一点',request_id='r2',feedback_id='f2',memory_version=1))
        self.assertEqual(r['memory_version'],2);self.assertEqual(self.active()[0]['value'],'quiet')
        old=[m for m in r['updated_memories'] if m['status']=='superseded'][0]
        self.assertEqual(old['superseded_by'],self.active()[0]['memory_id'])
    def test_conflict_requires_confirmation(self):
        self.run_req(req('我希望伴侣喜欢聚会'))
        r=self.run_req(req(feedback_id='f2',request_id='r2',memory_version=1))
        self.assertTrue(r['clarification_needed']);self.assertEqual(self.active()[0]['value'],'social')
    def test_different_contexts_coexist(self):
        r=self.run_req(req('我希望伴侣工作日安静一点，我希望伴侣周末喜欢聚会'))
        self.assertEqual(len(self.active()),2);self.assertEqual(r['memory_version'],1)
    def test_temporary_state_not_written(self):
        r=self.run_req(req('今天太累不想看'))
        self.assertEqual(r['memory_proposals'],[]);self.assertEqual(r['memory_version'],0)
    def test_mixed_feedback_keeps_preference(self):
        r=self.run_req(req('只是他每次迟到，但我希望伴侣不抽烟'))
        self.assertEqual(set(r['feedback_classification']),{'candidate_specific','general_preference'})
        self.assertEqual(self.active()[0]['attribute_key'],'smoking')
    def test_hard_boundary_pending_then_confirm(self):
        r=self.run_req(req('我不能接受伴侣抽烟'));p=r['memory_proposals'][0]
        self.assertEqual(self.active(),[]);self.assertEqual(p['status'],'pending')
        self.e.confirm('u',p['proposal_id'],0)
        self.assertTrue(self.active()[0]['confirmed']);self.assertEqual(len(self.e.matching_memories('u')),1)
    def test_vote_change_invalidates_pending(self):
        r=self.run_req(req('我不能接受伴侣抽烟'));pid=r['memory_proposals'][0]['proposal_id']
        self.run_req(req('只是他不合适',request_id='r2',feedback_revision=2,stance='like'))
        with self.assertRaises(Conflict):self.e.confirm('u',pid,0)
        self.assertEqual(self.active(),[])
    def test_confirmed_preference_survives_vote_change(self):
        r=self.run_req(req('我不能接受伴侣抽烟'));self.e.confirm('u',r['memory_proposals'][0]['proposal_id'],0)
        self.run_req(req('今天不想看',request_id='r2',feedback_revision=2,memory_version=1,stance='like'))
        self.assertEqual(len(self.active()),1)
    def test_old_async_cannot_override_correction(self):
        self.run_req(req('我希望伴侣喜欢聚会'))
        old=req('我希望伴侣喜欢聚会',feedback_id='f2',request_id='r2',memory_version=1)
        jid=self.e.prepare(old)
        self.run_req(req('我改变想法现在更希望伴侣安静一点',feedback_id='f3',request_id='r3',memory_version=1))
        result=self.e.run_job(jid,self.x)
        self.assertEqual(result['status'],'stale');self.assertEqual(self.active()[0]['value'],'quiet')
    def test_old_async_invalid_after_vote_revision(self):
        jid=self.e.prepare(req('我希望伴侣喜欢聚会'))
        self.run_req(req('今天不想看',request_id='r2',feedback_revision=2,stance='like'))
        self.assertEqual(self.e.run_job(jid,self.x)['status'],'stale');self.assertEqual(self.active(),[])
    def test_revocation_blocks_reextract_and_pending_job(self):
        self.run_req(req());mid=self.active()[0]['memory_id']
        jid=self.e.prepare(req(feedback_id='f2',request_id='r2',memory_version=1))
        self.e.revoke('u',mid,1)
        self.assertEqual(self.e.matching_memories('u'),[])
        self.assertEqual(self.e.run_job(jid,self.x)['status'],'stale')
        r=self.run_req(req(feedback_id='f3',request_id='r3',memory_version=2))
        self.assertEqual(r['arbitration_decisions'][0]['reason'],'use_prohibited');self.assertEqual(self.active(),[])
    def test_fabricated_evidence_rejected(self):
        jid=self.e.prepare(req('今天很累'))
        fake=unit('我希望伴侣安静一点','m','general_preference',direction='demand',attribute_key='shared_leisure',value='quiet',scope='general',certainty='explicit',correction=False)
        r=self.e.finish(jid,{'units':[fake]})
        self.assertTrue(r['validation_errors']);self.assertEqual(self.active(),[])
    def test_assistant_cannot_be_evidence(self):
        r=req();r['messages']=[{'message_id':'m','role':'assistant','text':'我希望伴侣安静一点'}]
        jid=self.e.prepare(r)
        fake=unit('我希望伴侣安静一点','m','general_preference',direction='demand',attribute_key='shared_leisure',value='quiet',scope='general',certainty='explicit',correction=False)
        result=self.e.finish(jid,{'units':[fake]});self.assertTrue(result['validation_errors']);self.assertEqual(self.active(),[])
    def test_model_cannot_set_permissions(self):
        r=req();jid=self.e.prepare(r);out,_=self.x.extract(r)
        out['units'][0]['permissions']={'public':True}
        self.e.finish(jid,out);self.assertFalse(self.active()[0]['permissions']['public'])
    def test_uncertain_does_not_overwrite(self):
        self.run_req(req('我希望伴侣喜欢聚会'))
        r=req(feedback_id='f2',request_id='r2',memory_version=1);jid=self.e.prepare(r);out,_=self.x.extract(r)
        out['units'][0]['certainty']='uncertain';out['units'][0]['correction']=True
        self.e.finish(jid,out);self.assertEqual(self.active()[0]['value'],'social')
    def test_conflicting_claims_same_request(self):
        r=self.run_req(req('我希望伴侣安静一点，我希望伴侣喜欢聚会'))
        self.assertEqual(self.active(),[]);self.assertTrue(r['clarification_needed'])
    def test_cross_user_confirmation_denied(self):
        r=self.run_req(req('我不能接受伴侣抽烟'));self.e.seed('other')
        with self.assertRaises(ValueError):self.e.confirm('other',r['memory_proposals'][0]['proposal_id'],0)
    def test_duplicate_message_ids_invalid(self):
        r=req();r['messages'].append(copy.deepcopy(r['messages'][0]))
        with self.assertRaises(ValueError):self.run_req(r)
    def test_failure_retry_preserves_vote(self):
        class Broken:
            def extract(self,r):raise TimeoutError()
        r=req()
        with self.assertRaises(TimeoutError):self.e.process(r,Broken())
        self.assertEqual(self.e.db.execute('SELECT stance FROM feedback').fetchone()[0],'reject')
        self.assertEqual(self.run_req(r)['memory_version'],1)
    def test_persistent_job_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'state.sqlite');e=Engine(path);e.seed('u');jid=e.prepare(req());e.close()
            e=Engine(path);self.assertEqual(e.run_job(jid,self.x)['memory_version'],1);e.close()
    def test_two_connections_version_fence(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'state.sqlite');a=Engine(path);b=Engine(path);a.seed('u')
            j=a.prepare(req('我希望伴侣喜欢聚会'))
            b.process(req(feedback_id='f2',request_id='r2'),self.x)
            self.assertEqual(a.run_job(j,self.x)['status'],'stale');a.close();b.close()

if __name__=='__main__':unittest.main()
