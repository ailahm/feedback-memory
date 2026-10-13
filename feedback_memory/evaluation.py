"""Offline multi-label and exact-claim evaluation, with auditable denominators."""
import json
import statistics
from pathlib import Path
from .engine import Engine
from .extractors import LABELS, LocalExtractor, SinglePassLocal, JsonLLM


def scores(tp,fp,fn):
    p=tp/(tp+fp) if tp+fp else None
    r=tp/(tp+fn) if tp+fn else None
    f=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None
    return {'precision':p,'recall':r,'f1':f,'tp':tp,'fp':fp,'fn':fn}

def run_cases(cases,extractor):
    rows=[]
    for case in cases:
        eng=Engine()
        eng.seed(case['request']['user_id'],case['initial_memories'])
        try:
            captured={}
            class Capture:
                def extract(self, request):
                    output, metrics=extractor.extract(request)
                    captured['raw']=output
                    return output,metrics
            result=eng.process(case['request'],Capture())
            props={tuple(p[k] for k in ('direction','attribute_key','value','scope','memory_action')) for p in result['memory_proposals']}
            labels=set(result['feedback_classification']); gold=set(case['expected']['labels'])
            expected={tuple(p) for p in case['expected']['proposals']}
            rows.append(dict(id=case['id'],split=case['split'],text=[m['text'] for m in case['request']['messages']],
                expected_labels=sorted(gold),actual_labels=sorted(labels),expected_proposals=sorted(expected),actual_proposals=sorted(props),
                exact=labels==gold and props==expected,result=result,error=None,raw_extraction=captured.get('raw'),messages=case['request']['messages']))
        except Exception as exc:
            # A provider failure is a failed case, not an omitted sample.
            rows.append(dict(id=case['id'],split=case['split'],text=[m['text'] for m in case['request']['messages']],expected_labels=case['expected']['labels'],actual_labels=[],expected_proposals=case['expected']['proposals'],actual_proposals=[],exact=False,result=None,error=type(exc).__name__))
        finally: eng.close()
    return rows


def summarize(rows):
    by_label={label:[0,0,0] for label in sorted(LABELS)}
    ptp=pfp=pfn=wrong=writes=evidence=valid_evidence=0
    arb=0;latencies=[];in_tokens=[];out_tokens=[];costs=[];calls=0
    for row in rows:
        gold=set(row['expected_labels']);pred=set(row['actual_labels'])
        for label,c in by_label.items():
            c[0]+=int(label in gold and label in pred);c[1]+=int(label in pred-gold);c[2]+=int(label in gold-pred)
        g={tuple(p[:4]) for p in row['expected_proposals']};p={tuple(p[:4]) for p in row['actual_proposals']}
        ptp+=len(g&p);pfp+=len(p-g);pfn+=len(g-p)
        ga={tuple(p) for p in row['expected_proposals']};pa={tuple(p) for p in row['actual_proposals']}
        arb+=int(row['error'] is None and ga==pa)
        actual_writes={x for x in pa if x[4] in ('add','update')}
        writes+=len(actual_writes);wrong+=len(actual_writes-ga)
        result=row['result']
        if result:
            messages={m['message_id']:m['text'] for m in row['messages'] if m['role']=='user'}
            raw=row.get('raw_extraction',{})
            raw_units=raw.get('units',[]) if isinstance(raw,dict) else []
            for proposal in raw_units if isinstance(raw_units,list) else []:
                if not isinstance(proposal,dict) or proposal.get('classification')!='general_preference': continue
                spans=proposal.get('evidence_span')
                if not isinstance(spans,list) or not spans:
                    evidence+=1;continue
                for span in spans:
                    evidence+=1
                    if isinstance(span,dict) and isinstance(span.get('message_id'),str) and isinstance(span.get('text'),str) and span['text'].strip() and span['text'] in messages.get(span['message_id'],''):
                        valid_evidence+=1
            m=result['metrics'];latencies.append(m.get('latency_ms',0));calls+=int(m.get('model_called',False))
            in_tokens.append(m.get('input_tokens'));out_tokens.append(m.get('output_tokens'));costs.append(m.get('cost'))
    counts=[sum(v[i] for v in by_label.values()) for i in range(3)]
    fs=[scores(*v)['f1'] for v in by_label.values()]
    correction=[r for r in rows if any(p[4] in ('update','clarify','no_change') for p in r['expected_proposals'])]
    correct=sum(r['error'] is None and {tuple(p) for p in r['actual_proposals']}=={tuple(p) for p in r['expected_proposals']} for r in correction)
    return dict(cases=len(rows),classification_micro=scores(*counts),classification_macro_f1=statistics.mean(f for f in fs if f is not None),classification_per_label={k:scores(*v) for k,v in by_label.items()},
        proposal_exact_claim=scores(ptp,pfp,pfn),wrong_long_term_write_rate=wrong/writes if writes else None,wrong_writes=wrong,total_writes=writes,
        arbitration_exact_accuracy=arb/len(rows),conflict_correction_accuracy=correct/len(correction) if correction else None,conflict_correction_cases=len(correction),
        evidence_substring_accuracy=valid_evidence/evidence if evidence else None,evidence_count=evidence,
        latency_ms_p50=statistics.median(latencies) if latencies else None,latency_ms_p95=sorted(latencies)[min(len(latencies)-1,int(.95*len(latencies)))] if latencies else None,
        model_calls=calls,input_tokens=sum(in_tokens) if in_tokens and all(x is not None for x in in_tokens) else None,output_tokens=sum(out_tokens) if out_tokens and all(x is not None for x in out_tokens) else None,
        cost=sum(costs) if costs and all(x is not None for x in costs) else None,failed_cases=sum(r['error'] is not None for r in rows),exact_cases=sum(r['exact'] for r in rows))


def evaluate(dataset,outdir,mode='local'):
    cases=json.loads(Path(dataset).read_text());out=Path(outdir);out.mkdir(parents=True,exist_ok=True)
    if len(cases)<30: raise ValueError('At least 30 cases required')
    report={'mode':mode,'sample_count':len(cases),'runs':{}}
    adapters={'baseline':SinglePassLocal(),'improved':LocalExtractor()} if mode=='local' else {'baseline':JsonLLM(True),'improved':JsonLLM(False)}
    for name,adapter in adapters.items():
        rows=run_cases(cases,adapter)
        report['runs'][name]={'all':summarize(rows),'dev':summarize([r for r in rows if r['split']=='dev']),'holdout':summarize([r for r in rows if r['split']=='holdout'])}
        (out/(name+'_cases.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    (out/'metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    a=report['runs']['baseline']['holdout'];b=report['runs']['improved']['holdout']
    def fmt(v):return 'N/A' if v is None else f'{v:.4f}'
    text='# 反馈记忆算法评测\n\n'
    text+=('这是本地规则实验，未调用真实模型，不能据此推断LLM语义质量或模型成本。\n\n' if mode=='local' else '真实模型调用结果；失败用例保留在分母中。费用按本地配置单价估算。\n\n')
    text+='45条虚构样本：开发集24条，预留评测集21条。单人标注，未经过业务方独立复核；本地规则在阅读整个任务时编写，预留集不代表独立盲测。\n\n'
    text+='## 预留集对比\n\n| 指标 | 基线 | 改进 |\n|---|---|---|\n'
    for title,path in [('分类micro Precision',('classification_micro','precision')),('分类micro Recall',('classification_micro','recall')),('分类micro F1',('classification_micro','f1')),('提案Precision',('proposal_exact_claim','precision')),('提案Recall',('proposal_exact_claim','recall')),('错误长期写入比例',('wrong_long_term_write_rate',)),('冲突与纠正正确率',('conflict_correction_accuracy',)),('证据原文定位准确率',('evidence_substring_accuracy',)),('提取延迟p50毫秒',('latency_ms_p50',)),('提取延迟p95毫秒',('latency_ms_p95',)),('模型输入tokens',('input_tokens',)),('模型输出tokens',('output_tokens',)),('模型成本',('cost',))]:
        va=a;vb=b
        for k in path:va=va[k];vb=vb[k]
        text+=f'| {title} | {fmt(va)} | {fmt(vb)} |\n'
    text+='\n## 口径\n\n分类为多标签micro/macro指标。提案以方向、属性、值和情境四元组精确匹配；仲裁再加入动作。错误写入率分母是实际add/update数，分子是与标注不符的写入数。冲突集包含预期update/clarify/no_change的样本。证据指标只验证原话连续片段的定位，不证明原话蕴含提案；语义错误由提案指标与失败分析覆盖。调用延迟只计提取器，不计数据库；本地0 tokens表示没调用模型。\n\n'
    text+='## 失败案例\n\n'
    for r in json.loads((out/'improved_cases.json').read_text()):
        if not r['exact']:
            text+=f"- {r['id']}：{' / '.join(r['text'])}\n  期望：{r['expected_labels']} / {r['expected_proposals']}；实际：{r['actual_labels']} / {r['actual_proposals']}；错误：{r['error']}。\n"
    text+='\n本地规则的主要限制是隐含普遍偏好、否定嵌套、跨轮指代和自然纠正措辞。接入模型后必须用相同样本重跑，不能沿用本地结果。两条路线共用仲裁器，这个对比隔离了提取策略差异；并未衡量移除事务和校验后的安全增益。\n'
    (out/'REPORT.md').write_text(text)
    return report
