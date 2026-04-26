# Astrbot_Plugin_HAOS_scwunai

> 智能家居助手：传感器监控、设备控制、自然语言交互

Astrbot 的 HomeAssistant 智能家居集成插件，通过 `/ha` 指令使用自然语言控制智能家居设备。

## 功能特性

- 🌡️ **传感器监控**：实时监控 HomeAssistant 温湿度传感器状态
- 💡 **设备控制**：支持开关设备控制
- 🔔 **温度告警**：温度超出阈值时自动推送告警消息
- ⏰ **延迟执行**：支持定时任务，如"五分钟后开空调"
- 🤖 **自然语言**：通过 `/ha` 指令使用自然语言交互
- 🧠 **智能识别**：LLM 多意图识别，支持连续指令
- ✨ **润色回复**：LLM 生成自然友好的回复

## 安装

1. 将插件目录放置于 Astrbot 的 `plugins/` 目录下
2. 重启 Astrbot 或通过管理面板加载插件
3. 在插件配置页面填写 HomeAssistant 连接信息

## 配置说明

### 必填配置

| 配置项 | 说明 |
|-------|------|
| `home_assistant_url` | Home Assistant 地址，如 `http://homeassistant.local:8123` |
| `token` | Home Assistant 长效访问令牌 |
| `temperature_sensor_id` | 温度传感器 Entity ID |
| `humidity_sensor_id` | 湿度传感器 Entity ID |

### 监控配置

| 配置项 | 默认值 | 说明 |
|-------|-------|------|
| `low_threshold` | `10` | 温度下限阈值（°C） |
| `high_threshold` | `30` | 温度上限阈值（°C） |
| `check_interval` | `10` | 监控检查间隔（秒） |

### 设备配置

在 `switches` 列表中添加设备：

```json
{
  "name": "客厅灯",
  "entity_id": "switch.living_room_light"
}
```

窗帘、百叶、卷帘使用 Home Assistant 的 `cover` 实体：

```json
{
  "name": "客厅窗帘",
  "entity_id": "cover.living_room_curtain"
}
```

## 指令列表

### 基础指令

| 指令 | 说明 |
|-----|------|
| `/get_temperature` | 获取温度数据 |
| `/get_humidity` | 获取湿度数据 |
| `/curtain <指令>` | 控制窗帘打开、关闭、停止或设置开度 |
| `/monitor_temp` | 启动温度监控 |
| `/stop_monitor` | 停止温度监控 |
| `/haoshelp` | 显示帮助信息 |

### 智能助手指令

| 指令 | 说明 |
|-----|------|
| `/ha <自然语言>` | 智能家居助手入口 |

## 使用示例

### 智能助手 `/ha`

```
/ha 现在温度多少
/ha 温度和湿度都告诉我
/ha 打开客厅灯
/ha 关闭空调
/ha 打开客厅窗帘
/ha 客厅窗帘开到50%
/ha 停止客厅窗帘
/ha 启动温度监控
/ha 停止监控
/ha 今天天气怎么样
/ha 五分钟后帮我开空调
/ha 10分钟后关灯
```

### 延迟执行

支持设置延迟任务，在指定时间后自动执行操作：

```
/ha 五分钟后帮我开空调
/ha 10分钟后关灯
/ha 半小时后打开风扇
```

### 多意图识别

支持在一条消息中包含多个指令：

```
/ha 温度和湿度都告诉我
/ha 打开客厅灯和卧室灯
```

## 工作原理

1. **意图识别**：优先使用关键词匹配，无法识别时调用 LLM
2. **并行执行**：多个查询意图并行执行，提高响应速度
3. **LLM 润色**：使用 LLM 生成自然友好的回复

## 获取 HomeAssistant Token

1. 登录 HomeAssistant 后台
2. 点击左下角用户名
3. 进入「安全」页面
4. 在「长期访问令牌」处创建新令牌

## 获取传感器 Entity ID

1. 进入 HomeAssistant 后台
2. 设置 → 设备与服务 → 实体
3. 找到目标传感器，复制实体标识符（如 `sensor.temperature`）

## 更新日志

### v2.2.4 (2026-03-31)

- ✨ 新增延迟执行功能，支持"五分钟后开空调"等定时任务
- 🐛 修复延迟执行意图被误识别为订阅天气的问题

### v2.2.3 (2026-03-23)

- 🔄 重构为 `/ha` 单指令入口，不再劫持所有 LLM 请求
- ✨ 支持多意图识别与并行执行
- ✨ 支持 LLM 润色回复
- 🗑️ 移除 `on_llm_request` 和 `on_llm_response` 钩子
- ⚡ 优化代码结构，使用异步 HTTP 请求

### v2.2.2 (2026-03-22)

- ✨ 设备控制支持智能模糊匹配
- ✨ 新增 LLM 语义理解增强功能

### v2.2.1 (2026-03-21)

- ✨ 新增分时天气查询
- ✨ 每日天气推送新增生活指数

### v2.2.0 (2026-03-20)

- ✨ 新增 AstrBot 人格集成功能

### v2.1.0 (2026-03-20)

- ✨ 新增连续指令响应
- ✨ 新增设备控制功能

### v2.0.0 (2026-03-18)

- 🎉 重构为智能家居助手

### v1.0.2 (2025-02-25)

- 新增自然语言控制功能

### v1.0.1 (2025-02-12)

- 新增 /monitor_temp、/stop_monitor 指令

## 支持

- [Astrbot 文档](https://astrbot.soulter.top/)
- [问题反馈](https://github.com/scwunai/Astrbot_Plugin_HAOS_scwunai/issues)

## License

MIT
