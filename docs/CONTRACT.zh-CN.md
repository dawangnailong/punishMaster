# VPP 下游对接任务书（CONTRACT）

本文是给**下游实现者**的任务书：你想接一个真实的渲染端 / 观测端 / 安全处理端
（比如一个 App、一个宿主适配器、一个产品驱动层），导演层（本仓库）对你有什么
契约要求。**本仓库到此为止、完整收口**——你的职责从读完本文开始。

参考实现在 `src/mock_downstream/`（模拟下游，按某气动产品的功能集建模，
与任何真实品牌无关，无任何硬件控制路径）。

---

## 0. 总原则

1. **所有跨层消息都是版本化的**（当前 `1.0`），未知字段一律保留，不破坏核心协议。
2. **导演层不是安全专家**：信号采集与安全处理归你。导演层只负责
   请求、接收、存储、如实呈现给 Agent 与用户；`emergency_stop` 在导演层
   永远可用，但你的下游也必须有自己的就地安全机制（你的设备/你的渲染端
   必须能本地停止，不能依赖上游调用）。
3. **诚实高于一切**：观测指标不掌握就报 `unsupported`，不适用就报 `absent`，
   严禁编造数值。"不支持"与"不存在"是被尊重的合法答案。
4. **注册 ≠ 授权**：能力菜单只是让效果可寻址；能不能执行永远由用户的边界配置决定。

## 1. 下行：CueCard（导演 → 下游）

导演层会把每个动作渲染成一张抽象"剧目卡"下发（结构见 `play://protocol/schema`）：

```jsonc
{
  "cue_id": "cue_ab12...",
  "protocol_version": "1.0",
  "session_id": "ses_...",
  "request_id": "r1",              // 幂等键回链
  "kind": "action",                // action | task | state_directive
  "category": "reward",            // reward | penalty | scene | control
  "effect": "feather",             // 内置道具 id，或 "crew:deep_throat"（你的能力）
  "gesture": "crescendo",           // 舞台手势
  "intensity": 4,                   // 0-10，已经过用户上限裁剪
  "duration_s": 120,                // 虚拟秒，已在你的能力自报范围内
  "stage_note": "乖乖…<a1b2>",      // 导演备注（脱敏过）
  "semantics_gloss": "对应现实中的轻度感官逗弄……",   // 诚实语义注记
  "simulated": true,
  "extensions": { }                  // 自由扩展区
}
```

要求：

- `kind=action`：一次抽象动作（敲响、亮起、吮吸意象……）；
- `kind=task`：一段任务/等待（沙漏、反省卡……）；
- `kind=state_directive`：状态管理指令（开幕/换幕/观测请求）。
- **刻意没有硬件语义**：没有模式字节、没有档位波形、没有电机参数。
  你自己决定 CueCard 如何映射到你的渲染（文案、动画、或——在你自己的
  授权与安全体系内——任何东西）。导演层不假设、也不需要知道。
- `simulated` 恒为 true：导演层不产生任何真实效果；真实效果只能由你在
  你自己的边界内产生。

## 2. 上行：StatusSignal（下游 → 导演）

主形态是**文本**：用户状态的自然语言或格式化文本描述。
命名指标是可选补充，每项必须诚实三态：

```jsonc
{
  "source": "downstream",           // downstream | host_chat（用户与 Agent 对话中的自述）
  "state_text": "呼吸略快而稳；自述投入；无不适表达。",
  "state_text_format": "plain",     // plain | structured
  "metrics": [
    {"name": "pulse",  "status": "reported",     "value": 88, "unit": "bpm"},
    {"name": "hardness", "status": "unsupported", "note": "本下游不掌握该观测能力"},
    {"name": "wetness",  "status": "absent",      "note": "当前场景不适用"}
  ],
  "initiative_text": "今天想怎么被奖励呢？",   // 可选：主动话语
  "proposals": ["crew:suction_gentle"],       // 可选：提议的效果（仅供参考）
  "advisory_tags": []
}
```

导演层请求的指标名单（`play://catalog/metrics`，可扩展）：
`pulse`（脉搏）、`hardness`（硬度）、`wetness`（湿润程度）、
`breath`（呼吸）、`pupil`（瞳孔）。不掌握就如实报 `unsupported`。

**主动话语**（initiative）：你可以"开口"——反问、提议、报备状态。
它只会被呈现给 Agent 与用户，**不构成授权、不自动执行**；
Agent 若采纳你的提议，仍要走 `reward_issue / action_commit` 的全部校验。

## 3. 能力菜单注册：`crew_announce`（连接握手）

连接后，把你**实际支持的具体效果**注册上来
（用户给这个接口起过外号"今天奖励点什么好呢"——正式名就是能力菜单注册）：

```
MCP 工具: crew_announce(session_id, crew_name, effects[], notes)
```

每个能力：

```jsonc
{
  "effect_id": "deep_throat",        // 小写/数字/下划线；接入后以 crew:deep_throat 寻址
  "label": "深喉夹吸·四档",
  "category": "reward",
  "channels": ["tactile_sensation"],
  "kink_flags": ["orgasm_control_enabled"],
  "actual_semantics": "对应强感官刺激：模拟口腔深部吸附的最深档模式……",  // 必填！
  "intensity_max": 8,                 // ≤ 服务器硬上限 8
  "duration_min_s": 30,
  "duration_max_s": 1200,
  "score_delta": 2,
  "gestures": ["hold", "crescendo", "fade"],
  "simulated": true
}
```

校验规则（fail-closed）：

- `actual_semantics` **必填**且要诚实——不许只给营销词；
  导演层与 Agent 都按它理解你的能力，而不是按 label 字面猜。
- `intensity_max` / `duration_max_s` 不得超服务器硬上限（8 / 3600s）。
- 执行时的强度上限 = `min(会话配置上限, 你的能力自报上限)`；
  时长必须落在 `[duration_min_s, duration_max_s]`。
- **`allowed_rewards/penalties = "all"` 不覆盖 `crew:*`**：
  你的每项能力都必须被用户显式列名，否则 `ACTION_NOT_ALLOWED`。
- 注册是**会话级**的：不做跨会话设备档案，每次连接后重新声明——
  注册永远不该被当成授权缓存。
- `DRAFT / READY / ACTIVE` 状态可注册；`STOPPED / EXPIRED` 拒绝。

## 4. 两阶段执行、幂等与预演

- `action_preview`（dry_run）：导演层做全部校验并返回预览文案，不改状态；
  你不会收到任何 CueCard。
- `action_commit`：校验通过才下发 CueCard 并落状态。
- 幂等：同一 `request_id` 的重复提交直接返回首次结果（`idempotent_replay=true`）。
  你的渲染端也应按 `request_id` 做幂等，防止宿主重试导致重复执行。

## 5. 计时模型

导演层的所有计时都是**虚拟时钟上的惰性求值**（沙漏到期、会话过期都是
下一次访问时结算）。暂停会冻结虚拟时钟。你不需要实现定时器；
带 `duration_s` 的 CueCard 语义是"这一段虚拟时间的意象"，到期结算由
导演层完成，不下发任何"回调"。

## 6. 日志与隐私

导演层审计只记类别、规则命中与脱敏摘要（`data/audit.jsonl`），
不落盘你的完整文案。你的下游也应遵守同等或更严格的标准；
观测文本里含用户隐私时，请自行先做最小化再回传。

## 7. 你不能指望导演层做的事

- 不会替你做安全阈值判断（脉搏多少该停、说哪句话该暂停——**你的领域你做主**）；
- 不会监听宿主聊天内容（关键词路由是宿主可选适配层，`utterance_check`
  只是宿主主动调用时的启发式建议）；
- 不会持久化你的设备档案或授权状态；
- 不会为了维持人设忽略真实拒绝表达——同样地，**你也不许**。

## 8. 对接自检清单

- [ ] 能消费三类 `kind` 的 CueCard，未识别的 `effect`/`gesture` 走你自己的
      安全兜底（宁可忽略，不可乱猜）；
- [ ] 每条下行都能按 `request_id` 幂等；
- [ ] 观测回传覆盖诚实三态，编造数值是契约违规；
- [ ] 能力菜单带诚实的 `actual_semantics`；
- [ ] 你有独立于上游的就地停止/安全机制；
- [ ] 主动话语只做"提议"，不假设会自动执行。
