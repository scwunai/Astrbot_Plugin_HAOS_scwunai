"""
HomeAssistant API 模块

封装 HomeAssistant REST API 的异步调用
"""

import aiohttp
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class HomeAssistantClient:
    """HomeAssistant API 异步客户端"""

    def __init__(self, base_url: str, token: str, timeout: int = 10):
        """
        初始化 HomeAssistant 客户端

        Args:
            base_url: HomeAssistant 地址
            token: 长效访问令牌
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def get_sensor_state(self, entity_id: str) -> Optional[dict]:
        """
        获取传感器状态

        Args:
            entity_id: 传感器实体 ID

        Returns:
            传感器状态字典，失败返回 None
        """
        url = f"{self.base_url}/api/states/{entity_id}"
        try:
            async with aiohttp.ClientSession(
                timeout=self.timeout, headers=self._headers
            ) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    logger.warning(
                        f"获取传感器状态失败: entity_id={entity_id}, status={response.status}"
                    )
                    return None
        except aiohttp.ClientError as e:
            logger.error(f"HomeAssistant API 请求失败: {e}")
            return None
        except Exception as e:
            logger.error(f"HomeAssistant API 未知错误: {e}")
            return None

    async def get_sensor_value(self, entity_id: str) -> Optional[float]:
        """
        获取传感器数值

        Args:
            entity_id: 传感器实体 ID

        Returns:
            传感器数值，失败或非数值返回 None
        """
        state = await self.get_sensor_state(entity_id)
        if state:
            try:
                return float(state.get("state", 0))
            except (ValueError, TypeError):
                return None
        return None

    async def get_all_sensors(self) -> list:
        """
        获取所有传感器列表

        Returns:
            传感器列表
        """
        url = f"{self.base_url}/api/states"
        try:
            async with aiohttp.ClientSession(
                timeout=self.timeout, headers=self._headers
            ) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        states = await response.json()
                        # 过滤出传感器实体
                        return [
                            s
                            for s in states
                            if s.get("entity_id", "").startswith("sensor.")
                        ]
                    logger.warning(f"获取传感器列表失败: status={response.status}")
                    return []
        except aiohttp.ClientError as e:
            logger.error(f"HomeAssistant API 请求失败: {e}")
            return []
        except Exception as e:
            logger.error(f"HomeAssistant API 未知错误: {e}")
            return []

    async def check_sensor_available(self, entity_id: str) -> bool:
        """
        检查传感器是否可用

        Args:
            entity_id: 传感器实体 ID

        Returns:
            是否可用
        """
        state = await self.get_sensor_state(entity_id)
        if state:
            # 检查状态是否为 unavailable 或 unknown
            return state.get("state") not in ["unavailable", "unknown", None]
        return False

    async def get_sensor_attributes(self, entity_id: str) -> dict:
        """
        获取传感器属性

        Args:
            entity_id: 传感器实体 ID

        Returns:
            属性字典
        """
        state = await self.get_sensor_state(entity_id)
        if state:
            return state.get("attributes", {})
        return {}

    async def call_service(
        self, domain: str, service: str, entity_id: str = None, data: dict = None
    ) -> bool:
        """
        调用 HomeAssistant 服务

        Args:
            domain: 服务域
            service: 服务名
            entity_id: 目标实体 ID
            data: 服务数据

        Returns:
            是否调用成功
        """
        url = f"{self.base_url}/api/services/{domain}/{service}"
        payload = data or {}
        if entity_id:
            payload["entity_id"] = entity_id

        try:
            async with aiohttp.ClientSession(
                timeout=self.timeout, headers=self._headers
            ) as session:
                async with session.post(url, json=payload) as response:
                    return response.status == 200
        except aiohttp.ClientError as e:
            logger.error(f"调用服务失败: {e}")
            return False
        except Exception as e:
            logger.error(f"调用服务未知错误: {e}")
            return False

    def format_sensor_state(self, state: dict) -> str:
        """
        格式化传感器状态文本

        Args:
            state: 传感器状态字典

        Returns:
            格式化的状态文本
        """
        if not state:
            return "获取传感器状态失败"

        entity_id = state.get("entity_id", "unknown")
        value = state.get("state", "N/A")
        attributes = state.get("attributes", {})
        unit = attributes.get("unit_of_measurement", "")
        friendly_name = attributes.get("friendly_name", entity_id)

        return f"{friendly_name}: {value}{unit}"

    # ==================== 开关设备控制 ====================

    async def get_entity_state(self, entity_id: str) -> Optional[dict]:
        """
        获取任意实体状态（通用方法）

        Args:
            entity_id: 实体 ID

        Returns:
            实体状态字典，失败返回 None
        """
        url = f"{self.base_url}/api/states/{entity_id}"
        try:
            async with aiohttp.ClientSession(
                timeout=self.timeout, headers=self._headers
            ) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            logger.error(f"获取实体状态失败: {e}")
            return None

    async def get_switch_state(self, entity_id: str) -> Optional[str]:
        """
        获取开关状态

        Args:
            entity_id: 开关实体 ID

        Returns:
            状态字符串 (on/off)，失败返回 None
        """
        state = await self.get_entity_state(entity_id)
        if state:
            return state.get("state")
        return None

    async def turn_on(self, entity_id: str) -> bool:
        """
        开启设备

        Args:
            entity_id: 实体 ID

        Returns:
            是否成功
        """
        # 根据实体类型选择服务
        domain = entity_id.split(".")[0]
        service_map = {
            "light": "turn_on",
            "switch": "turn_on",
            "fan": "turn_on",
            "climate": "turn_on",
            "humidifier": "turn_on",
            "media_player": "turn_on",
            "cover": "open_cover",
        }
        service = service_map.get(domain, "turn_on")
        return await self.call_service(domain, service, entity_id)

    async def turn_off(self, entity_id: str) -> bool:
        """
        关闭设备

        Args:
            entity_id: 实体 ID

        Returns:
            是否成功
        """
        domain = entity_id.split(".")[0]
        service_map = {
            "light": "turn_off",
            "switch": "turn_off",
            "fan": "turn_off",
            "climate": "turn_off",
            "humidifier": "turn_off",
            "media_player": "turn_off",
            "cover": "close_cover",
        }
        service = service_map.get(domain, "turn_off")
        return await self.call_service(domain, service, entity_id)

    async def toggle(self, entity_id: str) -> bool:
        """
        切换设备状态

        Args:
            entity_id: 实体 ID

        Returns:
            是否成功
        """
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "toggle", entity_id)

    async def get_all_switches(self) -> list:
        """
        获取所有开关设备

        Returns:
            开关设备列表
        """
        url = f"{self.base_url}/api/states"
        try:
            async with aiohttp.ClientSession(
                timeout=self.timeout, headers=self._headers
            ) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        states = await response.json()
                        # 过滤出开关类实体
                        switch_domains = ("light.", "switch.", "fan.", "climate.", "humidifier.", "cover.")
                        return [
                            s for s in states
                            if any(s.get("entity_id", "").startswith(d) for d in switch_domains)
                        ]
                    return []
        except Exception as e:
            logger.error(f"获取开关列表失败: {e}")
            return []

    async def get_all_lights(self) -> list:
        """获取所有灯光设备"""
        url = f"{self.base_url}/api/states"
        try:
            async with aiohttp.ClientSession(
                timeout=self.timeout, headers=self._headers
            ) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        states = await response.json()
                        return [s for s in states if s.get("entity_id", "").startswith("light.")]
                    return []
        except Exception as e:
            logger.error(f"获取灯光列表失败: {e}")
            return []

    def format_switch_state(self, state: dict) -> str:
        """
        格式化开关状态文本

        Args:
            state: 开关状态字典

        Returns:
            格式化的状态文本
        """
        if not state:
            return "获取设备状态失败"

        entity_id = state.get("entity_id", "unknown")
        switch_state = state.get("state", "unknown")
        attributes = state.get("attributes", {})
        friendly_name = attributes.get("friendly_name", entity_id)

        # 状态映射
        state_map = {
            "on": "开启",
            "off": "关闭",
            "open": "打开",
            "opening": "正在打开",
            "closed": "关闭",
            "closing": "正在关闭",
            "cool": "制冷",
            "heat": "制热",
            "auto": "自动",
            "idle": "待机",
            "unavailable": "不可用",
        }
        state_text = state_map.get(switch_state, switch_state)

        return f"{friendly_name}: {state_text}"

    async def set_climate_temperature(self, entity_id: str, temperature: float) -> bool:
        """
        设置空调温度

        Args:
            entity_id: 空调实体 ID
            temperature: 目标温度

        Returns:
            是否成功
        """
        return await self.call_service(
            "climate", "set_temperature", entity_id, {"temperature": temperature}
        )

    async def set_fan_speed(self, entity_id: str, speed: str) -> bool:
        """
        设置风扇速度

        Args:
            entity_id: 风扇实体 ID
            speed: 速度 (low/medium/high)

        Returns:
            是否成功
        """
        return await self.call_service(
            "fan", "set_speed", entity_id, {"speed": speed}
        )

    async def set_light_brightness(self, entity_id: str, brightness: int) -> bool:
        """
        设置灯光亮度

        Args:
            entity_id: 灯光实体 ID
            brightness: 亮度 (0-255)

        Returns:
            是否成功
        """
        return await self.call_service(
            "light", "turn_on", entity_id, {"brightness": brightness}
        )

    # ==================== Cover control ====================

    async def open_cover(self, entity_id: str) -> bool:
        """Open a cover entity."""
        return await self.call_service("cover", "open_cover", entity_id)

    async def close_cover(self, entity_id: str) -> bool:
        """Close a cover entity."""
        return await self.call_service("cover", "close_cover", entity_id)

    async def stop_cover(self, entity_id: str) -> bool:
        """Stop a cover entity."""
        return await self.call_service("cover", "stop_cover", entity_id)

    async def set_cover_position(self, entity_id: str, position: int) -> bool:
        """Set cover position from 0 to 100."""
        if position < 0 or position > 100:
            logger.warning(f"Cover position out of range: {position}")
            return False
        return await self.call_service(
            "cover", "set_cover_position", entity_id, {"position": position}
        )

    # ==================== 空调控制 ====================

    async def set_climate_mode(self, entity_id: str, mode: str) -> bool:
        """
        设置空调模式

        Args:
            entity_id: 空调实体 ID
            mode: 模式 (auto/heat/cool/dry/fan_only/off)

        Returns:
            是否成功
        """
        # 模式映射
        mode_map = {
            "自动": "auto",
            "auto": "auto",
            "制热": "heat",
            "heat": "heat",
            "制冷": "cool",
            "cool": "cool",
            "除湿": "dry",
            "dry": "dry",
            "仅送风": "fan_only",
            "送风": "fan_only",
            "fan_only": "fan_only",
            "关闭": "off",
            "off": "off",
        }
        ha_mode = mode_map.get(mode.lower(), mode.lower())
        return await self.call_service(
            "climate", "set_hvac_mode", entity_id, {"hvac_mode": ha_mode}
        )

    async def set_climate_fan_mode(self, entity_id: str, fan_mode: str) -> bool:
        """
        设置空调风速

        Args:
            entity_id: 空调实体 ID
            fan_mode: 风速 (Auto/Low/Medium/High)

        Returns:
            是否成功
        """
        # 风速映射
        fan_map = {
            "自动": "Auto",
            "auto": "Auto",
            "低": "Low",
            "low": "Low",
            "中": "Medium",
            "medium": "Medium",
            "高": "High",
            "high": "High",
        }
        ha_fan_mode = fan_map.get(fan_mode.lower(), fan_mode)
        return await self.call_service(
            "climate", "set_fan_mode", entity_id, {"fan_mode": ha_fan_mode}
        )

    async def set_climate_swing_mode(self, entity_id: str, swing_mode: str) -> bool:
        """
        设置空调摆动模式

        Args:
            entity_id: 空调实体 ID
            swing_mode: 摆动模式 (on/off)

        Returns:
            是否成功
        """
        # 摆动模式映射
        swing_map = {
            "开启": "on",
            "开": "on",
            "on": "on",
            "关闭": "off",
            "关": "off",
            "off": "off",
        }
        ha_swing_mode = swing_map.get(swing_mode.lower(), swing_mode.lower())
        return await self.call_service(
            "climate", "set_swing_mode", entity_id, {"swing_mode": ha_swing_mode}
        )

    async def get_climate_state(self, entity_id: str) -> Optional[dict]:
        """
        获取空调完整状态

        Args:
            entity_id: 空调实体 ID

        Returns:
            空调状态字典
        """
        state = await self.get_entity_state(entity_id)
        if not state:
            return None

        attributes = state.get("attributes", {})
        return {
            "state": state.get("state"),
            "temperature": attributes.get("temperature"),
            "current_temperature": attributes.get("current_temperature"),
            "hvac_mode": attributes.get("hvac_mode"),
            "fan_mode": attributes.get("fan_mode"),
            "swing_mode": attributes.get("swing_mode"),
            "min_temp": attributes.get("min_temp", 16),
            "max_temp": attributes.get("max_temp", 30),
            "friendly_name": attributes.get("friendly_name", entity_id),
        }

    def format_climate_state(self, climate_state: dict) -> str:
        """
        格式化空调状态文本

        Args:
            climate_state: 空调状态字典

        Returns:
            格式化的状态文本
        """
        if not climate_state:
            return "获取空调状态失败"

        # 模式映射
        mode_map = {
            "auto": "自动",
            "heat": "制热",
            "cool": "制冷",
            "dry": "除湿",
            "fan_only": "送风",
            "off": "关闭",
        }

        name = climate_state.get("friendly_name", "空调")
        hvac_mode = climate_state.get("hvac_mode", "unknown")
        mode_text = mode_map.get(hvac_mode, hvac_mode)
        temperature = climate_state.get("temperature", "N/A")
        current_temp = climate_state.get("current_temperature", "N/A")
        fan_mode = climate_state.get("fan_mode", "N/A")
        swing_mode = climate_state.get("swing_mode", "N/A")

        lines = [f"❄️ {name} 状态："]
        lines.append(f"  模式: {mode_text}")
        if temperature:
            lines.append(f"  设定温度: {temperature}°C")
        if current_temp:
            lines.append(f"  当前温度: {current_temp}°C")
        if fan_mode:
            lines.append(f"  风速: {fan_mode}")
        if swing_mode:
            lines.append(f"  摆动: {swing_mode}")

        return "\n".join(lines)
