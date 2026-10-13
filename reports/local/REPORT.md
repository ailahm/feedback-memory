# 反馈记忆算法评测

这是本地规则实验，未调用真实模型，不能据此推断LLM语义质量或模型成本。

45条虚构样本：开发集24条，预留评测集21条。单人标注，未经过业务方独立复核；本地规则在阅读整个任务时编写，预留集不代表独立盲测。

## 预留集对比

| 指标 | 基线 | 改进 |
|---|---|---|
| 分类micro Precision | 0.7143 | 0.7692 |
| 分类micro Recall | 0.6000 | 0.8000 |
| 分类micro F1 | 0.6522 | 0.7843 |
| 提案Precision | 1.0000 | 1.0000 |
| 提案Recall | 0.5000 | 0.8333 |
| 错误长期写入比例 | 0.1667 | 0.0000 |
| 冲突与纠正正确率 | 0.6667 | 0.8333 |
| 证据原文定位准确率 | 1.0000 | 1.0000 |
| 提取延迟p50毫秒 | 0.0135 | 0.0125 |
| 提取延迟p95毫秒 | 0.0249 | 0.0225 |
| 模型输入tokens | 0.0000 | 0.0000 |
| 模型输出tokens | 0.0000 | 0.0000 |
| 模型成本 | 0.0000 | 0.0000 |

## 口径

分类为多标签micro/macro指标。提案以方向、属性、值和情境四元组精确匹配；仲裁再加入动作。错误写入率分母是实际add/update数，分子是与标注不符的写入数。冲突集包含预期update/clarify/no_change的样本。证据指标只验证原话连续片段的定位，不证明原话蕴含提案；语义错误由提案指标与失败分析覆盖。调用延迟只计提取器，不计数据库；本地0 tokens表示没调用模型。

## 失败案例

- case-28：我不是不喜欢聚会，只是这周太累
  期望：['current_state'] / []；实际：['unclear'] / []；错误：None。
- case-29：他喜欢猫这件事不影响我的选择
  期望：['candidate_specific'] / []；实际：['unclear'] / []；错误：None。
- case-30：无论推荐谁，我都想两个人周末安静待着
  期望：['general_preference'] / [['demand', 'shared_leisure', 'quiet', 'weekends', 'add']]；实际：['unclear'] / []；错误：None。
- case-31：爱不爱聚会无所谓，有话直说对我才重要
  期望：['general_preference'] / [['demand', 'communication', 'direct', 'general', 'add']]；实际：['unclear'] / []；错误：None。
- case-33：以前说喜欢热闹作废，以后想找安静的伴侣
  期望：['general_preference'] / [['demand', 'shared_leisure', 'quiet', 'general', 'update']]；实际：['general_preference', 'unclear'] / [['demand', 'shared_leisure', 'quiet', 'general', 'clarify']]；错误：None。
- case-45：他每个周末都聚会，我受不了 / 你只是对他的安排不满意，还是总体希望伴侣周末安静一些？ / 后者，这是我一直以来的期待
  期望：['general_preference'] / [['demand', 'shared_leisure', 'quiet', 'weekends', 'add']]；实际：['unclear'] / []；错误：None。

本地规则的主要限制是隐含普遍偏好、否定嵌套、跨轮指代和自然纠正措辞。接入模型后必须用相同样本重跑，不能沿用本地结果。两条路线共用仲裁器，这个对比隔离了提取策略差异；并未衡量移除事务和校验后的安全增益。
