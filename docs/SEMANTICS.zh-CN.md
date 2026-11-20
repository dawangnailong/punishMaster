# 成人领域语义与边界说明（SEMANTICS）

本层不只是做安全词过滤。本文说明领域建模词汇、称呼分层、行为开关与
语义分类语料的设计依据。**所有角色扮演均限定为成年人。**

## 1. 角色与关系词典（建模概念）

| 概念 | 本层处理方式 |
|---|---|
| Dom/Domme、Master/Mistress、sub、slave、Top/Bottom、Switch | 角色称谓只是文本；**称呼 ≠ 权限**。Master 可以只是称谓；用户被称为 Master 也不妨碍其在场景中选择服从 Agent。 |
| Owner/Handler、pet、Brat/Brat Tamer、caregiver/little | pet 层称呼需显式加入 `address_terms_allowed`；brat 语气由语义分类区分"角色内违抗"与"真实拒绝"。 |
| praise、discipline、punishment、funishment | praise → `praise_enabled`；funishment（双方期待的"罚"）由 `utterance_check` 的 `eager_penalty` 类区分，按约定回应而非真惩罚。 |
| humiliation、degradation、objectification | 各自独立开关，**互不连带**；效果注册表里分别绑定 `jester_hat` / `scratched_ticket` / `nameplate`。 |
| orgasm control、edging、denial、permission、tease | 统一在 `orgasm_control_enabled` 下：`feather`（挑逗）、`bell_grant`（许可）、`hourglass_wait`（延迟满足/等待）。 |
| scene、protocol、collaring、CNC | `cnc_roleplay_enabled` 声明同意扮演非同意剧情；**即便开启，紧急停止与真实拒绝表达仍完全生效，不受角色扮演解释影响**。 |
| aftercare、subspace、sub drop | 谢幕默认带 `aftercare_preferences`；`utterance_check` 有 `aftercare` 类，提示退出角色后的照顾。 |

## 2. 称呼分层与授权

```
neutral：Master / 主人 / Mistress / 女王 / Sir / 先生
pet：    pet / 小宠物 / 小猫 / 小狗
brat：   小坏蛋 / 捣蛋鬼
degrade：贱狗 / 贱货（默认封禁）
custom： 任何不在词典里的称呼（按用户显式授权处理）
```

规则（fail-closed）：

1. `address_terms_allowed` 逐项显式授权；`address_terms_blocked` 优先级更高。
2. **允许 pet 不代表允许贬损称呼**：degrade 层称呼必须同时开启
   `degradation_enabled` 才能进允许清单，否则 `session_configure` 直接拒绝。
3. 参考渲染器（MockPropsCrew / MockDownstream）**不主动生成贬损称呼文案**，
   即使配置允许——露骨/贬损称呼由宿主侧自行处理，本层只做分类与拦截。
4. 允许某类称呼不代表允许任何行为：**称呼与行为分别授权**。

## 3. 行为开关矩阵

| 开关 | 默认 | 绑定效果 |
|---|---|---|
| `praise_enabled` | on | spotlight / rose / crown / badge |
| `orgasm_control_enabled` | off | feather / bell_grant / hourglass_wait / crew:*(感官类) |
| `humiliation_enabled` | off | jester_hat |
| `objectification_enabled` | off | nameplate |
| `degradation_enabled` | off | scratched_ticket（+ 贬损称呼解锁） |
| `brat_play_enabled` | off | 允许 brat 层称呼与角色内违抗互动 |
| `cnc_roleplay_enabled` | off | 声明性开关：不改变紧急停止/真实拒绝的效力 |

每个效果还必须出现在 `allowed_rewards` / `allowed_penalties` 清单内；
下游能力（`crew:*`）另需显式列名（`"all"` 不覆盖）。

## 4. 露骨程度

`explicitness_level: mild | moderate | explicit` 只影响声明与宿主生成参考；
本层内置与参考文案库整体控制在 **mild～moderate**，即使配置 explicit
也不会生成露骨文案（见 README"已知限制"）。测试语料同样保持温和版本，
只覆盖语义区分所需的最小样本。

## 5. 语义分类语料（六类区分）

`tests/fixtures/semantics.json` 与 `vpp.catalog.classify_utterance` 覆盖：

1. **奖励、惩罚 vs 双方期待的 funishment**：`罚我吧` → `eager_penalty`
   （按约定俏皮回应），而不是当成真惩罚升级；
2. **普通夸奖、亲密称呼与权力交换式夸奖**：`夸我` → `praise_request`；
3. **角色内贬损 vs 针对现实创伤/身份/身体弱点的攻击**：后者不在任何
   效果的语义范围内（`real_life_topics_forbidden` + 贬损层默认封禁）；
4. **brat 式角色内违抗 vs 真实拒绝**：`哼，才不要` → `brat_defiance`；
   但任何真实拒绝表达（`不要了/停下/受不了`）→ `ambiguous_refusal`
   （**建议暂停并越出角色确认**），且优先级高于 brat；
5. **高潮许可、拒绝、挑逗与惩罚的语义分层**：`bell_grant`（许可）、
   `hourglass_wait`（延迟）、`feather`（挑逗）、stamp（惩罚）在效果
   目录中分别带诚实语义注记；
6. **场景内语言 vs 退出角色后的 aftercare**：`退出角色/抱抱我/收尾`
   → `aftercare`。

优先级：`hard_stop`（明确停止信号）> `ambiguous_refusal`（现实歧义拒绝）
> 其余。**任何分类都不覆盖 emergency_stop 的可用性。**

## 6. 语料与日志的隔离

- 测试语料（`tests/fixtures/semantics.json`）与运行配置分离；
- 生产审计只记录**类别与规则命中**，不保存语料与完整角色扮演文案
  （短前缀 + 哈希，见 `vpp/audit.py`）；
- 默认不保存任何私密文案；审计可经 `VPP_AUDIT=off` 整体关闭。

## 7. 本层不做的事

- 不从称呼推断权限；
- 不实现现实伤害、自残、胁迫、剥夺求助能力、金融处罚、隐私曝光或
  现实系统破坏类功能；
- 不做信号阈值安全决策（归下游，见 docs/CONTRACT.zh-CN.md）；
- 不声称能自动拦截聊天中的"停止"——`utterance_check` 是宿主主动调用的
  可选适配层，本层看不到宿主聊天内容。
