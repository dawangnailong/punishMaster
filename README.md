# VPP 拟物互动导演台（punishMaster）

一个**完全虚拟**的"互动场景执行器"：Agent（如 Claude）可以在用户明确授权的边界内，
对用户（Master）进行奖励或虚拟惩罚。"完全虚拟"指：真实桥接项目的**函数形状都在**
（扫描设备 `link_scan`、连接 `link_connect`、能力注册 `crew_announce`、观测回传
`signal_report`），但**业务全部掏空为本地模拟**——`link_scan` 遍历的是假想设备名册
（假想注册），`link_connect` 是一次本地状态写入，效果渲染成舞台意象文本。
**不连接、不扫描、不控制任何真实硬件，不产生任何现实副作用**（源码级禁止硬件与
网络导入，由测试强制）。

诚实优先于拟物：每个效果都有直白语义名 `plain_name`（口头嘉许/角色内表扬/冷处理/
高潮许可宣告……）作为 Agent 面前的第一名称；舞台意象名（银铃、聚光灯、沙漏……）
只是文案皮肤。链路操作的返回用直白语言如实叙述"此刻实际发生与没有发生的事"
（`happening_now` 字段），不得拟物包装系统行为——防止 Agent 或用户误解为
发生了真实的扫描/连接/控制。

一句话定位：**统一 AI 驱动成人娱乐的方法层**——边界配置、显式授权、诚实语义、
观测契约与安全不变量在此收口，可移植到任何下游；实际渲染与安全处理归下游。

> 18+ only。仅面向成年人的自愿互动。**现实中的控制权始终属于用户**；
> 本项目不含任何媒体与露骨内容，内置文案整体保持在温和～中等水平。

参考项目 [dsh-tf-bhpro](https://github.com/RadeyesDrosophilaProMax/dsh-tf-bhpro)
的交互分层（控制面板 / 关键词路由 / 状态持久化 / 日志 / 可选模型工具），
不复刻其 BLE 硬件协议，也不考虑与任何现有厂商兼容。

---

## 1. 架构：一层收口

```
┌──────────────────────────────────────────────────────────────┐
│  MCP 接口层  src/vpp/server.py                               │
│  21 个工具 / 10 个资源 / 3 个提示词（stdio transport）        │
├──────────────────────────────────────────────────────────────┤
│  导演层  src/vpp/director.py   ← 全部业务规则，fail-closed    │
│  状态机 DRAFT→READY→ACTIVE⇄PAUSED→STOPPED/EXPIRED            │
├──────────────────────────────────────────────────────────────┤
│  虚拟链路层  src/vpp/link.py（假想设备名册，函数形状保留）     │
│  link_scan 遍历本地名册 / link_connect 本地状态写入           │
├──────────────────────────────────────────────────────────────┤
│  VPP 协议层  src/vpp/protocol.py（版本化信封/结果/错误）      │
│  下行 CueCard（抽象动作/任务/状态指令）                       │
│  上行 StatusSignal（文本为主的用户状态 + 诚实三态指标）        │
│  能力菜单 CapabilitiesDeclaration（crew_announce，注册≠授权） │
├──────────────────────────────────────────────────────────────┤
│  CrewPort（下游契约接口）                                    │
│  ├─ MockPropsCrew   层内兜底拟物渲染器（开箱可用）            │
│  └─ MockDownstream  独立模拟下游（src/mock_downstream/）     │
│     E-Pneumatic-Pro 风格能力菜单：4 档气压吸吮 + 一键爆发 + 恒温层 │
└──────────────────────────────────────────────────────────────┘
```

**本层到此为止、完整收口**：下发什么由 CueCard 抽象描述（动作/任务/状态管理指令，
无任何硬件语义）；怎么渲染、怎么观测、**安全处理**都归下游。
观测以文本为主形态回传，指标必须诚实三态。

## 2. 安装

需要 Python 3.11+。

```bash
cd punishMaster
python3 -m venv .venv
.venv/bin/pip install -e .        # 或：.venv/bin/pip install .
.venv/bin/pip install pytest      # 测试用
```

不想安装也可以直接 `PYTHONPATH=src` 运行（见下）。

## 3. 启动

```bash
# 方式一：模块入口（stdio，MCP 默认传输）
PYTHONPATH=src .venv/bin/python -m vpp.server

# 方式二：安装后的入口脚本
.venv/bin/vpp-server
```

stdout 是 stdio MCP 的传输线——本服务**从不在 stdout 打印任何日志**
（审计走 `data/audit.jsonl`，普通日志走 stderr，且默认 WARNING 级）。

环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `VPP_STORE` | `json` | `json`=文件持久化；`memory`=内存（测试） |
| `VPP_DATA_DIR` | `./data` | 状态文件 `sessions.json` 与审计 `audit.jsonl` 所在目录 |
| `VPP_AUDIT` | `<data>/audit.jsonl` | 审计路径；`off` 关闭 |
| `VPP_LOG_LEVEL` | `WARNING` | stderr 日志级别 |

## 4. MCP 客户端配置

Claude Code（项目 `.mcp.json` 或全局配置）：

```json
{
  "mcpServers": {
    "vpp-play": {
      "command": "/home/you/punishMaster/.venv/bin/python",
      "args": ["-m", "vpp.server"],
      "env": { "PYTHONPATH": "/home/you/punishMaster/src", "VPP_DATA_DIR": "/home/you/punishMaster/data" }
    }
  }
}
```

Claude Desktop：等价地填入 `command` / `args` / `env` 三个字段。

## 5. Inspector 验证

```bash
.venv/bin/pip install "mcp[cli]"
.venv/bin/mcp dev src/vpp/server.py
# 打开其打印的 URL：Tools / Resources / Resources Templates / Prompts 四个页签
```

或者用仓库自带的"等效客户端验收脚本"（无 Node 依赖，12 步全流程自动断言）：

```bash
PYTHONPATH=src .venv/bin/python examples/full_flow.py
```

它会依次走：创建 → 配置边界 → 授权 → 扫描假想设备名册 → 连接模拟设备 →
下游注册能力菜单 → 预演 → 奖励 → 注册能力（crew:deep_throat 四档）→
虚拟惩罚 → 暂停 → 恢复 → 历史 → 下游观测回传（诚实三态）+ 主动话语 →
紧急停止 → 停止后拒绝执行。

## 6. 示例交互

Agent 侧一次典型会话（节选自 `examples/full_flow.py` 的实际输出）：

```
① session_create            → {state: DRAFT, next_steps: [...]}
② session_configure         → 边界：称呼小猫、强度≤5、单动作≤600s、
                               允许奖励清单含 crew:deep_throat、惩罚清单含 stamp
③ session_authorize         → consent_note 非空 → READY
④ scene_resume              → 「丝绒大幕拉开……小猫，戏开始了。」
④a link_scan / link_connect → 假想名册 2 条；连接=本地状态写入（连接≠授权）
    happening_now 如实叙述：「没有发生任何蓝牙/串口/网络扫描……」
④b crew_announce            → 下游注册 4 档吮吸 + 一键爆发 + 恒温层（注册≠授权）
⑤ action_preview            → dry_run：完整校验、预览文案、零状态变更
⑥ reward_issue spotlight    → 「主灯缓缓推亮……」＋语义注记＋〔全模拟〕
⑥b reward_issue crew:deep_throat → 四档深部吮吸的意象文案（模拟下游渲染）
⑦ penalty_issue stamp       → 「印章『咚』地盖下……」 计分 -1
⑩ signal_report             → pulse:reported(88bpm) hardness:unsupported
                               wetness:absent —— 严禁编造，不支持就说不支持
⑩+ 下游主动话语             → 「今天想怎么被奖励呢？菜单上有轻档也有深档。」
⑪ emergency_stop            → 任意状态可调、幂等、立即清空虚拟时间线
⑫ 再次 reward_issue         → 已拒绝（INVALID_STATE）
```

每个动作消息的尾部都带两行小字：
`〔语义注记：…〕`（诚实说明该道具对应现实中哪类活动）与
`〔全部为本地模拟的舞台意象…〕`。

## 7. VPP 协议速览

- **下行 `ActionEnvelope`**：`protocol_version / request_id(幂等) / session_id /
  category(reward|penalty|scene|control) / effect / intensity(0-10) /
  duration_s / reason(脱敏) / dry_run / extensions`。
- **下行 `CueCard`**（发给下游）：`kind=action|task|state_directive`、
  `gesture` 舞台手势、`semantics_gloss` 诚实语义、自由 `extensions`。
  **刻意无硬件语义**（无档位波形电机）。
- **上行 `StatusSignal`**：`source=downstream|host_chat`、`state_text`
  （**主形态**：自然/格式化文本）、`metrics[]`（诚实三态
  `reported|unsupported|absent`，reported 必带 value，严禁编造）、
  `initiative_text + proposals[]`（下游主动话语，仅呈现不执行）。
- **虚拟链路 `link_scan / link_connect / link_disconnect`**：假想设备名册
  （`registration=hypothetical`）；「扫描」= 遍历本地内存记录，「连接」=
  本地状态写入；返回的 `happening_now` 如实叙述此刻发生与没有发生的事。
  **连接 ≠ 授权**。
- **能力菜单 `crew_announce`**：下游连接后注册 `crew:<effect_id>` 能力；
  **注册 ≠ 授权**，执行照走允许清单 + 行为开关 + 上限。
- **统一 `ActionResult`**：`accepted / executed / simulated:true / state /
  message / scheduled_effects / warnings / audit_id / error{code,message,hint}`。
- **标准错误**：`INVALID_ARGUMENT / SESSION_NOT_FOUND / INVALID_STATE /
  CONSENT_REQUIRED / LIMIT_EXCEEDED / ACTION_NOT_ALLOWED / EXPIRED / INTERNAL_ERROR`。
- **两阶段与幂等**：`action_preview → action_commit`；同 `request_id` 重复提交
  原样返回（`idempotent_replay:true`），不会重复执行。
- **扩展规则**：未知字段一律保留（extra=allow），不破坏核心协议。

完整 schema 见资源 `play://protocol/schema`；下游对接任务书见
[docs/CONTRACT.zh-CN.md](docs/CONTRACT.zh-CN.md)。

## 8. 安全设计（摘录，全文见 `play://safety/policy`）

1. 新会话默认不可执行任何奖励/惩罚：`configure → authorize → 开场`，缺一不可。
2. 强度/时长**双重硬上限**：Agent 不可突破用户配置，用户配置不可突破服务器硬上限
   （intensity≤8、单动作≤3600s、场景≤8h）。
3. fail-closed：规则不明、配置缺失、状态冲突一律拒绝，绝不猜用户意图。
4. `emergency_stop`：任意状态、无需确认、幂等、立即清空虚拟时间线。
   **CNC 开启也不改变紧急停止与真实拒绝表达的效力。**
5. 称呼与行为分别授权；贬损称呼须同时开 `degradation_enabled` 才允许配置；
   参考渲染器仍不主动生成贬损称呼文案。
6. 反实验护栏：同类效果累计第 3 次执行自动挂 warning——用户反应是多通道并行的
   不可预测现象，禁止把用户当验证"机制"的实验对象。
7. 诚实语义：每个道具都带 `actual_semantics` 注记；`CueCard` 不承诺任何
   反应、顺序或确定性输出。
8. 观测信道诚实三态；**信号采集与安全处理归下游**，本层只采集、存储、如实呈现。
9. 无后台线程/定时器：所有计时是注入时钟上的虚拟时间、惰性求值——
   停止后不存在继续触发的后台任务是**结构性保证**。
10. 审计最小化：不落盘完整角色扮演文案（短前缀+哈希），stdout 只留给 MCP 传输，
    无遥测、无外部服务。

## 9. 测试

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

覆盖任务书第九节全部 12 项验收 + 领域语义语料 + 下游契约回环：

| 验收项 | 对应测试 |
|---|---|
| 工具/资源可发现 | `test_discovery.py` |
| 未授权不可执行 | `test_safety_and_lifecycle.py::test_actions_rejected_before_authorize` |
| 合法奖惩产生模拟结果 | `test_actions.py::test_reward_and_penalty_produce_simulated_results` |
| 越界强度/超长时长被拒 | `test_safety_and_lifecycle.py::test_over_limits_rejected` |
| 非法状态转换被拒 | `test_safety_and_lifecycle.py::test_illegal_transitions_rejected` |
| emergency_stop 全场景 | `test_safety_and_lifecycle.py::test_emergency_stop_active_paused_repeat` |
| 停止后无后台任务 | `test_safety_and_lifecycle.py::test_no_background_tasks_after_stop` |
| 幂等不重复执行 | `test_actions.py::test_idempotent_request_id` |
| dry_run 不改状态 | `test_actions.py::test_dry_run_does_not_mutate` |
| replay 重现事件序列 | `test_replay_persistence.py::test_replay_reproduces_event_sequence` |
| 持久化可恢复 | `test_replay_persistence.py::test_persistence_roundtrip` |
| 无真实硬件/网络路径 | `test_no_real_hardware.py`（源码级扫描 + 能力声明断言） |
| 虚拟链路（假想注册） | `test_virtual_link.py`（扫描/连接的函数形状 + 诚实叙述 + plain_name 完整性） |

另有：领域语义语料（`test_semantics.py` + `tests/fixtures/semantics.json`）、
诚实三态与主动话语（`test_signals.py`）、能力菜单注册≠授权
（`test_crew_registration.py`）、模拟下游契约回环（`test_mock_downstream.py`）。

## 10. 已知限制

- 内置/参考文案库整体是温和～中等的中文拟物风格；`explicitness_level=explicit`
  只作为声明被接受，本层不会生成露骨文案（露骨内容由宿主侧自行处理）。
- `utterance_check` 是**可选宿主适配层**：本层无法看到宿主聊天内容，须宿主主动
  传入文本；它只给分类建议，不做权限推断，也不替代下游安全处理。
- replay 覆盖动作信封序列及其状态效果；工具级转换（暂停/恢复/停止）由状态机
  保证合法性，不在逐条比对范围内。
- 能力菜单是**会话级**注册（不做跨会话持久设备档案）；每次连接后需重新声明，
  这是故意的——注册永远不该被当成授权缓存。
- 模拟下游（`src/mock_downstream/`）参考了 E-Pneumatic-Pro 产品的公开功能描述
  做能力菜单建模，**与该品牌无任何关联，不含任何真实控制路径**；文案库风格
  可按接入方需求整体替换。

## 11. 许可

MIT。
