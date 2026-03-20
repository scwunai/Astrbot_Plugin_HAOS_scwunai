# Astrbot_Plugin_HAOS_scwunai

> 智能家居助手：天气查询、传感器监控、智能告警

Astrbot 的 HomeAssistant 智能家居集成插件，支持天气查询、传感器监控、自然语言交互。

## 功能特性

- 🌤️ **天气查询**：支持全国城市天气查询，包含当前天气、预报、生活指数
- 📊 **传感器监控**：实时监控 HomeAssistant 传感器状态，支持阈值告警
- 🔔 **智能告警**：传感器数据异常时自动推送告警消息
- 🤖 **自然语言**：支持通过自然语言与机器人交互
- ⏰ **定时推送**：每日定时推送天气信息

## 安装

1. 将插件目录放置于 Astrbot 的 `plugins/` 目录下
2. 重启 Astrbot 或通过管理面板加载插件
3. 在插件配置页面填写 HomeAssistant 连接信息

## 配置说明

### 必填配置

| 配置项 | 说明 |
|-------|------|
| `home_assistant_url` | Home Assistant 地址，如 `http://homeassistant.local:8123` |
| `ha_token` | Home Assistant 长效访问令牌 |

### 传感器配置

在 `sensors` 列表中添加传感器：

```json
{
  "name": "客厅温度",
  "entity_id": "sensor.living_room_temperature",
  "sensor_type": "temperature",
  "unit": "°C",
  "low_threshold": 10,
  "high_threshold": 30,
  "enabled": true
}
```

### 可选配置

| 配置项 | 默认值 | 说明 |
|-------|-------|------|
| `weather_push_time` | `07:00` | 每日天气推送时间 |
| `sensor_check_interval` | `300` | 传感器检查间隔（秒） |
| `enable_sensor_alert` | `true` | 是否启用传感器异常告警 |
| `enable_weather_push` | `true` | 是否启用每日天气推送 |

## 指令列表

| 指令 | 说明 |
|-----|------|
| `/set_location <城市>` | 设置用户位置 |
| `/weather` | 获取当前天气 |
| `/subscribe_weather` | 订阅每日天气推送 |
| `/unsubscribe_weather` | 取消天气订阅 |
| `/sensor` | 查询传感器状态 |
| `/list_sensors` | 列出已配置的传感器 |
| `/haoshelp` | 显示帮助信息 |

## 自然语言交互

支持通过自然语言触发功能：

- 「今天天气怎么样」→ 查询天气
- 「我在北京」→ 设置位置
- 「室内温度多少」→ 查询温度传感器
- 「湿度多少」→ 查询湿度传感器
- 「订阅天气」→ 订阅天气推送
- 「取消天气订阅」→ 取消订阅

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

### v2.0.0 (2026-03-18)

- 🎉 重构为智能家居助手
- ✨ 新增天气查询功能
- ✨ 新增用户位置管理
- ✨ 新增每日天气推送
- ✨ 新增传感器阈值告警
- ♻️ HTTP 调用改为异步（aiohttp）
- 🗑️ 移除旧的定时监控指令

### v1.0.2 (2025-02-25)

- 新增自然语言控制功能

### v1.0.1 (2025-02-12)

- 新增 /monitor_temp、/stop_monitor 指令

## 支持

- [Astrbot 文档](https://astrbot.soulter.top/)
- [问题反馈](https://github.com/scwunai/Astrbot_Plugin_HAOS_scwunai/issues)

## License

MIT
