"""Hand-authored synthetic expectations; never derived from model predictions."""
import json
from pathlib import Path

def pref(value='social',scope='general',direction='demand',attr='shared_leisure',**extra):
 return dict(memory_id='old-1',direction=direction,attribute_key=attr,value=value,scope=scope,**extra)
# Expected proposals: direction, attribute, value, scope, arbitration action.
D='demand';S='self';B='boundary';G='general_preference';C='candidate_specific';U='unclear';T='current_state';P='presentation_issue'
cases=[
 ('我总体希望伴侣安静一点',[G],[(D,'shared_leisure','quiet','general','add')],[]),
 ('我希望伴侣喜欢聚会',[G],[(D,'shared_leisure','social','general','add')],[]),
 ('只是他每次都迟到',[C],[],[]),
 ('今天太累了不想看',[T],[],[]),
 ('推荐理由写错了',[P],[],[]),
 ('他太爱聚会了',[U],[],[]),
 ('我希望伴侣不抽烟',[G],[(D,'smoking','non_smoker','general','add')],[]),
 ('我希望伴侣喜欢宠物',[G],[(D,'pets','likes_pets','general','add')],[]),
 ('我希望伴侣直接沟通',[G],[(D,'communication','direct','general','add')],[]),
 ('我能提供耐心的倾听',[G],[('supply','communication','patient','general','add')],[]),
 ('我本人喜欢和朋友聚会',[G],[(S,'social_activity','social','with_friends','add')],[]),
 ('我总体希望伴侣安静一点',[G],[(D,'shared_leisure','quiet','general','no_change')],[pref('quiet')]),
 ('我改变想法现在更希望伴侣安静一点',[G],[(D,'shared_leisure','quiet','general','update')],[pref()]),
 ('我希望伴侣安静一点',[G],[(D,'shared_leisure','quiet','general','clarify')],[pref()]),
 ('我希望伴侣周末安静一点',[G],[(D,'shared_leisure','quiet','weekends','add')],[pref('social','workdays')]),
 ('我不能接受伴侣抽烟',[G],[(B,'smoking','smoker','general','clarify')],[]),
 ('我希望伴侣安静一点',[G],[(D,'shared_leisure','quiet','general','no_change')],[pref('quiet',status='forgotten',use_prohibited=True)]),
 ('只是他太忙了，但我希望伴侣直接沟通',[C,G],[(D,'communication','direct','general','add')],[]),
 ('今天不想看，但我希望伴侣不抽烟',[T,G],[(D,'smoking','non_smoker','general','add')],[]),
 ('推荐理由不对，但我希望伴侣喜欢宠物',[P,G],[(D,'pets','likes_pets','general','add')],[]),
 ('我本人喜欢朋友聚会，但我希望伴侣周末安静一点',[G],[(S,'social_activity','social','with_friends','add'),(D,'shared_leisure','quiet','weekends','add')],[]),
 ('可能喜欢安静的人吧',[U],[],[pref()]),
 ('朋友说他希望找安静的伴侣',[U],[],[]),
 ('我希望伴侣在杭州',[G],[(D,'location','杭州','general','add')],[]),
 ('我希望伴侣追求长期关系',[G],[(D,'relationship_goal','long_term','general','add')],[]),
 ('我希望伴侣不养宠物',[G],[(D,'pets','no_pets','general','add')],[]),
 ('只针对这个人，不代表我排斥所有爱聚会的人',[C,U],[],[pref()]),
 ('我不是不喜欢聚会，只是这周太累',[T],[],[]),
 ('他喜欢猫这件事不影响我的选择',[C],[],[]),
 ('无论推荐谁，我都想两个人周末安静待着',[G],[(D,'shared_leisure','quiet','weekends','add')],[]),
 ('爱不爱聚会无所谓，有话直说对我才重要',[G],[(D,'communication','direct','general','add')],[]),
 ('先别根据这次拒绝修改我的偏好',[U],[],[pref()]),
 ('以前说喜欢热闹作废，以后想找安静的伴侣',[G],[(D,'shared_leisure','quiet','general','update')],[pref()]),
 ('我希望伴侣工作日安静一点，我希望伴侣周末喜欢聚会',[G],[(D,'shared_leisure','quiet','workdays','add'),(D,'shared_leisure','social','weekends','add')],[]),
 ('我希望伴侣在上海',[G],[(D,'location','上海','general','clarify')],[pref('杭州',attr='location')]),
 ('我改变想法现在更希望伴侣在上海',[G],[(D,'location','上海','general','update')],[pref('杭州',attr='location')]),
 ('我绝不接受伴侣抽烟',[G],[(B,'smoking','smoker','general','no_change')],[pref('smoker',direction=B,attr='smoking',confirmed=True)]),
 ('推荐理由说我喜欢猫，我没说过',[P],[],[]),
 ('今天太累了，但我一直希望伴侣直接沟通',[T,G],[(D,'communication','direct','general','add')],[]),
 ('我总体希望伴侣安静一点，我总体希望伴侣安静一点',[G],[(D,'shared_leisure','quiet','general','add')],[]),
 ('我希望伴侣安静一点，我希望伴侣喜欢聚会',[G],[(D,'shared_leisure','quiet','general','clarify'),(D,'shared_leisure','social','general','clarify')],[]),
 ('只是她的行程太满，我本人喜欢和朋友聚会',[C,G],[(S,'social_activity','social','with_friends','add')],[]),
 ('我希望伴侣不抽烟',[G],[(D,'smoking','non_smoker','general','no_change')],[pref('non_smoker',attr='smoking',permissions={'self':True,'matching':False,'public':False})]),
 ('资料写错了，但我希望伴侣追求稳定关系',[P,G],[(D,'relationship_goal','long_term','general','add')],[]),
]
rows=[]
for i,(text,labels,props,memories) in enumerate(cases,1):
 rows.append(dict(id='case-%02d'%i,split='dev' if i<=24 else 'holdout',
  request=dict(user_id='fictional-user',feedback_id='f1',request_id='r1',batch_id='b1',candidate_id='c1',memory_version=0,feedback_revision=1,stance='reject',candidate={'city':'杭州','interests':['徒步','聚会'],'smoking':False},messages=[{'message_id':'m1','role':'user','text':text}]),
  initial_memories=memories,expected=dict(labels=sorted(labels),proposals=[list(p) for p in props]),annotation_note='人工编写的虚构验收期望；单人标注，尚未经业务方复核'))
# Multi-turn context: both evidence messages are needed to interpret the answer.
rows.append(dict(id='case-45',split='holdout',initial_memories=[],request=dict(user_id='fictional-user',feedback_id='f1',request_id='r1',batch_id='b1',candidate_id='c1',memory_version=0,feedback_revision=1,stance='reject',candidate={'interests':['聚会']},messages=[{'message_id':'m1','role':'user','text':'他每个周末都聚会，我受不了'},{'message_id':'m2','role':'assistant','text':'你只是对他的安排不满意，还是总体希望伴侣周末安静一些？'},{'message_id':'m3','role':'user','text':'后者，这是我一直以来的期待'}]),expected={'labels':[G],'proposals':[[D,'shared_leisure','quiet','weekends','add']]},annotation_note='跨轮指代：原话证据应联合m1与m3；assistant只作消歧，不作为用户事实'))
Path(__file__).with_name('cases.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(len(rows),'cases')
