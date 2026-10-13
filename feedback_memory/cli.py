import argparse
import json
from pathlib import Path
from .engine import Engine
from .extractors import LocalExtractor, JsonLLM
from .evaluation import evaluate


def main():
    p=argparse.ArgumentParser(description='Feedback-to-Memory isolated exercise')
    sub=p.add_subparsers(dest='command',required=True)
    demo=sub.add_parser('demo');demo.add_argument('--case',default='case-13');demo.add_argument('--mode',choices=['local','llm'],default='local');demo.add_argument('--dataset',default='data/cases.json')
    ev=sub.add_parser('evaluate');ev.add_argument('--mode',choices=['local','llm'],default='local');ev.add_argument('--dataset',default='data/cases.json');ev.add_argument('--out',default='reports/local')
    init=sub.add_parser('init');init.add_argument('--db',required=True);init.add_argument('--user',required=True);init.add_argument('--memories');init.add_argument('--version',type=int,default=0)
    submit=sub.add_parser('submit');submit.add_argument('--db',required=True);submit.add_argument('--input',required=True);submit.add_argument('--mode',choices=['local','llm'],default='local')
    state=sub.add_parser('state');state.add_argument('--db',required=True);state.add_argument('--user',required=True)
    confirm=sub.add_parser('confirm');confirm.add_argument('--db',required=True);confirm.add_argument('--user',required=True);confirm.add_argument('--proposal',required=True);confirm.add_argument('--version',type=int,required=True);confirm.add_argument('--reject',action='store_true')
    revoke=sub.add_parser('revoke');revoke.add_argument('--db',required=True);revoke.add_argument('--user',required=True);revoke.add_argument('--memory',required=True);revoke.add_argument('--version',type=int,required=True)
    retry=sub.add_parser('retry');retry.add_argument('--db',required=True);retry.add_argument('--job',required=True);retry.add_argument('--mode',choices=['local','llm'],default='local')
    args=p.parse_args()
    if args.command in ('init','submit','state','confirm','revoke','retry'):
        eng=Engine(args.db)
        try:
            if args.command=='init':
                eng.seed(args.user,json.loads(Path(args.memories).read_text()) if args.memories else [],args.version);result={'initialized':True}
            elif args.command=='submit':
                request=json.loads(Path(args.input).read_text());jid=eng.prepare(request)
                result=eng.run_job(jid,LocalExtractor() if args.mode=='local' else JsonLLM());result['job_id']=jid
            elif args.command=='state':
                version,memories=eng.state(args.user);result={'memory_version':version,'memories':memories,'matching_memories':eng.matching_memories(args.user)}
            elif args.command=='confirm':result=eng.confirm(args.user,args.proposal,args.version,not args.reject)
            elif args.command=='revoke':result=eng.revoke(args.user,args.memory,args.version)
            else:result=eng.run_job(args.job,LocalExtractor() if args.mode=='local' else JsonLLM())
            print(json.dumps(result,ensure_ascii=False,indent=2))
        finally:eng.close()
        return
    if args.command=='demo':
        case=next(c for c in json.loads(Path(args.dataset).read_text()) if c['id']==args.case)
        eng=Engine();eng.seed(case['request']['user_id'],case['initial_memories'])
        result=eng.process(case['request'],LocalExtractor() if args.mode=='local' else JsonLLM())
        print(json.dumps(result,ensure_ascii=False,indent=2));eng.close()
    else:
        if args.mode=='llm':
            import os
            if not all(os.getenv(k) for k in ('MODEL_API_KEY','MODEL_BASE_URL','MODEL_NAME')):
                p.error('Configure MODEL_API_KEY, MODEL_BASE_URL, MODEL_NAME locally before real evaluation')
        result=evaluate(args.dataset,args.out,args.mode)
        print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
