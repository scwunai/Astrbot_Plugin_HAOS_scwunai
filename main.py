"""
智能家居助手插件

通过 /ha 指令使用自然语言控制智能家居设备
"""

import logging
from typing import Optional
import aiohttp

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from apscheduler.schedulers.asyncio import AsyncIOScheduler

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
        "temperature_query": ["温度", "多少度", "气温", "室内温度", "现在温度"],
        "humidity_query": ["湿度", "多少湿度", "室内湿度", "现在湿度"],
        "monitor_start": ["监控温度", "监测温度", "盯着温度", "温度监控", "启动监控"],
        "monitor_stop": ["停止监控", "关闭监控", "别监控", "取消监控"],
        "device_on": ["打开", "开启", "启动", "开灯", "开空调"],
        "device_off": ["关闭", "关掉", "停止", "关灯", "关空调"],
        "weather_query": ["天气", "天气预报", "今天天气", "明天天气"],
        "help": ["帮助", "怎么用", "功能"],
    }

    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

        # HomeAssistant 配置
        self.ha_url = config.get("home_assistant_url", "")
        self.ha_token = config.get("token", "")
        self.temp_sensor_id = config.get("temperature_sensor_id", "")
        self.humidity_sensor_id = config.get("humidity_sensor_id", "")

        # 监控配置
        self.low_threshold = config.get("low_threshold", 10)
        self.high_threshold = config.get("high_threshold", 30)
        self.check_interval = config.get("check_interval", 10)

        # 设备配置
        self.switches = config.get("switches", [])

        # 调度器
        self.scheduler = AsyncIOScheduler()
        self._monitor_jobs = {}  # 存储监控任务

    # ==================== 基础指令 ====================

    @filter.command("get_temperature")
    async def get_temperature(self, event: AstrMessageEvent):
        """获取温度数据"""
        temp = await self._get_sensor_state(self.temp_sensor_id)
        if temp is not None:
            yield event.plain_result(f"🌡️ 当前温度: {temp}°C")
        else:
            yield event.plain_result("获取温度失败，请检查配置")

    @filter.command("get_humidity")
    async def get_humidity(self, event: AstrMessageEvent):
        """获取湿度数据"""
        humidity = await self._get_sensor_state(self.humidity_sensor_id)
        if humidity is not None:
            yield event.plain_result(f"💧 当前湿度: {humidity}%")
        else:
            yield event.plain_result("获取湿度失败，请检查配置")

    @filter.command("monitor_temp")
    async def monitor_temperature(self, event: AstrMessageEvent):
        """启动温度监控"""
        umo = event.unified_msg_origin

        async def check_and_alert():
            temp = await self._get_sensor_state_async(self.temp_sensor_id)
            if temp is not None:
                if temp < self.low_threshold:
                    msg = f"⚠️ 温度过低: {temp}°C (低于 {self.low_threshold}°C)"
                elif temp > self.high_threshold:
                    msg = f"⚠️ 温度过高: {temp}°C (高于 {self.high_threshold}°C)"
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

    @filter.command("haoshelp")
    async def help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """🏠 智能家居助手

📋 基础指令:
/get_temperature - 获取温度
/get_humidity - 获取湿度
/monitor_temp - 启动温度监控
/stop_monitor - 停止监控

🤖 智能助手:
/ha <自然语言> - 智能控制

示例:
/ha 现在温度多少
/ha 打开客厅灯
/ha 启动温度监控
/ha 今天天气怎么样"""
        yield event.plain_result(help_text)

    # ==================== 智能助手入口 ====================

    @filter.command("ha")
    async def smart_assistant(self, event: AstrMessageEvent):
        """
        智能家居助手入口

        用法: /ha <自然语言指令>
        """
        message = event.get_message_str().strip()
        parts = message.split(maxsplit=1)

        if len(parts) < 2:
            yield event.plain_result("请输入指令，例如：/ha 现在温度多少")
            return

        user_query = parts[1].strip()

        # 解析意图
        intents = self._parse_intents(user_query)

        if not intents:
            # 使用 LLM 进行意图识别
            intents = await self._llm_parse_intents(event, user_query)

        if not intents:
            yield event.plain_result("抱歉，我没有理解您的指令")
            return

        # 执行意图
        results = await self._execute_intents(event, intents, user_query)

        # LLM 润色回复
        response = await self._polish_response(event, user_query, results)
        yield event.plain_result(response)

    def _parse_intents(self, text: str) -> list[dict]:
        """
        基于关键词解析意图

        Args:
            text: 用户输入

        Returns:
            意图列表
        """
        intents = []
        text_lower = text.lower()

        for intent, keywords in self.INTENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    intents.append({
                        "intent": intent,
                        "keyword": keyword
                    })
                    break

        return intents

    async def _llm_parse_intents(self, event: AstrMessageEvent, user_query: str) -> list[dict]:
        """
        使用 LLM 解析意图

        Args:
            event: 消息事件
            user_query: 用户查询

        Returns:
            意图列表
        """
        try:
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)

            if not provider_id:
                return []

            system_prompt = """你是智能家居意图识别器。根据用户输入，输出对应的意图标记。

可用意图标记:
[温度查询] - 查询温度
[湿度查询] - 查询湿度
[启动监控] - 启动温度监控
[停止监控] - 停止温度监控
[打开设备:设备名] - 打开设备
[关闭设备:设备名] - 关闭设备
[天气查询] - 查询天气
[帮助] - 显示帮助

规则:
1. 只输出意图标记，不要解释
2. 多个意图分行输出
3. 无法识别则输出 [未知]

示例:
用户: 现在多少度 → [温度查询]
用户: 打开客厅灯 → [打开设备:客厅灯]
用户: 温度和湿度都告诉我 → [温度查询]
[湿度查询]"""

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
            "monitor_start": r"\[启动监控\]",
            "monitor_stop": r"\[停止监控\]",
            "device_on": r"\[打开设备[:：]?(.+?)\]",
            "device_off": r"\[关闭设备[:：]?(.+?)\]",
            "weather_query": r"\[天气查询\]",
            "help": r"\[帮助\]",
        }

        for intent, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                intent_item = {"intent": intent}
                if intent in ("device_on", "device_off"):
                    intent_item["device"] = match.group(1).strip()
                intents.append(intent_item)

        return intents

    async def _execute_intents(
        self,
        event: AstrMessageEvent,
        intents: list[dict],
        user_query: str
    ) -> dict:
        """
        执行意图

        Args:
            event: 消息事件
            intents: 意图列表
            user_query: 原始查询

        Returns:
            执行结果
        """
        results = {
            "data": {},
            "actions": [],
            "errors": []
        }

        for intent_item in intents:
            intent = intent_item["intent"]

            try:
                if intent == "temperature_query":
                    temp = await self._get_sensor_state(self.temp_sensor_id)
                    if temp is not None:
                        results["data"]["temperature"] = f"{temp}°C"
                    else:
                        results["errors"].append("获取温度失败")

                elif intent == "humidity_query":
                    humidity = await self._get_sensor_state(self.humidity_sensor_id)
                    if humidity is not None:
                        results["data"]["humidity"] = f"{humidity}%"
                    else:
                        results["errors"].append("获取湿度失败")

                elif intent == "monitor_start":
                    results["actions"].append("已启动温度监控")

                elif intent == "monitor_stop":
                    results["actions"].append("已停止温度监控")

                elif intent == "device_on":
                    device = intent_item.get("device", "")
                    success = await self._control_device(device, "on")
                    if success:
                        results["actions"].append(f"已打开 {device}")
                    else:
                        results["errors"].append(f"打开 {device} 失败")

                elif intent == "device_off":
                    device = intent_item.get("device", "")
                    success = await self._control_device(device, "off")
                    if success:
                        results["actions"].append(f"已关闭 {device}")
                    else:
                        results["errors"].append(f"关闭 {device} 失败")

                elif intent == "weather_query":
                    weather = await self._get_weather()
                    if weather:
                        results["data"]["weather"] = weather
                    else:
                        results["errors"].append("获取天气失败")

                elif intent == "help":
                    results["data"]["help"] = "已显示帮助"

            except Exception as e:
                logger.error(f"执行意图 {intent} 失败: {e}")
                results["errors"].append(f"执行失败: {str(e)}")

        return results

    async def _polish_response(
        self,
        event: AstrMessageEvent,
        user_query: str,
        results: dict
    ) -> str:
        """
        使用 LLM 润色回复

        Args:
            event: 消息事件
            user_query: 用户查询
            results: 执行结果

        Returns:
            润色后的回复
        """
        # 如果结果简单，直接返回
        if not results["data"] and len(results["actions"]) <= 1 and not results["errors"]:
            if results["actions"]:
                return results["actions"][0]
            elif results["errors"]:
                return results["errors"][0]
            return "操作完成"

        # 构建上下文
        context_parts = []
        if results["data"]:
            for key, value in results["data"].items():
                context_parts.append(f"【{key}】{value}")
        if results["actions"]:
            context_parts.append(f"【操作】{', '.join(results['actions'])}")
        if results["errors"]:
            context_parts.append(f"【问题】{', '.join(results['errors'])}")

        context_str = "\n".join(context_parts)

        # 尝试使用 LLM 润色
        try:
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)

            if provider_id:
                prompt = f"""用户问: {user_query}

我已获取以下信息:
{context_str}

请用自然、友好的语言回复用户，简洁明了。不要提及技术细节。"""

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
            for key, value in results["data"].items():
                response_parts.append(f"{key}: {value}")
        if results["actions"]:
            response_parts.extend(results["actions"])
        if results["errors"]:
            response_parts.extend(results["errors"])

        return "\n".join(response_parts)

    # ==================== HomeAssistant API ====================

    async def _get_sensor_state(self, entity_id: str) -> Optional[str]:
        """获取传感器状态"""
        if not self.ha_url or not self.ha_token or not entity_id:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.ha_token}",
                    "Content-Type": "application/json"
                }
                url = f"{self.ha_url}/api/states/{entity_id}"
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("state")
        except Exception as e:
            logger.error(f"获取传感器状态失败: {e}")

        return None

    async def _get_sensor_state_async(self, entity_id: str) -> Optional[float]:
        """获取传感器数值"""
        state = await self._get_sensor_state(entity_id)
        if state:
            try:
                return float(state)
            except ValueError:
                pass
        return None

    async def _control_device(self, device_name: str, action: str) -> bool:
        """控制设备"""
        if not self.ha_url or not self.ha_token:
            return False

        # 查找设备
        entity_id = None
        for switch in self.switches:
            if isinstance(switch, dict):
                if device_name in switch.get("name", "") or device_name in switch.get("entity_id", ""):
                    entity_id = switch.get("entity_id")
                    break

        if not entity_id:
            # 尝试直接使用 device_name 作为 entity_id
            entity_id = f"switch.{device_name}"

        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {self.ha_token}",
                    "Content-Type": "application/json"
                }
                service = "turn_on" if action == "on" else "turn_off"
                url = f"{self.ha_url}/api/services/switch/{service}"
                data = {"entity_id": entity_id}

                async with session.post(url, headers=headers, json=data, timeout=10) as resp:
                    return resp.status == 200

        except Exception as e:
            logger.error(f"控制设备失败: {e}")

        return False

    async def _get_weather(self) -> Optional[str]:
        """获取天气信息"""
        # 如果配置了天气传感器
        weather_sensor = self.config.get("weather_sensor_id", "")
        if weather_sensor:
            state = await self._get_sensor_state(weather_sensor)
            if state:
                return f"当前天气: {state}"

        # 返回默认提示
        return "天气功能需要配置天气传感器"
