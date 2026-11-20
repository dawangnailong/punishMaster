# punishMaster — 设备契约层

2026-11-20 起，仓库推倒重来。旧的「拟物互动导演台」实现完整保存在分支
`v0-simulation`（tag `v0-archive`），不再作为当前方向。

当前项目只做一件事：**定义一台设备对 MCP 暴露什么，并用一台虚拟设备把它跑起来**。
它不是导演层/角色层，不是文案渲染器，也不是设备名册。虚拟设备与未来真实设备
实现同一份契约，可在 MCP 视角下整体替换。

> 18+ only。仅面向成年人的自愿互动。当前仓库只包含虚拟设备，不连接任何真实硬件。

---

## 1. 核心决定

1. **设备是黑盒。** MCP 面只看到语义动作、模式、体验级档位、状态、停止与语义反馈；
   电机、波形、寄存器不属于契约。
2. **语义动作优先。** 「奖励主人尝一下自己最里面」「先用指腹检查一下再决定下一步」
   这类意图优先走语义接口；强度/档位保留，但它是体验级参数。
3. **共享核心本体 + 厂商扩展。** 核心动作：`stimulate / tease / hold / release /
   check / rest / stop`；厂商可加自己的 action_id，但仍须声明 realization。
4. **每个动作声明 `realization`**：
   - `native`：设备原生执行；
   - `mode_mapping`：映射到设备已有的模式；
   - `unsupported`：明确不支持。
5. **不支持就是拒绝。** 返回 `supported=false / executed=false`，不用旁白冒充物理执行。
6. **安全由硬件自治。** 设备消费自己的原始数据，随时准备自动调节/停止；有物理 stop
   按钮；Agent 可通过 `device_stop` 直接停止。只有设备主动请求时，才向上游要推理帮助。
7. **反馈不是数。** Agent 侧只有语义反馈 + 可选影像（图片/视频）；原始传感器数值
   留给硬件自己消费。
8. **`simulated=true` 对 Agent 可见。** 虚拟设备接口与真实设备等价，但不假装有硬件。

## 2. 安装与运行

需要 Python 3.11+。

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install pytest
```

stdio MCP 入口：

```bash
PYTHONPATH=src .venv/bin/python -m punishmaster.server
# 或安装后：
.venv/bin/punishmaster-server
```

stdout 只留给 MCP 传输；不要在这里打印日志。

## 3. MCP 设备面

| 工具 | 作用 |
|---|---|
| `device_capabilities` | 能力菜单：语义动作、模式、档位范围、realization、安全声明 |
| `device_status` | 当前状态：运行中、动作/模式、档位、剩余时长、语义反馈 |
| `device_do` | 执行语义动作（首选入口），支持 `level`、`duration_s`、`params`、`intent` |
| `device_set_mode` | 直接使用设备原生模式（回退入口） |
| `device_set_level` | 调整档位/强度，运行中可用 |
| `device_stop` | 立即停止；永远可用、幂等；与物理停止共用同一路径 |
| `device_media` | 读取可选影像反馈；没有就返回空列表 |
| `device_events` | 轮询设备事件：`safety` / `reasoning_request` / `state` / `media` |

资源：`device://capabilities`、`device://state`。

## 4. 目录

```
src/punishmaster/
├── contract.py      设备契约：能力、请求、状态、结果、事件
├── ontology.py      共享核心语义本体（7 个核心动作）
├── device.py        设备侧 Protocol（真实设备与虚拟设备共同实现）
├── virtual.py       虚拟设备：语义执行、模式、档位、本地安全、停止
└── server.py        MCP 设备面（只做设备操作，无导演层）
```

## 5. 测试

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
```

覆盖：realization 三种取值、unsupported 显式拒绝、模式映射、厂商扩展、停止幂等、
物理/Agen 停止共用路径、档位校验、本地安全自动停止、请求上游推理事件、
状态不含原始数值、MCP 工具可发现与端到端回环。

## 6. 下一步

- 真实设备适配器：实现 `punishmaster.device.Device`，替换 `VirtualDevice`；
- 影像反馈：`MediaItem` 已有结构，虚拟设备目前返回空；
- 语义意图 → 动作的路由：当前 `intent` 只记录不自动映射，避免误判；
- 一致性测试：把本仓库的契约测试扩展成第三方设备适配器的验收套件。

## 7. 许可

MIT。
