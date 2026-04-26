"""
智能家居助手插件

通过 /ha 指令使用自然语言控制智能家居设备
"""

import logging
from typing import Optional
import asyncio

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .modules.weather import WeatherAPI
from .modules.homeassistant import HomeAssistantClient
from .modules.location import LocationManager
from .modules.llm_handler import LLMHandler

logger = logging.getLogger(__name__)


@register(
    "Astrbot_Plugin_HAOS_scwunai",
    "scwunai",
    "智能家居助手：通过自然语言控制 HomeAssistant 设备",
    "2.2.4",
    "https://github.com/scwunai/Astrbot_Plugin_HAOS_scwunai",
)
class SmartHomePlugin(Star):
    """智能家居助手插件"""

    # 意图关键词映射
    INTENT_KEYWORDS = {
        "temperature_query": ["温度", "多少度", "气温", "室内温度", "现在温度", "卧室温度", "客厅温度"],
        "humidity_query": ["湿度", "多少湿度", "室内湿度", "现在湿度"],
        "sensor_query": ["传感器", "传感器状态"],
        "monitor_start": ["监控温度", "监测温度", "盯着温度", "温度监控", "启动监控"],
        "monitor_stop": ["停止监控", "关闭监控", "别监控", "取消监控"],
        "curtain_query": ["窗帘状态", "窗帘情况", "百叶状态", "卷帘状态"],
        "curtain_position": ["窗帘位置", "窗帘开度", "窗帘到", "窗帘开到", "百叶位置", "卷帘位置"],
        "curtain_control": ["打开窗帘", "开启窗帘", "开窗帘", "拉开窗帘", "关闭窗帘", "关窗帘", "关上窗帘", "拉上窗帘", "停止窗帘", "暂停窗帘"],
        "device_on": ["打开", "开启", "启动", "开灯", "开空调"],
        "device_off": ["关闭", "关掉", "停止", "关灯", "关空调"],
        "device_query": ["设备状态", "设备情况"],
        "weather_query": ["天气", "天气预报", "今天天气", "明天天气", "后天天气"],
        "hourly_weather": ["小时后天气", "一小时后", "两小时后", "几小时后"],
        "set_location": ["我在", "我的位置", "设置位置"],
        "delayed_action": ["分钟后", "分钟后帮我", "秒后", "小时后帮我", "待会儿帮我", "一会儿帮我"],
        "help": ["帮助", "怎么用", "功能"],
    }

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

        # HomeAssistant 配置
        self.ha_url = config.get("home_assistant_url", "") or config.get("ha_url", "")
        self.ha_token = config.get("ha_token", "") or config.get("token", "")

        # 初始化 HomeAssistant 客户端
        self.ha_client = None
        if self.ha_url and self.ha_token:
            self.ha_client = HomeAssistantClient(self.ha_url, self.ha_token)

        # 天气 API
        self.weather_api = WeatherAPI()

        # 位置管理器
        from pathlib import Path
        data_dir = Path(__file__).parent / "data"
        self.location_mgr = LocationManager(data_dir)

        # LLM 处理器
        self.llm_handler = LLMHandler(self)

        # 传感器配置
        self.sensors = config.get("sensors", [])

        # 设备配置
        self.switches = config.get("switches", [])

        # 监控配置
        self.low_threshold = config.get("low_threshold", 10)
        self.high_threshold = config.get("high_threshold", 30)
        self.check_interval = config.get("check_interval", 10)

        # 权限配置
        self.admin_users = config.get("admin_users", [])
        self.admin_groups = config.get("admin_groups", [])
        self.public_commands = config.get("public_commands", ["weather", "set_location", "subscribe_weather", "unsubscribe_weather", "haoshelp"])

        # 人格集成配置
        self.enable_persona = config.get("enable_persona", False)
        self.persona_name = config.get("persona_name", "")

        # LLM 语义理解增强配置
        self.enable_llm_semantic = config.get("enable_llm_semantic", False)
        self.llm_semantic_provider = config.get("llm_semantic_provider", "")
        self.llm_response_provider = config.get("llm_response_provider", "")

        # 调度器
        self.scheduler = AsyncIOScheduler()
        self._monitor_jobs = {}

        # 初始化人格管理器
        self._init_persona_manager()

    def _init_persona_manager(self):
        """初始化人格管理器"""
        try:
            # 尝试从 context 获取 persona_manager
            if hasattr(self.context, 'persona_manager'):
                self.llm_handler.set_persona_manager(self.context.persona_manager)
                logger.info("人格管理器初始化成功")
        except Exception as e:
            logger.warning(f"人格管理器初始化失败: {e}")

    # 需要权限控制的意图列表
    PROTECTED_INTENTS = {
        "device_on", "device_off", "device_query",
        "curtain_control", "curtain_position", "curtain_query",
        "ac_control", "ac_temp",
        "sensor_query", "temperature_query", "humidity_query",
        "monitor_start", "monitor_stop",
        "delayed_action"
    }

    # 意图到指令的映射（用于权限检查）
    INTENT_TO_COMMAND = {
        "weather_query": "weather",
        "hourly_weather": "weather",
        "set_location": "set_location",
        "subscribe_weather": "subscribe_weather",
        "unsubscribe_weather": "unsubscribe_weather",
        "help": "haoshelp",
        "temperature_query": "get_temperature",
        "humidity_query": "get_humidity",
        "sensor_query": "sensor",
        "device_query": "device",
        "device_on": "device_control",
        "device_off": "device_control",
        "curtain_control": "curtain",
        "curtain_position": "curtain",
        "curtain_query": "curtain",
        "ac_control": "device_control",
        "ac_temp": "device_control",
        "monitor_start": "monitor_temp",
        "monitor_stop": "stop_monitor",
    }

    def _check_permission(self, event: AstrMessageEvent, intent: str) -> bool:
        """
        检查用户是否有权限执行某意图

        Args:
            event: 消息事件
            intent: 意图名称

        Returns:
            是否有权限
        """
        # 如果没有配置管理员，所有人都有权限
        if not self.admin_users and not self.admin_groups:
            return True

        # 将意图映射到指令名
        command = self.INTENT_TO_COMMAND.get(intent, intent)

        # 公开指令无需权限
        if command in self.public_commands:
            return True

        # 获取用户的 unified_msg_origin（可通过 /sid 指令获取）
        # 格式: platform:message_type:session_id
        # 例如: aiocqhttp:GroupMessage:547540978 或 aiocqhttp:FriendMessage:12345678
        umo = event.unified_msg_origin

        # 检查是否是管理员用户（直接匹配 unified_msg_origin）
        if umo in self.admin_users:
            return True

        # 解析 umo 获取平台和会话信息
        parts = umo.split(":") if umo else []
        platform = parts[0] if len(parts) > 0 else ""
        message_type = parts[1] if len(parts) > 1 else ""
        session_id = parts[2] if len(parts) > 2 else ""

        # 检查管理员用户（支持平台前缀格式）
        for admin in self.admin_users:
            # 支持格式: platform:session_id（如 aiocqhttp:12345678）
            if ":" in admin:
                admin_parts = admin.split(":")
                if len(admin_parts) == 2:
                    admin_platform, admin_sid = admin_parts
                    # 私聊场景：匹配平台和用户ID
                    if message_type == "FriendMessage" and admin_platform == platform and admin_sid == session_id:
                        return True
                    # 群聊场景：匹配平台和群ID
                    if message_type == "GroupMessage" and admin_platform == platform and admin_sid == session_id:
                        return True

        # 检查是否在管理员群组
        if message_type == "GroupMessage" and session_id:
            for admin_group in self.admin_groups:
                # 直接匹配群ID
                if admin_group == session_id:
                    return True
                # 支持 platform:group_id 格式
                if ":" in admin_group:
                    admin_platform, admin_gid = admin_group.split(":", 1)
                    if admin_platform == platform and admin_gid == session_id:
                        return True

        return False

    def _get_permission_denied_message(self) -> str:
        """获取权限拒绝消息"""
        return "⚠️ 您没有权限执行此操作，请联系管理员"

    def _get_sensor_by_type(self, sensor_type: str) -> Optional[dict]:
        """根据类型获取传感器配置"""
        for sensor in self.sensors:
            if isinstance(sensor, dict):
                # 检查 __template_key 或 sensor_type
                template_key = sensor.get("__template_key", "")
                if template_key == sensor_type:
                    return sensor
        return None

    def _get_sensor_by_name(self, name: str) -> Optional[dict]:
        """根据名称模糊匹配传感器"""
        name_lower = name.lower()
        for sensor in self.sensors:
            if isinstance(sensor, dict):
                sensor_name = sensor.get("name", "").lower()
                entity_id = sensor.get("entity_id", "").lower()
                if name_lower in sensor_name or name_lower in entity_id:
                    return sensor
        return None

    def _get_device_by_name(self, name: str) -> Optional[dict]:
        """根据名称模糊匹配设备"""
        name_lower = name.lower()
        for device in self.switches:
            if isinstance(device, dict):
                device_name = device.get("name", "").lower()
                entity_id = device.get("entity_id", "").lower()
                if name_lower in device_name or name_lower in entity_id:
                    return device
        return None

    # ==================== 基础指令 ====================

    @filter.command("get_temperature")
    async def get_temperature(self, event: AstrMessageEvent):
        """获取温度数据"""
        temp_sensor = self._get_sensor_by_type("temperature")
        if not temp_sensor:
            yield event.plain_result("未配置温度传感器")
            return

        entity_id = temp_sensor.get("entity_id", "")
        if self.ha_client:
            value = await self.ha_client.get_sensor_value(entity_id)
            if value is not None:
                unit = temp_sensor.get("unit", "°C")
                name = temp_sensor.get("name", "温度")
                yield event.plain_result(f"🌡️ {name}: {value}{unit}")
            else:
                yield event.plain_result("获取温度失败，请检查配置")
        else:
            yield event.plain_result("HomeAssistant 未配置")

    @filter.command("get_humidity")
    async def get_humidity(self, event: AstrMessageEvent):
        """获取湿度数据"""
        humidity_sensor = self._get_sensor_by_type("humidity")
        if not humidity_sensor:
            yield event.plain_result("未配置湿度传感器")
            return

        entity_id = humidity_sensor.get("entity_id", "")
        if self.ha_client:
            value = await self.ha_client.get_sensor_value(entity_id)
            if value is not None:
                unit = humidity_sensor.get("unit", "%")
                name = humidity_sensor.get("name", "湿度")
                yield event.plain_result(f"💧 {name}: {value}{unit}")
            else:
                yield event.plain_result("获取湿度失败，请检查配置")
        else:
            yield event.plain_result("HomeAssistant 未配置")

    @filter.command("sensor")
    async def query_sensors(self, event: AstrMessageEvent):
        """查询所有传感器状态"""
        if not self.ha_client:
            yield event.plain_result("HomeAssistant 未配置")
            return

        if not self.sensors:
            yield event.plain_result("未配置任何传感器")
            return

        results = []
        for sensor in self.sensors:
            if isinstance(sensor, dict) and sensor.get("enabled", True):
                entity_id = sensor.get("entity_id", "")
                name = sensor.get("name", entity_id)
                state = await self.ha_client.get_sensor_state(entity_id)
                if state:
                    value = state.get("state", "N/A")
                    unit = state.get("attributes", {}).get("unit_of_measurement", "")
                    results.append(f"📊 {name}: {value}{unit}")
                else:
                    results.append(f"📊 {name}: 获取失败")

        yield event.plain_result("\n".join(results) if results else "无传感器数据")

    @filter.command("monitor_temp")
    async def monitor_temperature(self, event: AstrMessageEvent):
        """启动温度监控"""
        umo = event.unified_msg_origin
        temp_sensor = self._get_sensor_by_type("temperature")

        if not temp_sensor:
            yield event.plain_result("未配置温度传感器")
            return

        entity_id = temp_sensor.get("entity_id", "")
        low = temp_sensor.get("low_threshold", self.low_threshold)
        high = temp_sensor.get("high_threshold", self.high_threshold)

        async def check_and_alert():
            if not self.ha_client:
                return
            value = await self.ha_client.get_sensor_value(entity_id)
            if value is not None:
                if value < low:
                    msg = f"⚠️ 温度过低: {value}°C (低于 {low}°C)"
                elif value > high:
                    msg = f"⚠️ 温度过高: {value}°C (高于 {high}°C)"
                else:
                    return
            else:
                msg = "获取温度失败"

            await self.context.send_message(umo, MessageChain().message(msg))

        job_id = f"temp_monitor_{umo}"
        if job_id in self._monitor_jobs:
            yield event.plain_result("温度监控已在运行中")
            return

        job = self.scheduler.add_job(
            check_and_alert,
            'interval',
            seconds=self.check_interval,
            id=job_id
        )
        self._monitor_jobs[job_id] = job

        if not self.scheduler.running:
            self.scheduler.start()

        yield event.plain_result(f"✅ 温度监控已启动 (每 {self.check_interval} 秒检查)")

    @filter.command("stop_monitor")
    async def stop_monitor(self, event: AstrMessageEvent):
        """停止温度监控"""
        umo = event.unified_msg_origin
        job_id = f"temp_monitor_{umo}"

        if job_id in self._monitor_jobs:
            self._monitor_jobs[job_id].remove()
            del self._monitor_jobs[job_id]
            yield event.plain_result("✅ 温度监控已停止")
        else:
            yield event.plain_result("当前没有运行中的温度监控")

    @filter.command("device")
    async def query_devices(self, event: AstrMessageEvent):
        """查询设备状态"""
        if not self.ha_client:
            yield event.plain_result("HomeAssistant 未配置")
            return

        if not self.switches:
            yield event.plain_result("未配置任何设备")
            return

        results = []
        for device in self.switches:
            if isinstance(device, dict):
                entity_id = device.get("entity_id", "")
                name = device.get("name", entity_id)
                state = await self.ha_client.get_entity_state(entity_id)
                if state:
                    dev_state = state.get("state", "unknown")
                    state_map = {
                        "on": "开启",
                        "off": "关闭",
                        "open": "打开",
                        "opening": "正在打开",
                        "closed": "关闭",
                        "closing": "正在关闭",
                        "cool": "制冷",
                        "heat": "制热",
                    }
                    state_text = state_map.get(dev_state, dev_state)
                    results.append(f"💡 {name}: {state_text}")
                else:
                    results.append(f"💡 {name}: 获取失败")

        yield event.plain_result("\n".join(results) if results else "无设备数据")

    @filter.command("curtain")
    async def control_curtain(self, event: AstrMessageEvent):
        """Control curtain devices."""
        if not self.ha_client:
            yield event.plain_result("HomeAssistant 未配置")
            return

        if not self._check_permission(event, "curtain_control"):
            yield event.plain_result(self._get_permission_denied_message())
            return

        message = event.get_message_str().strip()
        parts = message.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("请输入窗帘指令，例如：/curtain 打开客厅窗帘 或 /curtain 客厅窗帘 50%")
            return

        intents = self._parse_curtain_intents(parts[1].strip())
        if not intents:
            yield event.plain_result("未识别窗帘指令，支持打开、关闭、停止、设置百分比和查询状态")
            return

        intent_item = intents[0]
        intent = intent_item.get("intent")
        device_name = intent_item.get("device", "窗帘")

        if intent == "curtain_position":
            position = intent_item.get("position")
            success = await self._set_curtain_position(device_name, position)
            if success:
                yield event.plain_result(f"已将 {device_name} 设置到 {position}%")
            else:
                yield event.plain_result(f"设置 {device_name} 位置失败")
            return

        if intent == "curtain_query":
            data = await self._get_curtains_data(device_name)
            yield event.plain_result(data or f"获取 {device_name} 状态失败")
            return

        action = intent_item.get("action", "")
        success = await self._control_curtain(device_name, action)
        action_text = self._format_curtain_action(action)
        if success:
            yield event.plain_result(f"已{action_text} {device_name}")
        else:
            yield event.plain_result(f"{action_text} {device_name} 失败")

    @filter.command("haoshelp")
    async def help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """🏠 智能家居助手

📋 基础指令:
/get_temperature - 获取温度
/get_humidity - 获取湿度
/sensor - 查询所有传感器
/device - 查询设备状态
/curtain <指令> - 控制窗帘
/monitor_temp - 启动温度监控
/stop_monitor - 停止监控

🤖 智能助手:
/ha <自然语言> - 智能控制

示例:
/ha 现在温度多少
/ha 卧室温度多少
/ha 打开客厅灯
/ha 打开客厅窗帘
/ha 客厅窗帘开到 50%
/ha 今天天气怎么样
/ha 我在北京"""
        yield event.plain_result(help_text)

    # ==================== 智能助手入口 ====================

    @filter.command("ha")
    async def smart_assistant(self, event: AstrMessageEvent):
        """智能家居助手入口"""
        message = event.get_message_str().strip()
        parts = message.split(maxsplit=1)

        if len(parts) < 2:
            yield event.plain_result("请输入指令，例如：/ha 现在温度多少")
            return

        user_query = parts[1].strip()
        user_id = event.get_sender_id()

        # 解析意图
        intents = []

        # 如果启用了 LLM 语义理解增强，直接使用 LLM 解析
        if self.enable_llm_semantic:
            intents = await self._llm_parse_intents(event, user_query)
        else:
            # 先尝试关键词匹配
            intents = self._parse_intents(user_query)
            # 如果关键词匹配失败，再使用 LLM
            if not intents:
                intents = await self._llm_parse_intents(event, user_query)

        if not intents:
            yield event.plain_result("抱歉，我没有理解您的指令")
            return

        # 执行意图
        results = await self._execute_intents(event, intents, user_query, user_id)

        # LLM 润色回复
        response = await self._polish_response(event, user_query, results)
        yield event.plain_result(response)

    def _parse_intents(self, text: str) -> list[dict]:
        """基于关键词解析意图"""
        import re
        intents = []
        curtain_intents = self._parse_curtain_intents(text)
        intents.extend(curtain_intents)

        for intent, keywords in self.INTENT_KEYWORDS.items():
            if intent.startswith("curtain_"):
                continue
            if curtain_intents and intent in ("device_on", "device_off"):
                continue
            for keyword in keywords:
                if keyword in text:
                    intent_item = {"intent": intent}

                    # 提取位置信息
                    if intent == "set_location":
                        patterns = [
                            r"我在(.+?)(?:，|。|$)",
                            r"我的位置[是为：:\s]*(.+?)(?:，|。|$)",
                        ]
                        for pattern in patterns:
                            match = re.search(pattern, text)
                            if match:
                                intent_item["location"] = match.group(1).strip()
                                break

                    # 提取小时数
                    elif intent == "hourly_weather":
                        match = re.search(r"(\d+)\s*小时", text)
                        if match:
                            intent_item["hours"] = int(match.group(1))

                    # 提取延迟执行参数
                    elif intent == "delayed_action":
                        # 匹配 "X分钟后..." 或 "X秒后..."
                        minute_match = re.search(r"(\d+)\s*分钟后", text)
                        second_match = re.search(r"(\d+)\s*秒后", text)
                        hour_match = re.search(r"(\d+)\s*小时后", text)

                        delay_minutes = 0
                        if hour_match:
                            delay_minutes = int(hour_match.group(1)) * 60
                        elif minute_match:
                            delay_minutes = int(minute_match.group(1))
                        elif second_match:
                            delay_minutes = int(second_match.group(1)) / 60

                        if delay_minutes > 0:
                            intent_item["delay_minutes"] = delay_minutes

                            # 提取操作内容
                            # 尝试匹配 "帮我..." 或直接操作
                            action_patterns = [
                                r"分钟后帮我(.+?)(?:，|。|$)",
                                r"分钟后(.+?)(?:，|。|$)",
                                r"秒后帮我(.+?)(?:，|。|$)",
                                r"秒后(.+?)(?:，|。|$)",
                                r"小时后帮我(.+?)(?:，|。|$)",
                                r"小时后(.+?)(?:，|。|$)",
                            ]
                            for pattern in action_patterns:
                                match = re.search(pattern, text)
                                if match:
                                    intent_item["action"] = match.group(1).strip()
                                    break

                    # 提取设备名
                    elif intent in ("device_on", "device_off"):
                        for keyword in ["打开", "开启", "启动", "关闭", "关掉", "停止"]:
                            if keyword in text:
                                idx = text.find(keyword) + len(keyword)
                                device_name = text[idx:].strip()
                                # 清理后续内容
                                for stop in ["，", "。", "和", "以及"]:
                                    if stop in device_name:
                                        device_name = device_name[:device_name.find(stop)]
                                if device_name:
                                    intent_item["device"] = device_name
                                break

                    # 提取传感器名
                    elif intent in ("temperature_query", "humidity_query"):
                        for kw in ["卧室", "客厅", "厨房", "书房", "阳台"]:
                            if kw in text:
                                intent_item["sensor_name"] = kw
                                break

                    intents.append(intent_item)
                    break

        return intents

    def _parse_curtain_intents(self, text: str) -> list[dict]:
        """Parse curtain commands from natural language."""
        import re

        if not any(word in text for word in ("窗帘", "百叶", "卷帘")):
            return []

        intent_item = {}
        position = self._extract_curtain_position(text)
        if position is not None:
            intent_item = {"intent": "curtain_position", "position": position}
        elif any(word in text for word in ("状态", "情况")):
            intent_item = {"intent": "curtain_query"}
        elif any(word in text for word in ("停止", "暂停", "停下")):
            intent_item = {"intent": "curtain_control", "action": "stop"}
        elif any(
            re.search(pattern, text)
            for pattern in (
                r"(?:关闭|关上|拉上|合上).*(?:窗帘|百叶|卷帘)",
                r"关.*(?:窗帘|百叶|卷帘)",
                r"(?:窗帘|百叶|卷帘).*(?:关闭|关上|拉上|合上)",
            )
        ):
            intent_item = {"intent": "curtain_control", "action": "close"}
        elif any(
            re.search(pattern, text)
            for pattern in (
                r"(?:打开|开启|拉开).*(?:窗帘|百叶|卷帘)",
                r"开.*(?:窗帘|百叶|卷帘)",
                r"(?:窗帘|百叶|卷帘).*(?:打开|开启|拉开)",
            )
        ):
            intent_item = {"intent": "curtain_control", "action": "open"}

        if not intent_item:
            return []

        intent_item["device"] = self._extract_curtain_name(text)
        return [intent_item]

    def _extract_curtain_position(self, text: str) -> Optional[int]:
        """Extract a 0-100 cover position from text."""
        import re

        percent_match = re.search(r"(\d{1,3})\s*%", text)
        if percent_match:
            return self._normalize_curtain_position(percent_match.group(1))

        position_patterns = [
            r"(?:到|开到|调到|设置到|设为)\s*(\d{1,3})",
            r"(\d{1,3})\s*(?:位置|开度)",
            r"百分之\s*(\d{1,3})",
        ]
        for pattern in position_patterns:
            match = re.search(pattern, text)
            if match:
                return self._normalize_curtain_position(match.group(1))

        return None

    def _normalize_curtain_position(self, value: str) -> Optional[int]:
        """Normalize a Home Assistant cover position."""
        try:
            position = int(value)
        except (TypeError, ValueError):
            return None
        if 0 <= position <= 100:
            return position
        return None

    def _extract_curtain_name(self, text: str) -> str:
        """Extract curtain device name from a command."""
        import re

        name = text
        for stop in ("，", "。", "；", ";", "和", "以及"):
            if stop in name:
                name = name[:name.find(stop)]

        name = re.sub(r"\d{1,3}\s*%?", "", name)
        cleanup_words = (
            "请", "帮我", "把", "将", "给我", "一下",
            "打开", "开启", "拉开", "开", "关闭", "关上", "拉上", "合上", "关",
            "停止", "暂停", "停下", "设置到", "设置", "设为", "调到",
            "开到", "到", "位置", "开度", "状态", "情况", "百分之",
        )
        for word in cleanup_words:
            name = name.replace(word, "")

        name = name.strip()
        return name or "窗帘"

    async def _llm_parse_intents(self, event: AstrMessageEvent, user_query: str) -> list[dict]:
        """使用 LLM 解析意图"""
        try:
            umo = event.unified_msg_origin

            # 优先使用配置的专用语义 Provider
            provider_id = self.llm_semantic_provider
            if not provider_id:
                provider_id = await self.context.get_current_chat_provider_id(umo=umo)

            if not provider_id:
                return []

            # 获取可用设备列表
            device_names = [d.get("name", "") for d in self.switches if isinstance(d, dict)]
            device_hint = f"可用设备: {', '.join(device_names)}" if device_names else ""

            # 使用 LLMHandler 的系统提示词
            system_prompt = self.llm_handler.get_system_prompt()

            # 添加设备信息
            if device_hint:
                system_prompt += f"\n\n{device_hint}"

            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=f"{system_prompt}\n\n用户: {user_query}",
            )

            if llm_resp and llm_resp.completion_text:
                return self._parse_llm_intents(llm_resp.completion_text)

        except Exception as e:
            logger.error(f"LLM 意图识别失败: {e}")

        return []

    def _parse_llm_intents(self, text: str) -> list[dict]:
        """解析 LLM 输出的意图标记"""
        import re

        intents = []
        patterns = {
            "temperature_query": r"\[温度查询\]",
            "humidity_query": r"\[湿度查询\]",
            "sensor_query": r"\[传感器查询\]",
            "monitor_start": r"\[启动监控\]",
            "monitor_stop": r"\[停止监控\]",
            "device_on": r"\[打开设备[:：](.+?)\]",
            "device_off": r"\[关闭设备[:：](.+?)\]",
            "device_query": r"\[设备状态查询\]",
            "curtain_control": r"\[窗帘控制[:：](.+?)[:：](打开|关闭|停止|暂停|open|close|stop)\]",
            "curtain_position": r"\[窗帘位置[:：](.+?)[:：](\d{1,3})\]",
            "curtain_query": r"\[窗帘状态查询(?:[:：](.+?))?\]",
            "ac_control": r"\[空调控制[:：](.+?)\]",
            "ac_temp": r"\[空调温度[:：](.+?)\]",
            "weather_query": r"\[天气查询\]",
            "hourly_weather": r"\[小时天气[:：](\d+)\]",
            "set_location": r"\[设置位置[:：](.+?)\]",
            "subscribe_weather": r"\[订阅天气\]",
            "unsubscribe_weather": r"\[取消天气订阅\]",
            "delayed_action": r"\[延迟执行[:：](\d+)[:：](.+?)\]",
            "help": r"\[帮助\]",
        }

        # 按文本顺序收集所有匹配
        all_matches = []
        for intent, pattern in patterns.items():
            for match in re.finditer(pattern, text):
                intent_item = {"intent": intent, "pos": match.start()}
                groups = match.groups()
                if groups and groups[0]:
                    if intent == "hourly_weather":
                        intent_item["hours"] = int(groups[0])
                    elif intent in ("device_on", "device_off"):
                        intent_item["device"] = groups[0].strip()
                    elif intent == "curtain_control":
                        intent_item["device"] = groups[0].strip()
                        intent_item["action"] = self._normalize_curtain_action(groups[1].strip())
                    elif intent == "curtain_position":
                        intent_item["device"] = groups[0].strip()
                        intent_item["position"] = self._normalize_curtain_position(groups[1].strip())
                    elif intent == "curtain_query":
                        intent_item["device"] = groups[0].strip() if groups[0] else "窗帘"
                    elif intent == "ac_control":
                        intent_item["mode"] = groups[0].strip()
                    elif intent == "ac_temp":
                        intent_item["temperature"] = groups[0].strip()
                    elif intent == "set_location":
                        intent_item["location"] = groups[0].strip()
                    elif intent == "delayed_action":
                        # [延迟执行:分钟数:操作]
                        intent_item["delay_minutes"] = int(groups[0])
                        if len(groups) > 1 and groups[1]:
                            intent_item["action"] = groups[1].strip()
                all_matches.append(intent_item)

        # 按出现顺序排序
        all_matches.sort(key=lambda x: x["pos"])

        # 移除 pos 字段
        for item in all_matches:
            item.pop("pos", None)

        return all_matches

    # 需要权限控制的意图列表
    PROTECTED_INTENTS = {
        "device_on", "device_off", "device_query",
        "curtain_control", "curtain_position", "curtain_query",
        "ac_control", "ac_temp",
        "sensor_query", "temperature_query", "humidity_query",
        "monitor_start", "monitor_stop",
        "delayed_action"
    }

    async def _execute_intents(
        self,
        event: AstrMessageEvent,
        intents: list[dict],
        user_query: str,
        user_id: str
    ) -> dict:
        """执行意图"""
        results = {
            "data": {},
            "actions": [],
            "errors": []
        }

        for intent_item in intents:
            intent = intent_item["intent"]

            # 权限检查
            if intent in self.PROTECTED_INTENTS:
                if not self._check_permission(event, intent):
                    results["errors"].append(self._get_permission_denied_message())
                    continue

            try:
                if intent == "temperature_query":
                    sensor_name = intent_item.get("sensor_name", "")
                    data = await self._get_temperature_data(sensor_name)
                    if data:
                        results["data"]["temperature"] = data
                    else:
                        results["errors"].append("获取温度失败")

                elif intent == "humidity_query":
                    sensor_name = intent_item.get("sensor_name", "")
                    data = await self._get_humidity_data(sensor_name)
                    if data:
                        results["data"]["humidity"] = data
                    else:
                        results["errors"].append("获取湿度失败")

                elif intent == "sensor_query":
                    data = await self._get_all_sensors_data()
                    if data:
                        results["data"]["sensors"] = data
                    else:
                        results["errors"].append("获取传感器数据失败")

                elif intent == "monitor_start":
                    results["actions"].append("已启动温度监控")

                elif intent == "monitor_stop":
                    results["actions"].append("已停止温度监控")

                elif intent == "device_on":
                    device_name = intent_item.get("device", "")
                    success = await self._control_device(device_name, "on")
                    if success:
                        results["actions"].append(f"已打开 {device_name}")
                    else:
                        results["errors"].append(f"打开 {device_name} 失败")

                elif intent == "device_off":
                    device_name = intent_item.get("device", "")
                    success = await self._control_device(device_name, "off")
                    if success:
                        results["actions"].append(f"已关闭 {device_name}")
                    else:
                        results["errors"].append(f"关闭 {device_name} 失败")

                elif intent == "device_query":
                    data = await self._get_devices_data()
                    if data:
                        results["data"]["devices"] = data
                    else:
                        results["errors"].append("获取设备状态失败")

                elif intent == "curtain_control":
                    device_name = intent_item.get("device", "窗帘")
                    action = intent_item.get("action", "")
                    success = await self._control_curtain(device_name, action)
                    action_text = self._format_curtain_action(action)
                    if success:
                        results["actions"].append(f"已{action_text} {device_name}")
                    else:
                        results["errors"].append(f"{action_text} {device_name} 失败")

                elif intent == "curtain_position":
                    device_name = intent_item.get("device", "窗帘")
                    position = intent_item.get("position")
                    if position is None:
                        results["errors"].append(f"{device_name} 位置值无效")
                        continue
                    success = await self._set_curtain_position(device_name, position)
                    if success:
                        results["actions"].append(f"已将 {device_name} 设置到 {position}%")
                    else:
                        results["errors"].append(f"设置 {device_name} 位置失败")

                elif intent == "curtain_query":
                    device_name = intent_item.get("device", "")
                    data = await self._get_curtains_data(device_name)
                    if data:
                        results["data"]["curtains"] = data
                    else:
                        results["errors"].append("获取窗帘状态失败")

                elif intent == "ac_control":
                    device_name = intent_item.get("device", "空调")
                    mode = intent_item.get("mode", "")
                    success = await self._control_ac_mode(device_name, mode)
                    if success:
                        results["actions"].append(f"已将 {device_name} 设置为 {mode} 模式")
                    else:
                        results["errors"].append(f"设置 {device_name} 模式失败")

                elif intent == "ac_temp":
                    device_name = intent_item.get("device", "空调")
                    temp = intent_item.get("temperature", "")
                    try:
                        temp_value = int(temp)
                        success = await self._control_ac_temp(device_name, temp_value)
                        if success:
                            results["actions"].append(f"已将 {device_name} 温度设置为 {temp_value}°C")
                        else:
                            results["errors"].append(f"设置 {device_name} 温度失败")
                    except ValueError:
                        results["errors"].append(f"无效的温度值: {temp}")

                elif intent == "weather_query":
                    data = await self._get_weather_data(user_id)
                    if data:
                        results["data"]["weather"] = data
                    else:
                        results["errors"].append("获取天气失败，请先设置位置，如：/ha 我在北京")

                elif intent == "hourly_weather":
                    hours = intent_item.get("hours", 1)
                    data = await self._get_hourly_weather_data(user_id, hours)
                    if data:
                        results["data"]["hourly_weather"] = data
                    else:
                        results["errors"].append(f"获取 {hours} 小时后天气失败")

                elif intent == "set_location":
                    location = intent_item.get("location", "")
                    if location:
                        success = await self._set_user_location(user_id, location)
                        if success:
                            results["actions"].append(f"已设置位置为 {location}")
                        else:
                            results["errors"].append(f"无法识别位置 {location}")
                    else:
                        results["errors"].append("请提供位置信息")

                elif intent == "subscribe_weather":
                    results["actions"].append("已订阅天气推送")

                elif intent == "unsubscribe_weather":
                    results["actions"].append("已取消天气订阅")

                elif intent == "delayed_action":
                    delay_minutes = intent_item.get("delay_minutes", 0)
                    action_text = intent_item.get("action", "")

                    if delay_minutes > 0 and action_text:
                        # 解析延迟操作的具体内容
                        action_intents = self._parse_intents(action_text)

                        if action_intents:
                            # 创建延迟任务
                            from datetime import datetime, timedelta
                            job_id = f"delayed_action_{event.unified_msg_origin}_{id(intent_item)}"
                            umo = event.unified_msg_origin

                            async def execute_delayed_action():
                                """执行延迟操作"""
                                try:
                                    action_results = await self._execute_intents(event, action_intents, action_text, user_id)

                                    # 发送执行结果通知
                                    if action_results["actions"]:
                                        msg = f"⏰ 延迟任务执行完成：{', '.join(action_results['actions'])}"
                                    elif action_results["errors"]:
                                        msg = f"⏰ 延迟任务执行失败：{', '.join(action_results['errors'])}"
                                    else:
                                        msg = f"⏰ 延迟任务已完成"

                                    await self.context.send_message(umo, MessageChain().message(msg))
                                except Exception as e:
                                    logger.error(f"延迟任务执行失败: {e}")
                                    await self.context.send_message(umo, MessageChain().message(f"延迟任务执行出错: {e}"))
                                finally:
                                    # 清理任务记录
                                    if hasattr(self, '_delayed_jobs') and job_id in self._delayed_jobs:
                                        del self._delayed_jobs[job_id]

                            # 计算执行时间
                            run_time = datetime.now() + timedelta(minutes=delay_minutes)

                            # 添加一次性定时任务
                            job = self.scheduler.add_job(
                                execute_delayed_action,
                                'date',
                                run_date=run_time,
                                id=job_id
                            )

                            # 确保 scheduler 运行
                            if not self.scheduler.running:
                                self.scheduler.start()

                            # 记录延迟任务（用于取消等）
                            if not hasattr(self, '_delayed_jobs'):
                                self._delayed_jobs = {}
                            self._delayed_jobs[job_id] = {
                                "job": job,
                                "action": action_text,
                                "delay_minutes": delay_minutes,
                                "run_time": run_time,
                                "created_at": datetime.now()
                            }

                            results["actions"].append(f"已设置 {delay_minutes} 分钟后{action_text}")
                        else:
                            results["errors"].append(f"无法识别操作: {action_text}")
                    else:
                        results["errors"].append("延迟执行参数不完整")

                elif intent == "help":
                    results["data"]["help"] = "已显示帮助"

            except Exception as e:
                logger.error(f"执行意图 {intent} 失败: {e}")
                results["errors"].append(f"执行失败: {str(e)}")

        return results

    async def _get_temperature_data(self, sensor_name: str = "") -> Optional[str]:
        """获取温度数据"""
        if not self.ha_client:
            return None

        sensor = None
        if sensor_name:
            sensor = self._get_sensor_by_name(sensor_name)

        if not sensor:
            sensor = self._get_sensor_by_type("temperature")

        if not sensor:
            return None

        entity_id = sensor.get("entity_id", "")
        state = await self.ha_client.get_sensor_state(entity_id)
        if state:
            value = state.get("state", "N/A")
            unit = state.get("attributes", {}).get("unit_of_measurement", "°C")
            name = sensor.get("name", "温度")
            return f"{name}: {value}{unit}"
        return None

    async def _get_humidity_data(self, sensor_name: str = "") -> Optional[str]:
        """获取湿度数据"""
        if not self.ha_client:
            return None

        sensor = None
        if sensor_name:
            sensor = self._get_sensor_by_name(sensor_name)

        if not sensor:
            sensor = self._get_sensor_by_type("humidity")

        if not sensor:
            return None

        entity_id = sensor.get("entity_id", "")
        state = await self.ha_client.get_sensor_state(entity_id)
        if state:
            value = state.get("state", "N/A")
            unit = state.get("attributes", {}).get("unit_of_measurement", "%")
            name = sensor.get("name", "湿度")
            return f"{name}: {value}{unit}"
        return None

    async def _get_all_sensors_data(self) -> Optional[str]:
        """获取所有传感器数据"""
        if not self.ha_client or not self.sensors:
            return None

        results = []
        for sensor in self.sensors:
            if isinstance(sensor, dict) and sensor.get("enabled", True):
                entity_id = sensor.get("entity_id", "")
                name = sensor.get("name", entity_id)
                state = await self.ha_client.get_sensor_state(entity_id)
                if state:
                    value = state.get("state", "N/A")
                    unit = state.get("attributes", {}).get("unit_of_measurement", "")
                    results.append(f"{name}: {value}{unit}")

        return "\n".join(results) if results else None

    async def _get_devices_data(self) -> Optional[str]:
        """获取设备状态数据"""
        if not self.ha_client or not self.switches:
            return None

        results = []
        for device in self.switches:
            if isinstance(device, dict):
                entity_id = device.get("entity_id", "")
                name = device.get("name", entity_id)
                state = await self.ha_client.get_entity_state(entity_id)
                if state:
                    dev_state = state.get("state", "unknown")
                    state_map = {
                        "on": "开启",
                        "off": "关闭",
                        "open": "打开",
                        "opening": "正在打开",
                        "closed": "关闭",
                        "closing": "正在关闭",
                        "cool": "制冷",
                        "heat": "制热",
                    }
                    state_text = state_map.get(dev_state, dev_state)
                    results.append(f"{name}: {state_text}")

        return "\n".join(results) if results else None

    def _is_curtain_device(self, device: dict) -> bool:
        """Check whether a configured device is a cover."""
        if not isinstance(device, dict):
            return False
        template_key = device.get("__template_key", "")
        entity_id = device.get("entity_id", "")
        return template_key in ("curtain", "cover") or entity_id.startswith("cover.")

    def _get_curtain_by_name(self, name: str) -> Optional[dict]:
        """Find a curtain device by name."""
        name_lower = name.lower().strip()
        curtains = [d for d in self.switches if self._is_curtain_device(d)]
        if not curtains:
            return None

        if name_lower and name_lower not in ("窗帘", "百叶", "卷帘"):
            for curtain in curtains:
                curtain_name = curtain.get("name", "").lower()
                entity_id = curtain.get("entity_id", "").lower()
                if name_lower in curtain_name or name_lower in entity_id:
                    return curtain
            return None

        return curtains[0]

    def _normalize_curtain_action(self, action: str) -> str:
        """Normalize curtain action text."""
        action = (action or "").lower()
        action_map = {
            "打开": "open",
            "开启": "open",
            "拉开": "open",
            "开": "open",
            "open": "open",
            "关闭": "close",
            "关上": "close",
            "拉上": "close",
            "关": "close",
            "close": "close",
            "停止": "stop",
            "暂停": "stop",
            "stop": "stop",
        }
        return action_map.get(action, action)

    def _format_curtain_action(self, action: str) -> str:
        """Format curtain action for user-facing messages."""
        action_text = {
            "open": "打开",
            "close": "关闭",
            "stop": "停止",
        }
        return action_text.get(action, action)

    async def _get_curtains_data(self, device_name: str = "") -> Optional[str]:
        """Get curtain status data."""
        if not self.ha_client or not self.switches:
            return None

        if device_name:
            curtains = [self._get_curtain_by_name(device_name)]
        else:
            curtains = [d for d in self.switches if self._is_curtain_device(d)]

        results = []
        state_map = {
            "open": "打开",
            "opening": "正在打开",
            "closed": "关闭",
            "closing": "正在关闭",
            "unknown": "未知",
            "unavailable": "不可用",
        }
        for curtain in curtains:
            if not curtain:
                continue
            entity_id = curtain.get("entity_id", "")
            name = curtain.get("name", entity_id)
            state = await self.ha_client.get_entity_state(entity_id)
            if not state:
                results.append(f"{name}: 获取失败")
                continue

            cover_state = state.get("state", "unknown")
            state_text = state_map.get(cover_state, cover_state)
            position = state.get("attributes", {}).get("current_position")
            if position is not None:
                results.append(f"{name}: {state_text} ({position}%)")
            else:
                results.append(f"{name}: {state_text}")

        return "\n".join(results) if results else None

    async def _control_curtain(self, device_name: str, action: str) -> bool:
        """Control a curtain device."""
        if not self.ha_client:
            return False

        curtain = self._get_curtain_by_name(device_name)
        if not curtain:
            logger.warning(f"Curtain device not found: {device_name}")
            return False

        entity_id = curtain.get("entity_id", "")
        action = self._normalize_curtain_action(action)
        if action == "open":
            return await self.ha_client.open_cover(entity_id)
        if action == "close":
            return await self.ha_client.close_cover(entity_id)
        if action == "stop":
            return await self.ha_client.stop_cover(entity_id)

        logger.warning(f"Unsupported curtain action: {action}")
        return False

    async def _set_curtain_position(self, device_name: str, position: int) -> bool:
        """Set a curtain position."""
        if not self.ha_client or position is None:
            return False

        curtain = self._get_curtain_by_name(device_name)
        if not curtain:
            logger.warning(f"Curtain device not found: {device_name}")
            return False

        entity_id = curtain.get("entity_id", "")
        return await self.ha_client.set_cover_position(entity_id, position)

    async def _control_device(self, device_name: str, action: str) -> bool:
        """控制设备"""
        if not self.ha_client:
            return False

        device = self._get_device_by_name(device_name)
        if not device:
            logger.warning(f"未找到设备: {device_name}")
            return False

        entity_id = device.get("entity_id", "")
        if action == "on":
            return await self.ha_client.turn_on(entity_id)
        else:
            return await self.ha_client.turn_off(entity_id)

    async def _control_ac_mode(self, device_name: str, mode: str) -> bool:
        """控制空调模式"""
        if not self.ha_client:
            return False

        device = self._get_device_by_name(device_name)
        if not device:
            # 尝试查找空调类型设备
            for d in self.switches:
                if isinstance(d, dict):
                    template_key = d.get("__template_key", "")
                    if template_key == "ac":
                        device = d
                        break

        if not device:
            logger.warning(f"未找到空调设备: {device_name}")
            return False

        entity_id = device.get("entity_id", "")
        return await self.ha_client.set_climate_mode(entity_id, mode)

    async def _control_ac_temp(self, device_name: str, temperature: int) -> bool:
        """控制空调温度"""
        if not self.ha_client:
            return False

        device = self._get_device_by_name(device_name)
        if not device:
            # 尝试查找空调类型设备
            for d in self.switches:
                if isinstance(d, dict):
                    template_key = d.get("__template_key", "")
                    if template_key == "ac":
                        device = d
                        break

        if not device:
            logger.warning(f"未找到空调设备: {device_name}")
            return False

        entity_id = device.get("entity_id", "")
        return await self.ha_client.set_climate_temperature(entity_id, temperature)

    async def _get_weather_data(self, user_id: str) -> Optional[str]:
        """获取天气数据"""
        location = await self._get_user_location(user_id)
        if not location:
            return None

        adcode = location.get("adcode", "")
        city = location.get("city", "")

        weather_data = await self.weather_api.get_weather(adcode)
        if weather_data:
            return self.weather_api.format_weather_summary(weather_data)

        return None

    async def _get_hourly_weather_data(self, user_id: str, hours: int) -> Optional[str]:
        """获取小时级天气数据"""
        location = await self._get_user_location(user_id)
        if not location:
            return None

        adcode = location.get("adcode", "")
        hourly_data = await self.weather_api.get_weather_at_hour(adcode, hours)
        if hourly_data:
            return self.weather_api.format_hourly_weather(hourly_data, hours)

        return None

    async def _set_user_location(self, user_id: str, location_text: str) -> bool:
        """设置用户位置"""
        result = self.location_mgr.match_location(location_text)
        if result:
            import time
            result["updated_at"] = int(time.time())
            await self.put_kv_data(f"user_location:{user_id}", result)
            return True
        return False

    async def _get_user_location(self, user_id: str) -> Optional[dict]:
        """获取用户位置"""
        return await self.get_kv_data(f"user_location:{user_id}", None)

    async def _polish_response(
        self,
        event: AstrMessageEvent,
        user_query: str,
        results: dict
    ) -> str:
        """使用 LLM 润色回复"""
        # 构建上下文
        context_parts = []
        if results["data"]:
            for key, value in results["data"].items():
                context_parts.append(f"【{key}】\n{value}")
        if results["actions"]:
            context_parts.append(f"【操作】{', '.join(results['actions'])}")
        if results["errors"]:
            context_parts.append(f"【问题】{', '.join(results['errors'])}")

        context_str = "\n".join(context_parts)

        # 如果没有任何结果，返回默认消息
        if not context_str:
            return "操作完成"

        # 尝试使用 LLM 润色
        try:
            umo = event.unified_msg_origin

            # 优先使用配置的专用 Provider，否则使用默认 Provider
            provider_id = self.llm_response_provider
            logger.info(f"[HAOS] llm_response_provider 配置值: '{provider_id}'")

            if not provider_id:
                provider_id = await self.context.get_current_chat_provider_id(umo=umo)
                logger.info(f"[HAOS] 从 context 获取的 provider_id: '{provider_id}'")

            if provider_id:
                # 获取人格提示词
                persona_prompt = None
                if self.enable_persona:
                    persona_prompt = await self.llm_handler.get_persona_prompt(
                        umo=umo,
                        persona_name=self.persona_name if self.persona_name else None
                    )

                # 构建人格提示部分
                persona_section = ""
                if persona_prompt:
                    persona_section = f"""【人格设定】
{persona_prompt}

请以上述人格设定回答用户的问题，保持人格的风格和语气。

"""

                prompt = f"""{persona_section}用户问: {user_query}

我已获取以下信息:
{context_str}

请根据以上信息，用自然、友好的语言回复用户。要求：
1. 回答用户的所有问题，不要遗漏
2. 如果用户问"穿什么"、"要不要加衣服"等，根据温度数据给出穿衣建议
3. 如果用户问"适合做什么"等分析类问题，结合数据给出建议
4. 如果执行了多个设备操作，请合并告知，例如"已为您打开灯和空调"
5. 回复要简洁、自然，不要机械地罗列数据
6. 如果有操作失败，请告知用户
7. 不要提及意图标记或技术细节"""

                logger.info(f"[HAOS] 调用 LLM 润色，provider_id: {provider_id}")
                llm_resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                )

                if llm_resp and llm_resp.completion_text:
                    logger.info(f"[HAOS] LLM 润色成功")
                    return llm_resp.completion_text.strip()
                else:
                    logger.warning(f"[HAOS] LLM 润色返回空结果: llm_resp={llm_resp}")
            else:
                logger.warning("[HAOS] 无法获取 LLM Provider ID，跳过润色")

        except Exception as e:
            logger.error(f"[HAOS] LLM 润色失败: {e}", exc_info=True)

        # 回退到简单格式
        logger.info("[HAOS] 使用回退格式返回结果")
        response_parts = []
        if results["data"]:
            for value in results["data"].values():
                response_parts.append(value)
        if results["actions"]:
            response_parts.extend(results["actions"])
        if results["errors"]:
            response_parts.extend(results["errors"])

        return "\n".join(response_parts)
