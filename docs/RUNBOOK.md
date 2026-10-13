# Feedback Memory · 反馈到长期记忆

一个独立的 Python 实验项目：从推荐反馈中提取有证据的长期偏好，通过状态仲裁安全更新记忆。

**当前状态：** 持久化仲裁流程、本地规则提取器、45条虚构标注样本、自动化测试和本地基线对比可运行。兼容 Chat Completions 的真实模型适配器已提供，尚未配置密钥或实测；真实模型准确率、延迟和费用待运行后生成，不用本地结果替代。

## 运行

Python 3.9及以上，运行不需要安装第三方依赖。

```sh
cd feedback-memory
python3 -m unittest discover -s tests -v
python3 -m feedback_memory demo --case case-13
python3 -m feedback_memory evaluate --mode local --out reports/local
```

`demo`输出完整JSON：分类、分项原因、MemoryProposal、仲裁决定、记忆状态、版本、澄清需求和调用统计。case-13演示明确纠正，case-16演示硬边界待确认，case-21演示self与demand分开，case-45演示本地规则无法可靠理解跨轮指代。

评测报告见 `reports/local/REPORT.md`；逐条输出与失败证据见同目录JSON。`demo`使用内存数据库，不保留上次运行状态。

## 持久化使用

```sh
python3 -m feedback_memory init --db state.sqlite --user fictional-user
python3 -m feedback_memory submit --db state.sqlite --input data/example_request.json
python3 -m feedback_memory state --db state.sqlite --user fictional-user
```

同一请求重试使用完全相同的request_id与内容；同一反馈修改时更换request_id、feedback_revision加1，并带当前memory_version。初始有效记忆可通过 `init --memories memories.json --version 3` 注入一次，不接受普通反馈请求覆盖服务端记忆。

```sh
python3 -m feedback_memory confirm --db state.sqlite --user fictional-user --proposal PROPOSAL_ID --version CURRENT_VERSION
python3 -m feedback_memory revoke --db state.sqlite --user fictional-user --memory MEMORY_ID --version CURRENT_VERSION
python3 -m feedback_memory retry --db state.sqlite --job JOB_ID
```

`confirm --reject`拒绝待采用提案。确认和撤销由显式用户操作调用，模型不能代为调用。确认过期提案返回冲突，必须重新提取；重复提交反馈返回首次处理结果快照，要查询最新状态使用state。

## 算法流程

1. **先受理表态。** 校验请求与反馈版本，在事务中保存表态、持久任务，并使该反馈旧的pending提案失效。
2. **拆分语义。** 提取器读取用户反馈、候选上下文和服务端当前记忆，输出多个独立含义。用户消息提供证据，assistant只用于理解上下文。
3. **检查结构和来源。** 限制分类、方向、属性和状态枚举；引用必须精确定位当前请求中的用户原话。模型不能指定有效状态、公开权限或直接执行数据库操作。
4. **仲裁。** 同方向/属性/情境的相同值为no_change；明确纠正为update；不同情境为add；歧义、同一反馈自相矛盾、未确认硬边界为clarify。临时状态与单人反馈不生成长期偏好。
5. **原子提交。** 再查feedback_revision与memory_version。任何更新使旧异步任务返回stale，不写入。旧记忆被替代但保留来源，版本只在实际记忆变化时递增。
6. **权限撤销。** 禁止使用的记忆及相同属性/情境的派生修订不再参与匹配，旧提案失效。重新启用需要独立授权流程，此实验不自动重新启用。

普通明确软偏好自动采用，`confirmed=false`表示没有额外点击确认，不表示未生效；boundary必须通过confirm成为有效记忆。已采用偏好不因单次表态更改自动撤销。公开权限始终默认关闭。实验中的新软偏好按“已获内部匹配许可”的虚构业务前提写入；真实接入时需将该前提连接到账户级用途授权。

## 文件结构

| 文件 | 职责 |
|---|---|
| feedback_memory/engine.py | SQLite状态、幂等、仲裁、确认、撤销、任务恢复 |
| feedback_memory/extractors.py | 本地单含义基线、多含义规则提取、真实LLM接口及提示词 |
| feedback_memory/evaluation.py | 指标口径、分集评测、逐条输出、失败报告 |
| feedback_memory/cli.py | 命令行入口 |
| data/cases.json | 45条虚构输入与人工编写的期望标签、提案、仲裁动作 |
| tests/ | 状态安全与评测计数测试 |

## 基线与评测

本地基线只保留第一段含义，改进版保留多段含义并联合检查冲突。两者共用同一仲裁器，比较的是提取覆盖与其对仲裁的影响。这个基线是透明的简化规则基线，不能称为单次LLM实测。

LLM模式两条路线均为单次调用、相同模型、相同schema、相同仲裁器：基线用简短分类提取说明，改进提示明确多含义、否定转述、临时状态、证据与纠正。模型端JSON格式遵循服务商兼容协议，尚未做在线兼容性验证；没有声称增加调用或复杂Agent框架必然提高效果。

45条样本中开发集24条、预留集21条。它们是单人编写的合成验收集，并非外部独立盲测。指标包含多标签分类micro/macro Precision/Recall/F1、四元组提案Precision/Recall、错误长期写入率、冲突纠正正确率、原话定位准确率、调用延迟与token成本。证据原文存在不等于语义蕴含成立，测试专门保留了这个边界。

## 之后配置真实模型

在本地终端设置 `MODEL_BASE_URL`、`MODEL_NAME`、`MODEL_API_KEY`。不要把密钥写入代码、评测文件或提交版本库。`.env.example`是字段说明，不会被程序自动读取。

```sh
python3 -m feedback_memory evaluate --mode llm --out reports/llm
```

命令会将虚构评测输入发送到所配置的模型服务，运行45条×2路线。请求无自动网络重试，避免隐式重复费用。失败案例计入分母；服务失败不会写记忆，持久任务可以重试。输入/输出单价配置后计算费用估计，未配置显示N/A；缓存计费与阶梯价格不在估计中。日志不打印密钥或服务端错误原文。

## 对原设计的具体改进

1. **分类从单标签改为多含义。** 针对某人和普遍期待可以同句出现，先拆独立结论，再逐条仲裁。
2. **把“证据存在”与“证据支持结论”分开。** 程序验证引用位置，语义支持由标注评测与模型能力验证；不能用引用通过率代替记忆准确率。
3. **异步结果同时检查两种版本。** memory_version保护后来纠正，feedback_revision保护表态撤改；任何一个过期都不能写。
4. **撤销是持续约束。** 权限撤销保留禁止使用标记，关联旧提案失效，避免新请求重新提炼旧结论后又用于匹配。
5. **不修改记忆也是完整结果。** 记录原因与分类，不靠生成更多卡片来证明系统有效。

## 边界

属性字典覆盖七类实验属性，不能理解任意业务维度；本地规则无法可靠处理复杂否定、隐含意图、跨轮指代。LLM输出的certainty/correction依然是模型判断，不能把程序校验通过称为语义保证。生产接入还需要认证授权、完整属性字典、独立人工复核样本、监控和真实服务验证。CLI的user_id是实验身份参数，不是互联网多用户鉴权系统。

SQLite支持事务和重启恢复；prepare/run_job可分离以模拟异步执行，但没有常驻任务调度器。此范围满足独立算法实验，不声称已部署后台服务。
