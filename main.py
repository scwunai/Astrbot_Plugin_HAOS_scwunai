"""
智能家居助手插件

集成天气查询、传感器监控、智能告警功能
"""

import logging
from pathlib import Path
from typing import Optional

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api.provider import ProviderRequest, LLMResponse
from astrbot.api import AstrBotConfig

from .modules.weather import WeatherAPI
from .modules.homeassistant import HomeAssistantClient
from .modules.location import LocationManager
from .modules.scheduler import SchedulerManager
from .modules.llm_handler import LLMHandler

logger = logging.getLogger(__name__)


@register(
    "Astrbot_Plugin_HAOS_scwunai",
    "scwunai",
    "智能家居助手：天气查询、传感器监控、智能告警",
    "2.0.0",
    "https://github.com/scwunai/Astrbot_Plugin_HAOS_scwunai",
)
class SmartHomePlugin(Star):
    """智能家居助手插件主类"""

    def __init__(self, context: Context, config: AstrBotConfig):
        """
        初始化插件

        Args:
            context: AstrBot 上下文
            config: 插件配置
        """
        super().__init__(context)
        self.config = config

        # 初始化各模块
        self._init_modules()

        # 启动定时任务
        self._setup_schedulers()

    def _init_modules(self):
        """初始化各功能模块"""
        # 天气 API
        self.weather_api = WeatherAPI()

        # HomeAssistant 客户端
        ha_url = self.config.get("home_assistant_url", "")
        ha_token = self.config.get("ha_token", "")
        self.ha_client = HomeAssistantClient(ha_url, ha_token) if ha_url and ha_token else None

        # 位置管理器
        data_dir = Path(__file__).parent / "data"
        self.location_mgr = LocationManager(data_dir)

        # LLM 处理器
        self.llm_handler = LLMHandler(self)

        # 定时任务管理器
        self.scheduler_mgr = SchedulerManager(self)

    def _setup_schedulers(self):
        """设置定时任务"""
        try:
            self.scheduler_mgr.setup()
        except Exception as e:
            logger.error(f"设置定时任务失败: {e}")

    # ==================== 权限管理 ====================

    def _check_permission(self, event: AstrMessageEvent, command: str = None) -> bool:
        """
        检查用户是否有权限执行操作

        Args:
            event: 消息事件
            command: 指令名称（可选）

        Returns:
            是否有权限
        """
        admin_users = self.config.get("admin_users", [])
        admin_groups = self.config.get("admin_groups", [])
        public_commands = self.config.get("public_commands", ["weather", "set_location", "subscribe_weather", "unsubscribe_weather", "haoshelp"])

        # 如果没有配置管理员，则所有人都有权限
        if not admin_users and not admin_groups:
            return True

        # 检查是否是公开指令
        if command and command in public_commands:
            return True

        # 获取用户信息
        user_id = event.get_sender_id()
        umo = event.unified_msg_origin  # 格式：平台名:消息类型:会话ID

        # 解析 umo 获取平台和会话信息
        parts = umo.split(":") if umo else []
        platform = parts[0] if len(parts) > 0 else ""
        session_id = parts[2] if len(parts) > 2 else ""

        # 检查是否是管理员用户
        for admin in admin_users:
            if isinstance(admin, str):
                # 支持格式：平台名:用户ID 或仅用户ID
                if ":" in admin:
                    if admin == f"{platform}:{user_id}":
                        return True
                elif admin == user_id:
                    return True

        # 检查是否在管理员群组
        for group in admin_groups:
            if isinstance(group, str):
                if ":" in group:
                    if group == f"{platform}:{session_id}":
                        return True
                elif group == session_id:
                    return True

        return False

    def _get_permission_denied_message(self) -> str:
        """获取权限拒绝消息"""
        return "⚠️ 您没有权限执行此操作，请联系管理员"

    # ==================== 用户位置管理 ====================

    async def get_user_location(self, user_id: str) -> Optional[dict]:
        """
        获取用户位置

        Args:
            user_id: 用户 ID

        Returns:
            位置信息字典
        """
        key = f"user_location:{user_id}"
        return await self.get_kv_data(key, None)

    async def set_user_location(self, user_id: str, location: dict):
        """
        设置用户位置

        Args:
            user_id: 用户 ID
            location: 位置信息
        """
        import time

        location["updated_at"] = int(time.time())
        key = f"user_location:{user_id}"
        await self.put_kv_data(key, location)

    # ==================== 指令处理 ====================

    @filter.command("set_location")
    async def set_location(self, event: AstrMessageEvent):
        """设置用户位置"""
        message = event.get_message_str().strip()
        # 移除指令前缀
        parts = message.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("请提供位置信息，例如：/set_location 北京")
            return

        location_text = parts[1]
        result = await self._handle_location_setup(event, location_text)
        yield event.plain_result(result)

    @filter.command("weather")
    async def get_weather(self, event: AstrMessageEvent):
        """获取当前天气"""
        result = await self._handle_weather_query(event)
        yield event.plain_result(result)

    @filter.command("subscribe_weather")
    async def subscribe_weather(self, event: AstrMessageEvent):
        """订阅天气推送"""
        user_id = event.get_sender_id()
        umo = event.unified_msg_origin

        # 检查是否已设置位置
        location = await self.get_user_location(user_id)
        if not location:
            yield event.plain_result("请先设置位置，使用 /set_location 城市名")
            return

        await self.scheduler_mgr.add_weather_subscriber(user_id, umo)
        yield event.plain_result("✅ 已成功订阅每日天气推送！")

    @filter.command("unsubscribe_weather")
    async def unsubscribe_weather(self, event: AstrMessageEvent):
        """取消天气订阅"""
        user_id = event.get_sender_id()
        await self.scheduler_mgr.remove_weather_subscriber(user_id)
        yield event.plain_result("✅ 已取消天气推送订阅。")

    @filter.command("sensor")
    async def get_sensor(self, event: AstrMessageEvent):
        """查询传感器状态"""
        if not self._check_permission(event, "sensor"):
            yield event.plain_result(self._get_permission_denied_message())
            return
        result = await self._handle_sensor_query(event)
        yield event.plain_result(result)

    @filter.command("list_sensors")
    async def list_sensors(self, event: AstrMessageEvent):
        """列出已配置的传感器"""
        if not self._check_permission(event, "list_sensors"):
            yield event.plain_result(self._get_permission_denied_message())
            return
        sensors = self.config.get("sensors", [])
        if not sensors:
            yield event.plain_result("暂未配置任何传感器")
            return

        lines = ["📋 已配置的传感器："]
        for i, sensor in enumerate(sensors, 1):
            if not isinstance(sensor, dict):
                continue
            name = sensor.get("name", sensor.get("entity_id", "未命名"))
            entity_id = sensor.get("entity_id", "")
            enabled = "✅" if sensor.get("enabled", True) else "❌"
            lines.append(f"{i}. {name} ({entity_id}) {enabled}")

        yield event.plain_result("\n".join(lines))

    # ==================== 开关设备控制 ====================

    @filter.command("device")
    async def device_status(self, event: AstrMessageEvent):
        """查询设备状态"""
        if not self._check_permission(event, "device"):
            yield event.plain_result(self._get_permission_denied_message())
            return
        result = await self._handle_device_query(event)
        yield event.plain_result(result)

    @filter.command("list_devices")
    async def list_devices(self, event: AstrMessageEvent):
        """列出已配置的设备"""
        if not self._check_permission(event, "list_devices"):
            yield event.plain_result(self._get_permission_denied_message())
            return
        switches = self.config.get("switches", [])
        if not switches:
            yield event.plain_result("暂未配置任何设备")
            return

        lines = ["📋 已配置的设备："]
        for i, device in enumerate(switches, 1):
            if not isinstance(device, dict):
                continue
            name = device.get("name", device.get("entity_id", "未命名"))
            entity_id = device.get("entity_id", "")
            device_type = device.get("__template_key", "generic")
            lines.append(f"{i}. {name} ({device_type}) - {entity_id}")

        yield event.plain_result("\n".join(lines))

    @filter.command("turn_on")
    async def turn_on_device(self, event: AstrMessageEvent):
        """开启设备"""
        if not self._check_permission(event, "turn_on"):
            yield event.plain_result(self._get_permission_denied_message())
            return
        message = event.get_message_str().strip()
        parts = message.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("请指定设备名称，例如：/turn_on 客厅灯")
            return

        device_name = parts[1]
        result = await self._handle_device_control(device_name, "on")
        yield event.plain_result(result)

    @filter.command("turn_off")
    async def turn_off_device(self, event: AstrMessageEvent):
        """关闭设备"""
        if not self._check_permission(event, "turn_off"):
            yield event.plain_result(self._get_permission_denied_message())
            return
        message = event.get_message_str().strip()
        parts = message.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("请指定设备名称，例如：/turn_off 客厅灯")
            return

        device_name = parts[1]
        result = await self._handle_device_control(device_name, "off")
        yield event.plain_result(result)

    @filter.command("air_quality")
    async def air_quality(self, event: AstrMessageEvent):
        """查询空气质量"""
        if not self._check_permission(event, "air_quality"):
            yield event.plain_result(self._get_permission_denied_message())
            return
        result = await self._handle_air_quality_query(event)
        yield event.plain_result(result)

    @filter.command("ac")
    async def ac_control(self, event: AstrMessageEvent):
        """空调控制"""
        if not self._check_permission(event, "ac"):
            yield event.plain_result(self._get_permission_denied_message())
            return
        message = event.get_message_str().strip()
        parts = message.split(maxsplit=1)
        if len(parts) < 2:
            # 无参数时显示空调状态
            result = await self._handle_ac_status(event)
        else:
            result = await self._handle_ac_command(event, parts[1])
        yield event.plain_result(result)

    @filter.command("ac_temp")
    async def ac_set_temp(self, event: AstrMessageEvent):
        """设置空调温度"""
        if not self._check_permission(event, "ac_temp"):
            yield event.plain_result(self._get_permission_denied_message())
            return
        message = event.get_message_str().strip()
        parts = message.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("请指定温度，例如：/ac_temp 26")
            return

        try:
            temp = int(parts[1])
            result = await self._handle_ac_set_temperature(event, temp)
            yield event.plain_result(result)
        except ValueError:
            yield event.plain_result("温度必须是数字，例如：/ac_temp 26")

    @filter.command("haoshelp")
    async def help(self, event: AstrMessageEvent):
        """帮助信息"""
        help_text = await self.llm_handler.generate_help_message()
        yield event.plain_result(help_text)

    # ==================== LLM 集成 ====================

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """LLM 请求处理 - 注入系统提示"""
        system_prompt = self.llm_handler.get_system_prompt()
        if req.system_prompt:
            req.system_prompt = f"{req.system_prompt}\n\n{system_prompt}"
        else:
            req.system_prompt = system_prompt

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        """LLM 响应处理 - 解析意图并执行"""
        text = resp.completion_text.strip()
        user_id = event.get_sender_id()
        original_message = event.get_message_str().strip()

        # 解析所有意图标记
        intents = self._parse_llm_intents(text)
        if not intents:
            return  # 没有意图标记，保持原响应

        # 需要权限控制的意图
        admin_intents = {"sensor_query", "temperature_query", "humidity_query", "air_quality",
                         "device_query", "turn_on", "turn_off", "ac_control", "ac_temp"}

        # 检查是否有需要权限的意图
        admin_intent_items = [item for item in intents if item["intent"] in admin_intents]
        public_intent_items = [item for item in intents if item["intent"] not in admin_intents]

        # 如果所有意图都需要权限且用户无权限，只输出一次拒绝消息
        if admin_intent_items and not public_intent_items:
            has_any_permission = any(
                self._check_permission(event, item["intent"])
                for item in admin_intent_items
            )
            if not has_any_permission:
                resp.completion_text = self._get_permission_denied_message()
                return

        # 执行所有意图，收集数据和操作结果
        collected_data = {}
        executed_actions = []

        for intent_item in intents:
            try:
                result = await self._execute_single_intent_v2(
                    event, intent_item, user_id, collected_data, executed_actions
                )
            except Exception as e:
                logger.error(f"处理意图 {intent_item['intent']} 失败: {e}")
                executed_actions.append({
                    "type": "处理失败",
                    "detail": str(e),
                    "success": False
                })

        # 判断是否需要 LLM 生成自然回复
        # 条件：有查询数据 或 有多个操作 或 用户原始消息包含分析类关键词
        has_query_data = bool(collected_data)
        has_multiple_actions = len(executed_actions) > 1
        has_analysis_request = any(kw in original_message for kw in ["分析", "建议", "适合", "怎么样", "如何", "怎样"])

        if has_query_data or has_multiple_actions or has_analysis_request:
            # 使用 LLM 生成自然回复
            try:
                natural_response = await self._generate_natural_response(
                    event, original_message, collected_data, executed_actions
                )
                if natural_response:
                    resp.completion_text = natural_response
                else:
                    # LLM 调用失败，使用默认格式
                    resp.completion_text = self._format_fallback_response(collected_data, executed_actions)
            except Exception as e:
                logger.error(f"生成自然回复失败: {e}")
                resp.completion_text = self._format_fallback_response(collected_data, executed_actions)
        else:
            # 单个简单操作，直接返回结果
            if executed_actions:
                resp.completion_text = executed_actions[0].get("detail", "操作完成")
            elif collected_data:
                resp.completion_text = self._format_fallback_response(collected_data, executed_actions)

    async def _execute_single_intent_v2(
        self,
        event: AstrMessageEvent,
        intent_item: dict,
        user_id: str,
        collected_data: dict,
        executed_actions: list
    ) -> None:
        """
        执行单个意图（新版本，收集数据而非返回字符串）

        Args:
            event: 消息事件
            intent_item: 意图信息字典
            user_id: 用户 ID
            collected_data: 收集的数据字典
            executed_actions: 执行的操作列表
        """
        intent = intent_item["intent"]

        # 需要权限控制的意图
        admin_intents = ["sensor_query", "temperature_query", "humidity_query", "air_quality",
                         "device_query", "turn_on", "turn_off", "ac_control", "ac_temp"]

        if intent == "weather_query":
            data = await self._collect_weather_data(event)
            if data:
                collected_data["weather"] = data

        elif intent == "set_location":
            location_text = intent_item.get("location", "")
            if location_text:
                result = await self._handle_location_setup(event, location_text)
                executed_actions.append({
                    "type": "设置位置",
                    "detail": result,
                    "success": "✅" in result
                })
            else:
                executed_actions.append({
                    "type": "设置位置",
                    "detail": "请提供城市名称",
                    "success": False
                })

        elif intent in admin_intents:
            if not self._check_permission(event, intent):
                executed_actions.append({
                    "type": "权限检查",
                    "detail": self._get_permission_denied_message(),
                    "success": False
                })
            elif intent == "sensor_query":
                data = await self._collect_sensor_data(event)
                if data:
                    collected_data["sensors"] = data
            elif intent == "temperature_query":
                data = await self._collect_temperature_data(event)
                if data:
                    collected_data["temperature"] = data
            elif intent == "humidity_query":
                data = await self._collect_humidity_data(event)
                if data:
                    collected_data["humidity"] = data
            elif intent == "air_quality":
                data = await self._collect_air_quality_data(event)
                if data:
                    collected_data["air_quality"] = data
            elif intent == "device_query":
                data = await self._collect_device_data(event)
                if data:
                    collected_data["devices"] = data
            elif intent == "turn_on":
                device_name = intent_item.get("device", "")
                if device_name:
                    result = await self._handle_device_control(device_name, "on")
                    executed_actions.append({
                        "type": "打开设备",
                        "detail": result,
                        "device": device_name,
                        "success": "✅" in result
                    })
                else:
                    executed_actions.append({
                        "type": "打开设备",
                        "detail": "请指定设备名称",
                        "success": False
                    })
            elif intent == "turn_off":
                device_name = intent_item.get("device", "")
                if device_name:
                    result = await self._handle_device_control(device_name, "off")
                    executed_actions.append({
                        "type": "关闭设备",
                        "detail": result,
                        "device": device_name,
                        "success": "✅" in result
                    })
                else:
                    executed_actions.append({
                        "type": "关闭设备",
                        "detail": "请指定设备名称",
                        "success": False
                    })
            elif intent == "ac_control":
                command = intent_item.get("command", "")
                if command:
                    result = await self._handle_ac_command(event, command)
                    executed_actions.append({
                        "type": "空调控制",
                        "detail": result,
                        "success": "✅" in result
                    })
                else:
                    data = await self._collect_ac_data(event)
                    if data:
                        collected_data["ac"] = data
            elif intent == "ac_temp":
                temp_str = intent_item.get("temperature", "")
                if temp_str:
                    try:
                        temp = int(temp_str)
                        result = await self._handle_ac_set_temperature(event, temp)
                        executed_actions.append({
                            "type": "设置温度",
                            "detail": result,
                            "success": "✅" in result
                        })
                    except ValueError:
                        executed_actions.append({
                            "type": "设置温度",
                            "detail": "温度必须是数字",
                            "success": False
                        })
                else:
                    executed_actions.append({
                        "type": "设置温度",
                        "detail": "请指定温度值",
                        "success": False
                    })

        elif intent == "subscribe_weather":
            location = await self.get_user_location(user_id)
            if not location:
                executed_actions.append({
                    "type": "订阅天气",
                    "detail": "请先设置位置",
                    "success": False
                })
            else:
                await self.scheduler_mgr.add_weather_subscriber(user_id, event.unified_msg_origin)
                executed_actions.append({
                    "type": "订阅天气",
                    "detail": "已成功订阅天气推送",
                    "success": True
                })

        elif intent == "unsubscribe_weather":
            await self.scheduler_mgr.remove_weather_subscriber(user_id)
            executed_actions.append({
                "type": "取消订阅",
                "detail": "已取消天气推送订阅",
                "success": True
            })

        elif intent == "help":
            help_text = await self.llm_handler.generate_help_message()
            executed_actions.append({
                "type": "帮助",
                "detail": help_text,
                "success": True
            })

    async def _generate_natural_response(
        self,
        event: AstrMessageEvent,
        user_message: str,
        collected_data: dict,
        executed_actions: list[dict]
    ) -> str:
        """
        使用 LLM 生成自然回复

        Args:
            event: 消息事件
            user_message: 用户原始消息
            collected_data: 收集的数据
            executed_actions: 执行的操作列表

        Returns:
            自然回复文本
        """
        try:
            # 获取当前会话的 provider
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)

            if not provider_id:
                return None

            # 生成提示词
            prompt = self.llm_handler.get_response_prompt(user_message, collected_data, executed_actions)

            # 调用 LLM
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt
            )

            return llm_resp.completion_text if llm_resp else None

        except Exception as e:
            logger.error(f"调用 LLM 生成回复失败: {e}")
            return None

    def _format_fallback_response(self, collected_data: dict, executed_actions: list[dict]) -> str:
        """
        格式化备用回复（当 LLM 调用失败时使用）

        Args:
            collected_data: 收集的数据
            executed_actions: 执行的操作列表

        Returns:
            格式化的回复文本
        """
        parts = []

        # 数据部分
        if collected_data.get("weather"):
            parts.append(collected_data["weather"])
        if collected_data.get("temperature"):
            parts.append(collected_data["temperature"])
        if collected_data.get("humidity"):
            parts.append(collected_data["humidity"])
        if collected_data.get("air_quality"):
            parts.append(collected_data["air_quality"])
        if collected_data.get("sensors"):
            parts.append(collected_data["sensors"])
        if collected_data.get("devices"):
            parts.append(collected_data["devices"])

        # 操作部分（去重）
        seen_details = set()
        for action in executed_actions:
            detail = action.get("detail", "")
            if detail and detail not in seen_details and not detail.startswith("⚠️"):
                parts.append(detail)
                seen_details.add(detail)

        return "\n".join(parts) if parts else "操作完成"

    # ==================== 数据收集方法 ====================

    async def _collect_weather_data(self, event: AstrMessageEvent) -> str:
        """收集天气数据"""
        user_id = event.get_sender_id()
        location = await self.get_user_location(user_id)
        if not location:
            return None

        adcode = location.get("adcode")
        if not adcode:
            return None

        weather_data = await self.weather_api.get_weather(adcode)
        location_name = self.location_mgr.format_location(location)

        return await self.llm_handler.generate_weather_summary(weather_data, location_name)

    async def _collect_sensor_data(self, event: AstrMessageEvent) -> str:
        """收集传感器数据"""
        return await self._handle_sensor_query(event)

    async def _collect_temperature_data(self, event: AstrMessageEvent) -> str:
        """收集温度数据"""
        return await self._handle_temperature_query(event)

    async def _collect_humidity_data(self, event: AstrMessageEvent) -> str:
        """收集湿度数据"""
        return await self._handle_humidity_query(event)

    async def _collect_air_quality_data(self, event: AstrMessageEvent) -> str:
        """收集空气质量数据"""
        return await self._handle_air_quality_query(event)

    async def _collect_device_data(self, event: AstrMessageEvent) -> str:
        """收集设备状态数据"""
        return await self._handle_device_query(event)

    async def _collect_ac_data(self, event: AstrMessageEvent) -> str:
        """收集空调状态数据"""
        return await self._handle_ac_status(event)

    def _parse_llm_intents(self, text: str) -> list[dict]:
        """
        解析 LLM 响应中的所有意图标记

        Args:
            text: LLM 响应文本

        Returns:
            意图信息字典列表，按出现顺序排列
        """
        import re

        patterns = {
            "weather_query": r"\[天气查询\]",
            "set_location": r"\[设置位置[:：]?(.+?)\]",
            "sensor_query": r"\[传感器查询\]",
            "temperature_query": r"\[温度查询\]",
            "humidity_query": r"\[湿度查询\]",
            "air_quality": r"\[空气质量查询\]",
            "device_query": r"\[设备状态查询\]",
            "turn_on": r"\[打开设备[:：]?(.+?)\]",
            "turn_off": r"\[关闭设备[:：]?(.+?)\]",
            "ac_control": r"\[空调控制[:：]?(.+?)\]",
            "ac_temp": r"\[空调温度[:：]?(.+?)\]",
            "subscribe_weather": r"\[订阅天气\]",
            "unsubscribe_weather": r"\[取消天气订阅\]",
            "help": r"\[帮助\]",
        }

        # 按位置排序匹配所有意图
        all_matches = []
        for intent_name, pattern in patterns.items():
            for match in re.finditer(pattern, text):
                result = {"intent": intent_name, "match_start": match.start()}
                if intent_name == "set_location" and match.groups():
                    result["location"] = match.group(1).strip()
                elif intent_name in ["turn_on", "turn_off"] and match.groups():
                    result["device"] = match.group(1).strip()
                elif intent_name == "ac_control" and match.groups():
                    result["command"] = match.group(1).strip()
                elif intent_name == "ac_temp" and match.groups():
                    result["temperature"] = match.group(1).strip()
                all_matches.append(result)

        # 按出现顺序排序
        all_matches.sort(key=lambda x: x["match_start"])

        # 移除 match_start 字段
        for item in all_matches:
            del item["match_start"]

        return all_matches

    # ==================== 内部处理方法 ====================

    async def _handle_location_setup(
        self, event: AstrMessageEvent, location_text: str
    ) -> str:
        """
        处理用户位置设置

        Args:
            event: 消息事件
            location_text: 位置文本

        Returns:
            处理结果消息
        """
        user_id = event.get_sender_id()

        # 匹配位置
        location = self.location_mgr.match_location(location_text)
        if not location:
            return await self.llm_handler.generate_set_location_failed(location_text)

        # 保存位置
        await self.set_user_location(user_id, location)

        # 格式化位置名称
        location_name = self.location_mgr.format_location(location)
        return await self.llm_handler.generate_set_location_success(location_name)

    async def _handle_weather_query(self, event: AstrMessageEvent) -> str:
        """
        处理天气查询

        Args:
            event: 消息事件

        Returns:
            天气信息
        """
        user_id = event.get_sender_id()

        # 获取用户位置
        location = await self.get_user_location(user_id)
        if not location:
            return await self.llm_handler.generate_location_question()

        # 获取天气数据
        adcode = location.get("adcode")
        if not adcode:
            return "位置信息不完整，请重新设置位置"

        weather_data = await self.weather_api.get_weather(adcode)
        location_name = self.location_mgr.format_location(location)

        return await self.llm_handler.generate_weather_summary(weather_data, location_name)

    async def _handle_sensor_query(self, event: AstrMessageEvent) -> str:
        """
        处理传感器查询

        Args:
            event: 消息事件

        Returns:
            传感器状态信息
        """
        if not self.ha_client:
            return "HomeAssistant 未配置，请在插件设置中配置连接信息"

        sensors = self.config.get("sensors", [])
        if not sensors:
            return "暂未配置任何传感器，请在插件设置中添加"

        sensor_data = []
        for sensor in sensors:
            # 跳过非字典类型的配置项
            if not isinstance(sensor, dict):
                logger.warning(f"传感器配置格式错误: {sensor}")
                continue

            entity_id = sensor.get("entity_id")
            if not entity_id:
                continue

            state = await self.ha_client.get_sensor_state(entity_id)
            if state:
                value = state.get("state", "N/A")
                attributes = state.get("attributes", {})
                unit = sensor.get("unit") or attributes.get("unit_of_measurement", "")
                status = "ok" if value not in ["unavailable", "unknown"] else "error"

                # 从 template_list 的 __template_key 获取传感器类型
                sensor_type = sensor.get("__template_key", "generic")

                sensor_data.append(
                    {
                        "name": sensor.get("name", entity_id),
                        "entity_id": entity_id,
                        "value": value,
                        "unit": unit,
                        "status": status,
                        "sensor_type": sensor_type,
                    }
                )

        return await self.llm_handler.generate_sensor_summary(sensor_data)

    async def _handle_temperature_query(self, event: AstrMessageEvent) -> str:
        """
        处理温度查询

        Args:
            event: 消息事件

        Returns:
            温度信息
        """
        if not self.ha_client:
            return "HomeAssistant 未配置"

        sensors = self.config.get("sensors", [])
        # 从 template_list 筛选温度传感器
        temp_sensors = [
            s for s in sensors
            if isinstance(s, dict) and s.get("__template_key") == "temperature"
        ]

        if not temp_sensors:
            # 尝试查找任何温度相关传感器
            all_sensors = await self.ha_client.get_all_sensors()
            temp_sensors = [
                {"entity_id": s["entity_id"], "name": s.get("attributes", {}).get("friendly_name", s["entity_id"])}
                for s in all_sensors
                if "temp" in s["entity_id"].lower() or "温度" in s.get("attributes", {}).get("friendly_name", "")
            ]

        if not temp_sensors:
            return "未找到温度传感器"

        results = []
        for sensor in temp_sensors[:3]:  # 最多显示3个
            entity_id = sensor.get("entity_id")
            if not entity_id:
                continue
            state = await self.ha_client.get_sensor_state(entity_id)
            if state:
                value = state.get("state", "N/A")
                unit = state.get("attributes", {}).get("unit_of_measurement", "°C")
                name = sensor.get("name", entity_id)
                results.append(f"{name}: {value}{unit}")

        return "\n".join(results) if results else "获取温度数据失败"

    async def _handle_humidity_query(self, event: AstrMessageEvent) -> str:
        """
        处理湿度查询

        Args:
            event: 消息事件

        Returns:
            湿度信息
        """
        if not self.ha_client:
            return "HomeAssistant 未配置"

        sensors = self.config.get("sensors", [])
        # 从 template_list 筛选湿度传感器
        humidity_sensors = [
            s for s in sensors
            if isinstance(s, dict) and s.get("__template_key") == "humidity"
        ]

        if not humidity_sensors:
            all_sensors = await self.ha_client.get_all_sensors()
            humidity_sensors = [
                {"entity_id": s["entity_id"], "name": s.get("attributes", {}).get("friendly_name", s["entity_id"])}
                for s in all_sensors
                if "humid" in s["entity_id"].lower() or "湿度" in s.get("attributes", {}).get("friendly_name", "")
            ]

        if not humidity_sensors:
            return "未找到湿度传感器"

        results = []
        for sensor in humidity_sensors[:3]:
            entity_id = sensor.get("entity_id")
            if not entity_id:
                continue
            state = await self.ha_client.get_sensor_state(entity_id)
            if state:
                value = state.get("state", "N/A")
                unit = state.get("attributes", {}).get("unit_of_measurement", "%")
                name = sensor.get("name", entity_id)
                results.append(f"{name}: {value}{unit}")

        return "\n".join(results) if results else "获取湿度数据失败"

    async def _handle_air_quality_query(self, event: AstrMessageEvent) -> str:
        """
        处理空气质量查询

        Args:
            event: 消息事件

        Returns:
            空气质量信息
        """
        if not self.ha_client:
            return "HomeAssistant 未配置"

        sensors = self.config.get("sensors", [])
        # 筛选空气质量相关传感器
        air_quality_types = ["co2", "formaldehyde", "pm25", "pm10"]
        air_sensors = [
            s for s in sensors
            if isinstance(s, dict) and s.get("__template_key") in air_quality_types
        ]

        if not air_sensors:
            # 尝试从所有传感器中查找
            all_sensors = await self.ha_client.get_all_sensors()
            air_keywords = ["co2", "carbon_dioxide", "formaldehyde", "pm25", "pm10", "pm2.5", "pm1"]
            air_sensors = [
                {"entity_id": s["entity_id"], "name": s.get("attributes", {}).get("friendly_name", s["entity_id"])}
                for s in all_sensors
                if any(kw in s["entity_id"].lower() for kw in air_keywords)
            ]

        if not air_sensors:
            return "未找到空气质量传感器"

        results = ["🌬️ 空气质量："]
        for sensor in air_sensors:
            entity_id = sensor.get("entity_id")
            if not entity_id:
                continue
            state = await self.ha_client.get_sensor_state(entity_id)
            if state:
                value = state.get("state", "N/A")
                if value in ["unavailable", "unknown"]:
                    continue
                attributes = state.get("attributes", {})
                unit = attributes.get("unit_of_measurement", "")
                name = sensor.get("name", entity_id)
                results.append(f"  {name}: {value}{unit}")

        return "\n".join(results) if len(results) > 1 else "获取空气质量数据失败"

    async def _handle_device_query(self, event: AstrMessageEvent) -> str:
        """
        处理设备状态查询

        Args:
            event: 消息事件

        Returns:
            设备状态信息
        """
        if not self.ha_client:
            return "HomeAssistant 未配置"

        switches = self.config.get("switches", [])
        if not switches:
            return "暂未配置任何设备，请在插件设置中添加"

        results = ["🔌 设备状态："]
        for device in switches:
            if not isinstance(device, dict):
                continue

            entity_id = device.get("entity_id")
            if not entity_id:
                continue

            state = await self.ha_client.get_entity_state(entity_id)
            if state:
                device_state = state.get("state", "unknown")
                name = device.get("name", entity_id)
                device_type = device.get("__template_key", "generic")

                # 状态映射
                state_map = {
                    "on": "✅ 开启",
                    "off": "❌ 关闭",
                    "cool": "❄️ 制冷",
                    "heat": "🔥 制热",
                    "auto": "🔄 自动",
                    "idle": "💤 待机",
                    "unavailable": "⚠️ 不可用",
                }
                state_text = state_map.get(device_state, device_state)
                results.append(f"  {name} ({device_type}): {state_text}")

        return "\n".join(results) if len(results) > 1 else "获取设备状态失败"

    async def _handle_device_control(self, device_name: str, action: str) -> str:
        """
        处理设备控制

        Args:
            device_name: 设备名称
            action: 操作 (on/off)

        Returns:
            操作结果
        """
        if not self.ha_client:
            return "HomeAssistant 未配置"

        switches = self.config.get("switches", [])
        if not switches:
            return "暂未配置任何设备"

        # 查找匹配的设备
        matched_device = None
        for device in switches:
            if not isinstance(device, dict):
                continue
            name = device.get("name", "")
            entity_id = device.get("entity_id", "")
            # 模糊匹配设备名
            if device_name in name or name in device_name or device_name.lower() in entity_id.lower():
                matched_device = device
                break

        if not matched_device:
            return f"未找到设备「{device_name}」，请检查设备名称"

        entity_id = matched_device.get("entity_id")
        name = matched_device.get("name", entity_id)

        # 执行操作
        if action == "on":
            success = await self.ha_client.turn_on(entity_id)
            if success:
                return f"✅ 已打开 {name}"
            else:
                return f"❌ 打开 {name} 失败"
        else:
            success = await self.ha_client.turn_off(entity_id)
            if success:
                return f"✅ 已关闭 {name}"
            else:
                return f"❌ 关闭 {name} 失败"

    # ==================== 空调控制 ====================

    async def _handle_ac_status(self, event: AstrMessageEvent) -> str:
        """
        获取空调状态

        Args:
            event: 消息事件

        Returns:
            空调状态信息
        """
        if not self.ha_client:
            return "HomeAssistant 未配置"

        switches = self.config.get("switches", [])
        ac_devices = [
            d for d in switches
            if isinstance(d, dict) and d.get("__template_key") == "ac"
        ]

        if not ac_devices:
            return "暂未配置空调设备"

        results = []
        for device in ac_devices:
            entity_id = device.get("entity_id")
            if not entity_id:
                continue

            state = await self.ha_client.get_climate_state(entity_id)
            if state:
                results.append(self.ha_client.format_climate_state(state))

        return "\n\n".join(results) if results else "获取空调状态失败"

    async def _handle_ac_command(self, event: AstrMessageEvent, command: str) -> str:
        """
        处理空调控制命令

        Args:
            event: 消息事件
            command: 控制命令

        Returns:
            操作结果
        """
        if not self.ha_client:
            return "HomeAssistant 未配置"

        switches = self.config.get("switches", [])
        ac_devices = [
            d for d in switches
            if isinstance(d, dict) and d.get("__template_key") == "ac"
        ]

        if not ac_devices:
            return "暂未配置空调设备"

        # 获取第一个空调设备
        ac_device = ac_devices[0]
        entity_id = ac_device.get("entity_id")
        name = ac_device.get("name", "空调")

        # 解析命令
        command = command.strip().lower()

        # 模式命令
        mode_map = {
            "自动": "auto", "auto": "auto",
            "制热": "heat", "热": "heat",
            "制冷": "cool", "冷": "cool",
            "除湿": "dry", "干": "dry",
            "送风": "fan_only", "风": "fan_only",
            "关闭": "off", "关": "off",
        }

        # 风速命令
        fan_map = {
            "自动风": "Auto", "自动风速": "Auto",
            "低风": "Low", "低速": "Low", "低": "Low",
            "中风": "Medium", "中速": "Medium", "中": "Medium",
            "高风": "High", "高速": "High", "高": "High",
        }

        # 摆动命令
        swing_map = {
            "摆动开": "on", "开启摆动": "on", "摆动": "on",
            "摆动关": "off", "关闭摆动": "off",
        }

        # 检查模式命令
        for key, mode in mode_map.items():
            if key in command:
                success = await self.ha_client.set_climate_mode(entity_id, mode)
                if success:
                    return f"✅ {name} 已设置为{key}模式"
                return f"❌ 设置{key}模式失败"

        # 检查风速命令
        for key, fan_mode in fan_map.items():
            if key in command:
                success = await self.ha_client.set_climate_fan_mode(entity_id, fan_mode)
                if success:
                    return f"✅ {name} 风速已设置为{fan_mode}"
                return f"❌ 设置风速失败"

        # 检查摆动命令
        for key, swing_mode in swing_map.items():
            if key in command:
                success = await self.ha_client.set_climate_swing_mode(entity_id, swing_mode)
                if success:
                    return f"✅ {name} 摆动模式已{key}"
                return f"❌ 设置摆动模式失败"

        return f"未识别的命令：{command}\n可用命令：自动/制热/制冷/除湿/送风/关闭、低/中/高风速、摆动开/关"

    async def _handle_ac_set_temperature(self, event: AstrMessageEvent, temp: int) -> str:
        """
        设置空调温度

        Args:
            event: 消息事件
            temp: 目标温度

        Returns:
            操作结果
        """
        if not self.ha_client:
            return "HomeAssistant 未配置"

        switches = self.config.get("switches", [])
        ac_devices = [
            d for d in switches
            if isinstance(d, dict) and d.get("__template_key") == "ac"
        ]

        if not ac_devices:
            return "暂未配置空调设备"

        ac_device = ac_devices[0]
        entity_id = ac_device.get("entity_id")
        name = ac_device.get("name", "空调")
        min_temp = ac_device.get("min_temp", 16)
        max_temp = ac_device.get("max_temp", 30)

        # 验证温度范围
        if temp < min_temp or temp > max_temp:
            return f"温度必须在 {min_temp}°C 到 {max_temp}°C 之间"

        success = await self.ha_client.set_climate_temperature(entity_id, temp)
        if success:
            return f"✅ {name} 温度已设置为 {temp}°C"
        return f"❌ 设置温度失败"

    # ==================== 插件生命周期 ====================

    async def terminate(self):
        """插件终止时清理资源"""
        self.scheduler_mgr.shutdown()
        logger.info("智能家居助手插件已停止")
