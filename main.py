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
    "2.2.3",
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
        "device_on": ["打开", "开启", "启动", "开灯", "开空调"],
        "device_off": ["关闭", "关掉", "停止", "关灯", "关空调"],
        "device_query": ["设备状态", "设备情况"],
        "weather_query": ["天气", "天气预报", "今天天气", "明天天气", "后天天气"],
        "hourly_weather": ["小时后天气", "一小时后", "两小时后", "几小时后"],
        "set_location": ["我在", "我的位置", "设置位置"],
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
                    state_map = {"on": "开启", "off": "关闭", "cool": "制冷", "heat": "制热"}
                    state_text = state_map.get(dev_state, dev_state)
                    results.append(f"💡 {name}: {state_text}")
                else:
                    results.append(f"💡 {name}: 获取失败")

        yield event.plain_result("\n".join(results) if results else "无设备数据")

    @filter.command("haoshelp")
    async def help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """🏠 智能家居助手

📋 基础指令:
/get_temperature - 获取温度
/get_humidity - 获取湿度
/sensor - 查询所有传感器
/device - 查询设备状态
/monitor_temp - 启动温度监控
/stop_monitor - 停止监控

🤖 智能助手:
/ha <自然语言> - 智能控制

示例:
/ha 现在温度多少
/ha 卧室温度多少
/ha 打开客厅灯
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
        intents = []

        for intent, keywords in self.INTENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    intent_item = {"intent": intent}

                    # 提取位置信息
                    if intent == "set_location":
                        import re
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
                        import re
                        match = re.search(r"(\d+)\s*小时", text)
                        if match:
                            intent_item["hours"] = int(match.group(1))

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
            "ac_control": r"\[空调控制[:：](.+?)\]",
            "ac_temp": r"\[空调温度[:：](.+?)\]",
            "weather_query": r"\[天气查询\]",
            "hourly_weather": r"\[小时天气[:：](\d+)\]",
            "set_location": r"\[设置位置[:：](.+?)\]",
            "subscribe_weather": r"\[订阅天气\]",
            "unsubscribe_weather": r"\[取消天气订阅\]",
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
                    elif intent == "ac_control":
                        intent_item["mode"] = groups[0].strip()
                    elif intent == "ac_temp":
                        intent_item["temperature"] = groups[0].strip()
                    elif intent == "set_location":
                        intent_item["location"] = groups[0].strip()
                all_matches.append(intent_item)

        # 按出现顺序排序
        all_matches.sort(key=lambda x: x["pos"])

        # 移除 pos 字段
        for item in all_matches:
            item.pop("pos", None)

        return all_matches

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
                    state_map = {"on": "开启", "off": "关闭", "cool": "制冷", "heat": "制热"}
                    state_text = state_map.get(dev_state, dev_state)
                    results.append(f"{name}: {state_text}")

        return "\n".join(results) if results else None

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

            # 优先使用配置的专用 Provider
            provider_id = self.llm_response_provider
            if not provider_id:
                provider_id = await self.context.get_current_chat_provider_id(umo=umo)

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

                llm_resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                )

                if llm_resp and llm_resp.completion_text:
                    return llm_resp.completion_text.strip()

        except Exception as e:
            logger.error(f"LLM 润色失败: {e}")

        # 回退到简单格式
        response_parts = []
        if results["data"]:
            for value in results["data"].values():
                response_parts.append(value)
        if results["actions"]:
            response_parts.extend(results["actions"])
        if results["errors"]:
            response_parts.extend(results["errors"])

        return "\n".join(response_parts)
