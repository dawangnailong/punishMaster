# 设备契约（DEVICE CONTRACT）

本文是设备实现者（虚拟设备或真实设备适配器）与 MCP 设备面之间的契约。
目标：**同一份接口，虚拟设备与真实设备在 MCP 视角下可整体替换。**

版本：`0.1`。未知字段一律保留（`extra=allow`）。

---

## 0. 总原则

1. **设备是黑盒。** 上层不假设电机、波形、气泵、寄存器。
2. **语义优先。** 上层说的是「对用户做什么」；设备决定怎么实现。
3. **强度/档位保留。** 档位是体验级参数（1..设备上限），不是电机占空比。
4. **不支持就拒绝。** `realization=unsupported` 必须显式返回
   `supported=false / executed=false`；不得用旁白冒充物理执行。
5. **安全归硬件。** 设备自己消费原始数据并随时准备自动停止；上游只能建议，不能覆盖。
6. **原始数值不上行。** Agent 侧只有语义反馈与可选影像。

## 1. 能力声明 `DeviceCapabilities`

```jsonc
{
  "contract_version": "0.1",
  "device_id": "sim-cup-01",
  "device_class": "suction_cup",
  "label": "模拟气压吮吸器具（虚拟设备）",
  "simulated": true,
  "level_max": 8,
  "semantic_actions": [
    {
      "action_id": "stimulate",
      "label": "刺激",
      "category": "stimulate",
      "realization": "native",
      "description": "对用户施加刺激；深度/节奏/温度由语义参数表达。",
      "params_schema": {
        "depth":  {"enum": ["shallow", "deep"], "default": "shallow"},
        "rhythm": {"enum": ["steady", "pulse", "wave"], "default": "steady"},
        "warmth": {"enum": ["none", "warm"], "default": "none"}
      },
      "requires_consent": true
    }
  ],
  "modes": [
    {"mode_id": "gentle", "label": "轻吮", "level_max": 4},
    {"mode_id": "deep", "label": "深部", "level_max": 8}
  ],
  "supports_media": false,
  "safety": {
    "local_auto_stop": true,
    "physical_stop_button": true,
    "agent_stop": true,
    "raw_sensor_data_exposed": false,
    "reasoning_request": true
  }
}
```

### `realization` 三态

| 值 | 含义 | 执行行为 |
|---|---|---|
| `native` | 设备原生理解并执行该语义动作 | 直接执行 |
| `mode_mapping` | 设备不能原生执行，但能映射到某个模式 | 通过 `mapped_mode_id` 执行模式 |
| `unsupported` | 设备明确做不到 | 返回 `supported=false`，绝不旁白代替 |

核心动作由 `ontology.py` 共享；厂商扩展动作使用自己的 `action_id`，
但必须落回同一套字段与三态。

## 2. 执行 `device_do` / `ActionRequest`

```jsonc
{
  "action_id": "stimulate",
  "intent": "奖励主人尝一下自己最里面",   // 仅记录，不自动映射
  "level": 4,
  "duration_s": 60,                      // 0 = 持续到显式 stop
  "params": {"depth": "deep", "rhythm": "pulse", "warmth": "warm"}
}
```

返回 `DeviceActionResult`：

```jsonc
{
  "contract_version": "0.1",
  "device_id": "sim-cup-01",
  "simulated": true,
  "accepted": true,
  "executed": true,
  "supported": true,
  "realization": "native",
  "message": "已执行语义动作 `stimulate`：深部、节奏起伏。本设备为模拟设备，无真实接触。",
  "state": { "...": "见第 3 节" },
  "error": null
}
```

拒绝分两类：

- **不支持**：`supported=false`、`realization=unsupported`、`executed=false`，
  `error.code=UNSUPPORTED`；
- **参数非法**：`supported=true`、`accepted=false`、`executed=false`，
  `error.code` 例如 `LEVEL_OUT_OF_RANGE` / `DURATION_EXCEEDED`。

## 3. 状态 `DeviceState`

```jsonc
{
  "device_id": "sim-cup-01",
  "simulated": true,
  "running": true,
  "current_action": "stimulate",
  "current_mode": null,
  "level": 4,
  "remaining_s": 60,
  "feedback": "深部、节奏起伏",
  "safety": "ok",
  "fault": null
}
```

**不得包含**原始传感器数值（心率、气压、温度读数、电机转速……）。
`feedback` 是语义文本；数值只留在设备内部。

## 4. 停止

停止有四个来源，共用一条路径：

| source | 触发者 |
|---|---|
| `agent` | Agent 调用 `device_stop` |
| `hardware` | 设备上的物理 stop 按钮 |
| `safety` | 设备本地安全策略自动停止 |
| `timer` | 动作到时结束 |

要求：

- **幂等**：已经是停止状态时返回 `executed=false`，不报错；
- **随时可用**：不依赖当前动作、模式或上游状态；
- **本地优先**：上游停止不是唯一保障；硬件必须能自己停；
- **断连即停**：真实设备与上游失联时，本地必须停止（实现者责任）。

## 5. 安全与推理请求

- 设备自己消费原始数据，持续评估本地安全；触发时自动停止并记录 `safety` 事件。
- 允许设备在接近本地安全边界时发 `reasoning_request` 事件，请求上游协助判断；
  上游的回复只是建议，**不能覆盖硬件的本地停止权**。
- Agent 不应把 `reasoning_request` 当成继续运行的许可。

事件结构：

```jsonc
{
  "event_id": "evt_0001",
  "cursor": 1,
  "kind": "reasoning_request",
  "semantic_text": "接近本地安全上限；硬件请求上游协助判断是否继续或调整。",
  "data": {}
}
```

`device_events(cursor)` 返回 `events` 与 `next_cursor`；Agent 用游标增量轮询。

## 6. 反馈与影像

- 主形态：语义文本（`feedback`、事件 `semantic_text`）；
- 可选：`MediaItem`（`kind=image|video`、`uri`、`caption`）；
- **不提供**原始传感器数值给 Agent；
- 影像的采集、存储与隐私边界由设备/宿主负责，本层只呈现引用。

## 7. 虚拟设备的诚实规则

- `simulated=true` 对 Agent 可见；
- 行为与真实设备等价，但不产生真实接触；
- 消息中明确说明「本设备为模拟设备，无真实接触」；
- 不支持的能力与真实设备一样显式拒绝，不因为「反正是模拟」就放宽。

## 8. 实现者检查清单

- [ ] `capabilities()` 声明所有动作的 `realization`；
- [ ] `unsupported` 动作返回 `supported=false / executed=false`；
- [ ] `stop()` 幂等，且本地安全路径独立于上游；
- [ ] 状态与事件中没有任何原始传感器数值；
- [ ] `simulated` 如实填写；
- [ ] 断连/超时/断电时本地停止；
- [ ] 通过仓库的契约测试（可作为适配器验收套件的基础）。
