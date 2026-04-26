"""
LLM 处理模块

处理 LLM 对话、意图解析和响应生成
"""

import json
import logging
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.provider import ProviderRequest, LLMResponse
    from astrbot.core.persona_mgr import PersonaManager
    from main import SmartHomePlugin

logger = logging.getLogger(__name__)


class LLMHandler:
    """LLM 对话处理器"""

    # 意图关键词映射
    INTENT_KEYWORDS = {
        "weather_query": ["天气", "气温", "温度", "下雨", "晴天", "阴天", "刮风", "下雪"],
        "hourly_weather": ["小时后天气", "一小时后", "两小时后", "几小时后", "一会儿", "待会儿", "出门", "之后天气"],
        "set_location": ["设置位置", "我在", "我的位置", "定位", "所在城市"],
        "sensor_query": ["传感器", "温度传感器", "湿度传感器", "传感器状态"],
        "temperature_query": ["室内温度", "房间温度", "家里温度", "现在多少度"],
        "humidity_query": ["室内湿度", "房间湿度", "家里湿度", "湿度多少"],
        "air_quality": ["空气质量", "PM2.5", "PM10", "甲醛", "二氧化碳", "CO2", "空气"],
        "device_query": ["设备状态", "设备情况", "电器状态", "开关状态"],
        "curtain_control": ["打开窗帘", "开窗帘", "关闭窗帘", "关窗帘", "拉开窗帘", "拉上窗帘", "停止窗帘"],
        "curtain_position": ["窗帘位置", "窗帘开度", "窗帘开到", "窗帘调到"],
        "curtain_query": ["窗帘状态", "窗帘情况"],
        "turn_on": ["打开", "开启", "开灯", "开空调", "开风扇", "开电扇", "启动"],
        "turn_off": ["关闭", "关掉", "关灯", "关空调", "关风扇", "关电扇", "停止"],
        "ac_control": ["空调", "制热", "制冷", "除湿", "送风", "调温度"],
        "ac_temp": ["空调温度", "调到", "度"],
        "subscribe_weather": ["订阅天气", "每天天气", "天气推送", "天气提醒"],
        "unsubscribe_weather": ["取消天气", "退订天气", "不要天气推送"],
        "delayed_action": ["分钟后", "分钟后帮我", "秒后", "小时后帮我", "待会儿帮我", "一会儿帮我"],
        "help": ["帮助", "怎么用", "功能", "指令"],
    }

    def __init__(self, plugin: "SmartHomePlugin"):
        """
        初始化 LLM 处理器

        Args:
            plugin: 插件实例
        """
        self.plugin = plugin
        self.persona_manager: Optional["PersonaManager"] = None

    def set_persona_manager(self, persona_manager: "PersonaManager"):
        """
        设置人格管理器

        Args:
            persona_manager: AstrBot 人格管理器实例
        """
        self.persona_manager = persona_manager

    async def get_persona_prompt(
        self,
        umo: str = None,
        persona_name: str = None
    ) -> Optional[str]:
        """
        获取人格提示词

        Args:
            umo: 消息会话来源 ID，用于获取会话配置
            persona_name: 指定的人格名称，如果提供则优先使用

        Returns:
            人格提示词，如果未找到则返回 None
        """
        if not self.persona_manager:
            return None

        try:
            # 如果指定了人格名称，直接查找
            if persona_name:
                persona = next(
                    (p for p in self.persona_manager.personas_v3 if p["name"] == persona_name),
                    None
                )
                if persona:
                    return persona.get("prompt")
                # 尝试从数据库获取
                try:
                    db_persona = await self.persona_manager.get_persona(persona_name)
                    if db_persona:
                        return db_persona.system_prompt
                except ValueError:
                    pass
                logger.warning(f"未找到指定的人格: {persona_name}")
                return None

            # 否则获取默认人格
            default_persona = await self.persona_manager.get_default_persona_v3(umo)
            if default_persona and default_persona.get("name") != "default":
                return default_persona.get("prompt")

            return None
        except Exception as e:
            logger.error(f"获取人格提示词失败: {e}")
            return None

    def get_system_prompt(self) -> str:
        """
        获取系统提示词

        Returns:
            系统提示词
        """
        return """你是智能家居助手，可以帮助用户查询天气、监控传感器状态、控制家电设备。

当用户询问天气时，回复格式：[天气查询]
当用户询问几小时后的天气时，回复格式：[小时天气:小时数]（如：[小时天气:1] 表示1小时后）
当用户设置位置时，回复格式：[设置位置:城市名]
当用户查询传感器时，回复格式：[传感器查询]
当用户查询室内温度时，回复格式：[温度查询]
当用户查询室内湿度时，回复格式：[湿度查询]
当用户查询空气质量时，回复格式：[空气质量查询]
当用户查询设备状态时，回复格式：[设备状态查询]
当用户控制窗帘开关或停止时，回复格式：[窗帘控制:设备名:动作]（动作为：打开/关闭/停止）
当用户设置窗帘位置时，回复格式：[窗帘位置:设备名:百分比]（如：[窗帘位置:客厅窗帘:50]）
当用户查询窗帘状态时，回复格式：[窗帘状态查询:设备名]
当用户要打开设备时，回复格式：[打开设备:设备名]
当用户要关闭设备时，回复格式：[关闭设备:设备名]
当用户控制空调时，回复格式：[空调控制:命令]
当用户设置空调温度时，回复格式：[空调温度:温度值]
当用户订阅天气推送时，回复格式：[订阅天气]
当用户取消天气订阅时，回复格式：[取消天气订阅]
当用户要求延迟执行操作时，回复格式：[延迟执行:分钟数:操作]（如：[延迟执行:5:打开空调] 表示5分钟后打开空调）
当用户询问帮助时，回复格式：[帮助]

空调控制命令：自动/制热/制冷/除湿/送风/关闭、低/中/高风速、摆动开/关

**重要**：用户可能在一条消息中包含多个指令，请按顺序输出所有对应的意图标记，每个标记独占一行。

其他问题正常回答。

示例：
用户：今天天气怎么样 → [天气查询]
用户：一个小时后天气怎么样 → [小时天气:1]
用户：两小时后我要出门，天气如何 → [小时天气:2]
用户：我在北京 → [设置位置:北京]
用户：室内温度多少 → [温度查询]
用户：空气质量怎么样 → [空气质量查询]
用户：打开客厅灯 → [打开设备:客厅灯]
用户：关闭空调 → [关闭设备:空调]
用户：打开客厅窗帘 → [窗帘控制:客厅窗帘:打开]
用户：客厅窗帘开到50% → [窗帘位置:客厅窗帘:50]
用户：停止卧室窗帘 → [窗帘控制:卧室窗帘:停止]
用户：客厅窗帘状态 → [窗帘状态查询:客厅窗帘]
用户：空调开制冷 → [空调控制:制冷]
用户：空调温度调到26度 → [空调温度:26]
用户：设备状态 → [设备状态查询]
用户：五分钟后帮我开空调 → [延迟执行:5:打开空调]
用户：10分钟后关灯 → [延迟执行:10:关闭灯]
用户：半小时后打开风扇 → [延迟执行:30:打开风扇]

**多指令示例**：
用户：打开空调，调成除湿模式，温度开到20度 →
[打开设备:空调]
[空调控制:除湿]
[空调温度:20]

用户：打开客厅灯和卧室灯 →
[打开设备:客厅灯]
[打开设备:卧室灯]"""

    def get_response_prompt(
        self,
        user_message: str,
        collected_data: dict,
        executed_actions: list[dict],
        persona_prompt: Optional[str] = None
    ) -> str:
        """
        生成用于 LLM 生成自然回复的提示词

        Args:
            user_message: 用户原始消息
            collected_data: 收集的数据（天气、传感器等）
            executed_actions: 已执行的操作列表
            persona_prompt: 人格提示词（可选）

        Returns:
            提示词
        """
        data_context = []

        if collected_data.get("weather"):
            weather = collected_data["weather"]
            data_context.append(f"【天气数据】\n{weather}")

        if collected_data.get("hourly_weather"):
            data_context.append(f"【分时天气】\n{collected_data['hourly_weather']}")

        if collected_data.get("temperature"):
            data_context.append(f"【室内温度】\n{collected_data['temperature']}")

        if collected_data.get("humidity"):
            data_context.append(f"【室内湿度】\n{collected_data['humidity']}")

        if collected_data.get("air_quality"):
            data_context.append(f"【空气质量】\n{collected_data['air_quality']}")

        if collected_data.get("sensors"):
            data_context.append(f"【传感器状态】\n{collected_data['sensors']}")

        if collected_data.get("devices"):
            data_context.append(f"【设备状态】\n{collected_data['devices']}")

        actions_context = []
        for action in executed_actions:
            action_type = action.get("type", "")
            action_detail = action.get("detail", "")
            success = action.get("success", True)
            status = "成功" if success else "失败"
            actions_context.append(f"- {action_type}: {action_detail} ({status})")

        # 构建人格提示部分
        persona_section = ""
        if persona_prompt:
            persona_section = f"""
【人格设定】
{persona_prompt}

请以上述人格设定回答用户的问题，保持人格的风格和语气。
"""

        prompt = f"""{persona_section}用户消息：{user_message}

我已为您收集了以下数据：
{chr(10).join(data_context) if data_context else '暂无相关数据'}

已执行的操作：
{chr(10).join(actions_context) if actions_context else '无操作'}

请根据以上信息，用自然、友好的语言回复用户。要求：
1. 回答用户的所有问题，不要遗漏
2. 如果用户问"穿什么"、"要不要加衣服"等，根据温度数据给出穿衣建议
3. 如果用户问"适合做什么"等分析类问题，结合数据给出建议
4. 如果执行了多个设备操作，请合并告知，例如"已为您打开灯和空调"
5. 回复要简洁、自然，不要机械地罗列数据
6. 如果有操作失败，请告知用户
7. 不要提及意图标记或技术细节"""

        return prompt

    def parse_intent(self, text: str) -> Optional[dict]:
        """
        解析用户意图

        Args:
            text: 用户输入文本

        Returns:
            意图信息字典，未识别返回 None
        """
        text = text.strip()

        # 检查关键词
        for intent, keywords in self.INTENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text:
                    result = {"intent": intent, "original_text": text}

                    # 提取城市名
                    if intent == "set_location":
                        location = self._extract_location(text)
                        if location:
                            result["location"] = location

                    return result

        return None

    def _extract_location(self, text: str) -> Optional[str]:
        """
        从文本中提取位置

        Args:
            text: 用户输入文本

        Returns:
            位置文本
        """
        # 常见模式
        patterns = [
            r"我在(.+?)(?:，|。|$)",
            r"我的位置是(.+?)(?:，|。|$)",
            r"设置位置[为是为：:\s]*(.+?)(?:，|。|$)",
            r"定位[为是为：:\s]*(.+?)(?:，|。|$)",
            r"(.+?)天气",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                location = match.group(1).strip()
                # 清理常见后缀
                location = re.sub(r"(市|省|区|县)$", "", location)
                return location

        return None

    async def generate_weather_summary(self, weather_data: dict, location: str) -> str:
        """
        生成天气摘要

        Args:
            weather_data: 天气数据
            location: 位置名称

        Returns:
            天气摘要文本
        """
        if not weather_data:
            return f"抱歉，无法获取 {location} 的天气信息。"

        parts = [f"📍 {location} 天气："]

        # 当前天气（API 直接在根级别返回）
        if weather_data.get("weather"):
            weather = weather_data.get("weather", "N/A")
            temperature = weather_data.get("temperature", "N/A")
            humidity = weather_data.get("humidity", "N/A")
            wind_direction = weather_data.get("wind_direction", "N/A")
            wind_power = weather_data.get("wind_power", "N/A")
            temp_max = weather_data.get("temp_max", "N/A")
            temp_min = weather_data.get("temp_min", "N/A")

            parts.append(f"🌡️ 当前：{weather}，{temperature}°C")
            parts.append(f"💧 湿度：{humidity}%")
            parts.append(f"🌬️ 风力：{wind_direction} {wind_power}")
            if temp_max and temp_min:
                parts.append(f"🌡️ 气温：{temp_min}~{temp_max}°C")

        # 未来预报
        forecast = weather_data.get("forecast", [])
        if forecast:
            parts.append("\n📅 未来天气：")
            for day in forecast[:3]:
                date = day.get("date", "")
                weather_day = day.get("weather_day", "")
                weather_night = day.get("weather_night", "")
                high = day.get("temp_max", "")
                low = day.get("temp_min", "")
                parts.append(f"{date}：{weather_day}/{weather_night} {low}~{high}°C")

        return "\n".join(parts)

    async def generate_sensor_summary(self, sensor_data: list) -> str:
        """
        生成传感器状态摘要

        Args:
            sensor_data: 传感器数据列表

        Returns:
            传感器摘要文本
        """
        if not sensor_data:
            return "暂无传感器数据"

        parts = ["📊 传感器状态："]
        for sensor in sensor_data:
            name = sensor.get("name", sensor.get("entity_id", "未知"))
            value = sensor.get("value", "N/A")
            unit = sensor.get("unit", "")
            status = sensor.get("status", "unknown")

            status_emoji = "✅" if status == "ok" else "⚠️"
            parts.append(f"{status_emoji} {name}：{value}{unit}")

        return "\n".join(parts)

    async def generate_alert_message(
        self, sensor_name: str, value: float, unit: str, issue: str
    ) -> str:
        """
        生成告警消息

        Args:
            sensor_name: 传感器名称
            value: 当前值
            unit: 单位
            issue: 问题类型

        Returns:
            告警消息
        """
        return f"⚠️ 传感器告警\n{sensor_name}：当前值 {value}{unit}，{issue}"

    async def generate_location_question(self) -> str:
        """
        生成询问用户位置的语句

        Returns:
            询问语句
        """
        return "请问您在哪个城市？设置位置后我可以为您提供天气服务。"

    async def generate_set_location_success(self, location: str) -> str:
        """
        生成位置设置成功消息

        Args:
            location: 位置名称

        Returns:
            成功消息
        """
        return f"✅ 已将您的位置设置为 {location}，现在可以查询天气了！"

    async def generate_set_location_failed(self, text: str) -> str:
        """
        生成位置设置失败消息

        Args:
            text: 用户输入的位置文本

        Returns:
            失败消息
        """
        return f"抱歉，无法识别「{text}」这个位置，请输入城市名称，如：北京、上海、广州。"

    async def generate_subscribe_success(self, service: str) -> str:
        """
        生成订阅成功消息

        Args:
            service: 服务名称

        Returns:
            成功消息
        """
        return f"✅ 已成功订阅{service}！"

    async def generate_unsubscribe_success(self, service: str) -> str:
        """
        生成取消订阅成功消息

        Args:
            service: 服务名称

        Returns:
            成功消息
        """
        return f"✅ 已取消{service}订阅。"

    async def generate_help_message(self) -> str:
        """
        生成帮助消息

        Returns:
            帮助消息
        """
        return """🏠 智能家居助手帮助

📍 位置设置：
• 设置位置：告诉我您在哪个城市
• 示例：「我在北京」「我的位置是上海」

🌤️ 天气查询：
• 查询天气：「今天天气怎么样」「北京天气」
• 订阅天气推送：「订阅天气」「每天提醒我天气」
• 取消订阅：「取消天气订阅」

📊 传感器监控：
• 查询传感器：「传感器状态」「室内温度」「湿度多少」
• 自动告警：传感器异常时会自动通知

💡 提示：
• 支持自然语言交互，直接说就行！
• 配置更多传感器请在插件设置中添加"""
