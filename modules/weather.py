"""
天气 API 模块

封装 uapis.cn 天气 API 的异步调用
"""

import aiohttp
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class WeatherAPI:
    """天气 API 异步客户端"""

    BASE_URL = "https://uapis.cn/api/v1/misc/weather"

    def __init__(self, timeout: int = 10):
        """
        初始化天气 API 客户端

        Args:
            timeout: 请求超时时间（秒）
        """
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def get_weather(
        self,
        adcode: str,
        extended: bool = True,
        forecast: bool = True,
        hourly: bool = True,
        indices: bool = True,
    ) -> dict:
        """
        获取完整天气信息

        Args:
            adcode: 行政区划代码
            extended: 是否包含扩展信息
            forecast: 是否包含天气预报
            hourly: 是否包含小时级预报
            indices: 是否包含生活指数

        Returns:
            天气数据字典
        """
        params = {"adcode": adcode}
        if extended:
            params["extended"] = "true"
        if forecast:
            params["forecast"] = "true"
        if hourly:
            params["hourly"] = "true"
        if indices:
            params["indices"] = "true"

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(self.BASE_URL, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        # API 直接返回天气数据，检查是否有 adcode 字段确认有效
                        if data and data.get("adcode"):
                            return data
                    logger.warning(f"天气 API 返回异常: status={response.status}")
                    return {}
        except aiohttp.ClientError as e:
            logger.error(f"天气 API 请求失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"天气 API 未知错误: {e}")
            return {}

    async def get_current_weather(self, adcode: str) -> Optional[dict]:
        """
        仅获取当前天气

        Args:
            adcode: 行政区划代码

        Returns:
            当前天气数据，失败返回 None
        """
        data = await self.get_weather(
            adcode, extended=False, forecast=False, hourly=False, indices=False
        )
        if data and "current" in data:
            return data["current"]
        return None

    async def get_forecast(self, adcode: str, days: int = 3) -> list:
        """
        获取天气预报

        Args:
            adcode: 行政区划代码
            days: 预报天数（1-7）

        Returns:
            预报数据列表
        """
        data = await self.get_weather(
            adcode, extended=False, forecast=True, hourly=False, indices=False
        )
        if data and "forecast" in data:
            return data["forecast"][:days]
        return []

    async def get_hourly_forecast(self, adcode: str, hours: int = 24) -> list:
        """
        获取小时级预报

        Args:
            adcode: 行政区划代码
            hours: 预报小时数

        Returns:
            小时级预报数据列表
        """
        data = await self.get_weather(
            adcode, extended=False, forecast=False, hourly=True, indices=False
        )
        if data and "hourly_forecast" in data:
            return data["hourly_forecast"][:hours]
        return []

    async def get_weather_at_hour(self, adcode: str, hours_later: int) -> Optional[dict]:
        """
        获取指定小时后的天气

        Args:
            adcode: 行政区划代码
            hours_later: 几小时后（1-24）

        Returns:
            指定时间点的天气数据，失败返回 None
        """
        if hours_later < 1 or hours_later > 24:
            return None

        hourly_data = await self.get_hourly_forecast(adcode, hours_later)
        if hourly_data and len(hourly_data) >= hours_later:
            return hourly_data[hours_later - 1]
        return None

    def format_hourly_weather(self, hourly_data: dict, hours_later: int) -> str:
        """
        格式化小时级天气摘要

        Args:
            hourly_data: 小时级天气数据
            hours_later: 几小时后

        Returns:
            格式化的天气摘要文本
        """
        if not hourly_data:
            return f"无法获取 {hours_later} 小时后的天气数据"

        time_str = hourly_data.get("time", "")
        temperature = hourly_data.get("temperature", "N/A")
        weather = hourly_data.get("weather", "N/A")
        wind_direction = hourly_data.get("wind_direction", "N/A")
        wind_scale = hourly_data.get("wind_scale", "N/A")
        humidity = hourly_data.get("humidity", "N/A")
        pop = hourly_data.get("pop")  # 降水概率

        parts = [f"⏰ {hours_later} 小时后（{time_str}）的天气："]
        parts.append(f"🌡️ 温度：{temperature}°C")
        parts.append(f"🌤️ 天气：{weather}")
        parts.append(f"🌬️ 风力：{wind_direction} {wind_scale}")
        parts.append(f"💧 湿度：{humidity}%")
        if pop is not None:
            parts.append(f"🌧️ 降水概率：{pop}%")

        return "\n".join(parts)

    async def get_indices(self, adcode: str) -> list:
        """
        获取生活指数

        Args:
            adcode: 行政区划代码

        Returns:
            生活指数列表
        """
        data = await self.get_weather(
            adcode, extended=False, forecast=False, hourly=False, indices=True
        )
        if data and "indices" in data:
            return data["indices"]
        return []

    def format_weather_summary(self, weather_data: dict) -> str:
        """
        格式化天气摘要

        Args:
            weather_data: 天气数据

        Returns:
            格式化的天气摘要文本
        """
        if not weather_data:
            return "获取天气数据失败"

        parts = []

        # 当前天气（API 直接在根级别返回当前天气信息）
        if weather_data.get("weather"):
            # 位置信息
            province = weather_data.get("province", "")
            city = weather_data.get("city", "")
            district = weather_data.get("district", "")
            location = f"{province}{city}{district}" if district else f"{province}{city}"
            if location:
                parts.append(f"📍 {location}")

            # 天气信息
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
        if "forecast" in weather_data and weather_data["forecast"]:
            parts.append("\n📅 未来天气：")
            for day in weather_data["forecast"][:3]:
                date = day.get("date", "")
                weather_day = day.get("weather_day", "N/A")
                weather_night = day.get("weather_night", "N/A")
                high = day.get("temp_max", "N/A")
                low = day.get("temp_min", "N/A")
                parts.append(f"{date}：{weather_day}/{weather_night} {low}~{high}°C")

        return "\n".join(parts) if parts else "获取天气数据失败"
