"""SQLite transactions enforce memory safety independently of extraction quality."""
import copy
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from .extractors import LABELS, ATTRS


def ident(): return uuid.uuid4().hex

def dump(x): return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def key(m): return (m['direction'], m['attribute_key'], m['scope'])


class Conflict(ValueError): pass


class Engine:
    def __init__(self, path=':memory:'):
        self.db = sqlite3.connect(path, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, version INTEGER NOT NULL, memories TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS feedback(user_id TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL, stance TEXT NOT NULL, PRIMARY KEY(user_id,id));
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, request TEXT NOT NULL, base_version INTEGER NOT NULL, status TEXT NOT NULL, result TEXT, UNIQUE(user_id,request_id));
        CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, user_id TEXT NOT NULL, feedback_id TEXT NOT NULL, feedback_revision INTEGER NOT NULL, base_version INTEGER NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
        ''')
    def close(self): self.db.close()
    @contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK'); raise
    def event(self, uid, kind, data):
        self.db.execute('INSERT INTO events(user_id,kind,payload) VALUES(?,?,?)',(uid,kind,dump(data)))
    def seed(self, uid, memories=None, version=0):
        if not isinstance(uid,str) or not uid or type(version) is not int or version < 0:
            raise ValueError('Invalid user/version')
        rows=copy.deepcopy(memories or [])
        ids=set(); active=set()
        for m in rows:
            if not all(k in m for k in ['direction','attribute_key','value','scope']): raise ValueError('Incomplete memory')
            if m['direction'] not in ('self','supply','demand','boundary'): raise ValueError('Invalid direction')
            m.setdefault('memory_id',ident()); m.setdefault('status','active'); m.setdefault('revision',1)
            m.setdefault('confirmed',True); m.setdefault('permissions',{'matching':True,'self':True,'public':False})
            if m['memory_id'] in ids: raise ValueError('Duplicate memory ID')
            ids.add(m['memory_id'])
            if m['status']=='active':
                if key(m) in active: raise ValueError('Duplicate active attribute/scope')
                active.add(key(m))
            if m['direction']=='boundary' and not m['confirmed'] and m['status']=='active': raise ValueError('Unconfirmed active boundary')
        with self.tx():
            if self.db.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone(): raise Conflict('User already initialized')
            self.db.execute('INSERT INTO users VALUES(?,?,?)',(uid,version,dump(rows)))
    def state(self,uid):
        row=self.db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        if not row: raise ValueError('Unknown user')
        return row['version'],json.loads(row['memories'])
    def matching_memories(self,uid):
        _,rows=self.state(uid)
        return [m for m in rows if m['status']=='active' and m['permissions'].get('matching') is True and (m['direction']!='boundary' or m['confirmed'])]
    @staticmethod
    def validate_request(r):
        for field in ('user_id','feedback_id','request_id','batch_id','candidate_id'):
            if not isinstance(r.get(field),str) or not r[field]: raise ValueError('Missing '+field)
        for field in ('memory_version','feedback_revision'):
            if type(r.get(field)) is not int or r[field]<0: raise ValueError('Invalid '+field)
        if r['feedback_revision']<1 or r.get('stance') not in ('like','reject','pending'): raise ValueError('Invalid feedback')
        if not isinstance(r.get('candidate'),dict) or not isinstance(r.get('messages'),list): raise ValueError('Invalid context')
        mids=set()
        for m in r['messages']:
            if not isinstance(m,dict) or not isinstance(m.get('message_id'),str) or not m['message_id'] or m['message_id'] in mids: raise ValueError('Invalid/duplicate message ID')
            mids.add(m['message_id'])
            if m.get('role') not in ('user','assistant') or not isinstance(m.get('text'),str) or not m['text'].strip(): raise ValueError('Invalid message')
    def prepare(self,request):
        self.validate_request(request)
        # Ignore extra input fields, including model-supplied permissions or gold answers.
        r={k:copy.deepcopy(request[k]) for k in ('user_id','feedback_id','request_id','batch_id','candidate_id','memory_version','feedback_revision','stance','candidate','messages')}
        fingerprint=hashlib.sha256(dump(r).encode()).hexdigest()
        with self.tx():
            prior=self.db.execute('SELECT * FROM jobs WHERE user_id=? AND request_id=?',(r['user_id'],r['request_id'])).fetchone()
            if prior:
                if prior['fingerprint']!=fingerprint: raise Conflict('Idempotency key reused with different content')
                return prior['id']
            version,memories=self.state(r['user_id'])
            if version!=r['memory_version']: raise Conflict('Stale memory_version; reread and retry')
            f=self.db.execute('SELECT * FROM feedback WHERE user_id=? AND id=?',(r['user_id'],r['feedback_id'])).fetchone()
            expected=1 if not f else f['revision']+1
            if r['feedback_revision']!=expected: raise Conflict('Expected feedback_revision '+str(expected))
            self.db.execute('INSERT OR REPLACE INTO feedback VALUES(?,?,?,?)',(r['user_id'],r['feedback_id'],r['feedback_revision'],r['stance']))
            self.db.execute("UPDATE proposals SET status='invalidated' WHERE user_id=? AND feedback_id=? AND status='pending'",(r['user_id'],r['feedback_id']))
            r['current_memories']=memories
            jid=ident()
            self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,NULL)',(jid,r['user_id'],r['request_id'],fingerprint,dump(r),version,'pending'))
            self.event(r['user_id'],'feedback_accepted',{'feedback_id':r['feedback_id'],'revision':r['feedback_revision'],'stance':r['stance']})
            return jid
    def job(self,jid):
        row=self.db.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not row: raise ValueError('Unknown job')
        return row
    def process(self,request,extractor):
        return self.run_job(self.prepare(request),extractor)
    def run_job(self,jid,extractor):
        row=self.job(jid)
        if row['result']: return json.loads(row['result'])
        r=json.loads(row['request'])
        try:
            extracted,metrics=extractor.extract(r)
        except Exception as exc:
            with self.tx():
                self.db.execute("UPDATE jobs SET status='retryable' WHERE id=? AND result IS NULL",(jid,))
                self.event(r['user_id'],'extraction_failed',{'job_id':jid,'error_type':type(exc).__name__})
            raise
        return self.finish(jid,extracted,metrics)
    @staticmethod
    def checked_units(r,extraction):
        msgs={m['message_id']:m['text'] for m in r['messages'] if m['role']=='user'}
        valid=[]; errors=[]
        raw=extraction.get('units') if isinstance(extraction,dict) else None
        if not isinstance(raw,list) or len(raw)>100: return [],['invalid_units']
        for idx,u in enumerate(raw):
            reason=None
            if not isinstance(u,dict) or u.get('classification') not in LABELS: reason='invalid_classification'
            else:
                refs=u.get('source_message_ids'); spans=u.get('evidence_span')
                if not isinstance(refs,list) or not refs or any(not isinstance(x,str) or x not in msgs for x in refs): reason='invalid_source'
                elif not isinstance(spans,list) or not spans or any(not isinstance(s,dict) or s.get('message_id') not in refs or not isinstance(s.get('text'),str) or not s['text'].strip() or s['text'] not in msgs[s['message_id']] for s in spans): reason='invalid_evidence'
                elif set(refs)!={s['message_id'] for s in spans}: reason='missing_evidence'
                elif u['classification']=='general_preference':
                    if u.get('direction') not in ('self','supply','demand','boundary') or u.get('attribute_key') not in ATTRS: reason='invalid_attribute'
                    elif any(not isinstance(u.get(k),str) or not u[k].strip() or len(u[k])>200 for k in ('value','scope')): reason='invalid_value'
                    elif u.get('certainty') not in ('explicit','uncertain') or type(u.get('correction')) is not bool: reason='invalid_certainty'
            if reason: errors.append({'unit':idx,'reason':reason})
            else: valid.append(u)
        return valid,errors
    def finish(self,jid,extracted,metrics=None):
        with self.tx():
            job=self.job(jid)
            if job['result']: return json.loads(job['result'])
            r=json.loads(job['request']);uid=r['user_id'];version,memories=self.state(uid)
            f=self.db.execute('SELECT * FROM feedback WHERE user_id=? AND id=?',(uid,r['feedback_id'])).fetchone()
            if f['revision']!=r['feedback_revision'] or version!=job['base_version']:
                result=self.output([],[],[],memories,version,False,'stale',metrics,[])
            else:
                units,errors=self.checked_units(r,extracted)
                proposals=[];decisions=[];changed=False;clarify=bool(errors)
                # Contradictory same-key values in one extraction must not be applied in order.
                groups={}
                for u in units:
                    if u['classification']=='general_preference': groups.setdefault(key(u),set()).add(u['value'])
                seen_assertions=set()
                for u in units:
                    if u['classification']=='unclear': clarify=True
                    if u['classification']!='general_preference': continue
                    assertion=(key(u),u['value'],u['certainty'],u['correction'])
                    if assertion in seen_assertions: continue
                    seen_assertions.add(assertion)
                    proposal={k:copy.deepcopy(u[k]) for k in ('source_message_ids','direction','attribute_key','value','scope','evidence_span','certainty')}
                    proposal.update(proposal_id=ident(),user_id=uid,feedback_id=r['feedback_id'],batch_id=r['batch_id'],candidate_id=r['candidate_id'],feedback_revision=r['feedback_revision'])
                    same=[m for m in memories if key(m)==key(u)]
                    current=next((m for m in same if m['status']=='active'),None)
                    # Explicit revocation remains a tombstone even if older evidence is re-extracted.
                    blocked=any(m['status']=='forgotten' or m.get('use_prohibited') is True or (m['status']=='active' and m['permissions'].get('matching') is False) for m in same)
                    status='applied'; reason='new_explicit_preference';action='add'
                    if blocked: action='no_change';reason='use_prohibited';status='rejected'
                    elif len(groups[key(u)])>1: action='clarify';reason='conflicting_claims_in_feedback';status='pending'
                    elif u['certainty']!='explicit': action='clarify';reason='uncertain';status='pending'
                    elif current and current['value']==u['value']: action='no_change';reason='duplicate'
                    elif u['direction']=='boundary': action='clarify';reason='boundary_confirmation_required';status='pending'
                    elif current and not u['correction']: action='clarify';reason='unresolved_conflict';status='pending'
                    elif current: action='update';reason='explicit_correction'
                    proposal['memory_action']=action;proposal['status']=status
                    if action=='clarify': clarify=True
                    if action in ('add','update'):
                        self.apply_memory(memories,proposal,current,version+1,confirmed=False)
                        changed=True
                    self.db.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,?)',(proposal['proposal_id'],uid,r['feedback_id'],r['feedback_revision'],version,status,dump(proposal)))
                    proposals.append(proposal)
                    decisions.append(dict(proposal_id=proposal['proposal_id'],action=action,reason=reason,replaces=current['memory_id'] if current and action=='update' else None))
                if changed:
                    version+=1
                    self.db.execute('UPDATE users SET version=?,memories=? WHERE id=?',(version,dump(memories),uid))
                    self.event(uid,'memory_changed',{'version':version,'job_id':jid})
                # Pending confirmations use the post-transaction version, including sibling writes.
                self.db.execute("UPDATE proposals SET base_version=? WHERE user_id=? AND feedback_id=? AND feedback_revision=? AND status='pending'",(version,uid,r['feedback_id'],r['feedback_revision']))
                result=self.output(units,proposals,decisions,memories,version,clarify,'completed',metrics,errors)
            self.db.execute('UPDATE jobs SET status=?,result=? WHERE id=?',(result['status'],dump(result),jid))
            return result
    @staticmethod
    def apply_memory(memories,p,current,version,confirmed):
        mid=ident()
        if current:
            current['status']='superseded';current['superseded_by']=mid
        memories.append(dict(memory_id=mid,revision=(current['revision']+1 if current else 1),status='active',
            direction=p['direction'],attribute_key=p['attribute_key'],value=p['value'],scope=p['scope'],confirmed=confirmed,
            source_message_ids=p['source_message_ids'],evidence_span=p['evidence_span'],proposal_id=p['proposal_id'],
            feedback_id=p['feedback_id'],state_version=version,supersedes=current['memory_id'] if current else None,
            permissions=copy.deepcopy(current['permissions']) if current else {'self':True,'matching':True,'public':False}))
    @staticmethod
    def output(units,proposals,decisions,memories,version,clarify,status,metrics,errors):
        return dict(feedback_classification=sorted({u['classification'] for u in units}),
            reason_scope=[{'classification':u['classification'],'source_message_ids':u['source_message_ids'],'evidence_span':u['evidence_span']} for u in units],
            memory_proposals=proposals,arbitration_decisions=decisions,updated_memories=copy.deepcopy(memories),
            memory_version=version,clarification_needed=clarify,status=status,metrics=metrics or {},validation_errors=errors)
    def confirm(self,uid,pid,expected_version,accept=True):
        with self.tx():
            row=self.db.execute('SELECT * FROM proposals WHERE id=? AND user_id=?',(pid,uid)).fetchone()
            if not row: raise ValueError('Unknown proposal')
            version,memories=self.state(uid)
            if row['status']!='pending': raise Conflict('Proposal no longer pending')
            if expected_version!=version or row['base_version']!=version: raise Conflict('Stale proposal; re-extract against latest state')
            f=self.db.execute('SELECT revision FROM feedback WHERE user_id=? AND id=?',(uid,row['feedback_id'])).fetchone()
            if f['revision']!=row['feedback_revision']: raise Conflict('Feedback changed')
            p=json.loads(row['body'])
            if accept:
                same=[m for m in memories if key(m)==key(p)]
                if any(m['status']=='forgotten' or m.get('use_prohibited') or (m['status']=='active' and not m['permissions'].get('matching')) for m in same): raise Conflict('Use prohibited')
                current=next((m for m in same if m['status']=='active'),None)
                if current is None or current['value']!=p['value']:
                    version+=1;self.apply_memory(memories,p,current,version,confirmed=True)
                    self.db.execute('UPDATE users SET version=?,memories=? WHERE id=?',(version,dump(memories),uid))
                    self.event(uid,'memory_confirmed',{'proposal_id':pid,'version':version})
            self.db.execute('UPDATE proposals SET status=? WHERE id=?',('applied' if accept else 'rejected',pid))
            return {'memory_version':version,'updated_memories':memories}
    def revoke(self,uid,mid,expected_version):
        with self.tx():
            version,memories=self.state(uid)
            if version!=expected_version: raise Conflict('Stale memory_version')
            m=next((m for m in memories if m['memory_id']==mid),None)
            if m is None: raise ValueError('Unknown memory')
            # Revocation of an old revision also fences all current derivatives of the same claim.
            for related in memories:
                if key(related)==key(m):
                    related['permissions']={'self':False,'matching':False,'public':False};related['use_prohibited']=True
                    if related['status']=='active':related['status']='forgotten'
            version+=1
            self.db.execute('UPDATE users SET version=?,memories=? WHERE id=?',(version,dump(memories),uid))
            self.db.execute("UPDATE proposals SET status='invalidated' WHERE user_id=? AND status='pending'",(uid,))
            self.event(uid,'permission_revoked',{'memory_id':mid,'version':version})
            return {'memory_version':version,'updated_memories':memories}
