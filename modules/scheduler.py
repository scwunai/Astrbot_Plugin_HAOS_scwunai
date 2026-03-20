"""
定时任务模块

管理天气推送和传感器监控的定时任务
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from main import SmartHomePlugin

logger = logging.getLogger(__name__)


class SchedulerManager:
    """定时任务管理器"""

    def __init__(self, plugin: "SmartHomePlugin"):
        """
        初始化定时任务管理器

        Args:
            plugin: 插件实例
        """
        self.plugin = plugin
        self.scheduler = AsyncIOScheduler()
        self._weather_job_id = "weather_push"
        self._sensor_job_id = "sensor_monitor"

    def setup(self):
        """设置所有定时任务"""
        config = self.plugin.config

        # 天气推送任务
        if config.get("enable_weather_push", True):
            push_time = config.get("weather_push_time", "07:00")
            self.setup_daily_weather_push(push_time)

        # 传感器监控任务
        if config.get("enable_sensor_alert", True):
            interval = config.get("sensor_check_interval", 300)
            self.setup_sensor_monitor(interval)

        # 启动调度器
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("定时任务调度器已启动")

    def shutdown(self):
        """关闭调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("定时任务调度器已关闭")

    def setup_daily_weather_push(self, time_str: str):
        """
        设置每日天气推送任务

        Args:
            time_str: 推送时间，格式 HH:MM
        """
        try:
            hour, minute = map(int, time_str.split(":"))
            trigger = CronTrigger(hour=hour, minute=minute)

            # 移除旧任务
            if self.scheduler.get_job(self._weather_job_id):
                self.scheduler.remove_job(self._weather_job_id)

            # 添加新任务
            self.scheduler.add_job(
                self.send_weather_to_subscribers,
                trigger,
                id=self._weather_job_id,
                replace_existing=True,
            )
            logger.info(f"已设置天气推送任务: 每天 {time_str}")
        except Exception as e:
            logger.error(f"设置天气推送任务失败: {e}")

    def setup_sensor_monitor(self, interval: int):
        """
        设置传感器监控任务

        Args:
            interval: 检查间隔（秒）
        """
        try:
            # 移除旧任务
            if self.scheduler.get_job(self._sensor_job_id):
                self.scheduler.remove_job(self._sensor_job_id)

            # 添加新任务
            self.scheduler.add_job(
                self.check_sensors_and_alert,
                "interval",
                seconds=interval,
                id=self._sensor_job_id,
                replace_existing=True,
            )
            logger.info(f"已设置传感器监控任务: 每 {interval} 秒")
        except Exception as e:
            logger.error(f"设置传感器监控任务失败: {e}")

    async def send_weather_to_subscribers(self):
        """向订阅用户推送天气"""
        try:
            # 获取所有订阅天气推送的用户
            # 使用 KV 存储遍历订阅用户
            subscribers = await self._get_weather_subscribers()

            if not subscribers:
                logger.debug("没有订阅天气推送的用户")
                return

            for user_id, sub_info in subscribers.items():
                try:
                    # 获取用户位置
                    location = await self.plugin.get_user_location(user_id)
                    if not location:
                        continue

                    # 获取天气数据
                    adcode = location.get("adcode")
                    if not adcode:
                        continue

                    weather_data = await self.plugin.weather_api.get_weather(adcode)
                    if not weather_data:
                        continue

                    # 生成天气摘要
                    summary = self.plugin.weather_api.format_weather_summary(weather_data)

                    # 发送消息
                    umo = sub_info.get("umo")
                    if umo:
                        from astrbot.api.event import MessageChain

                        message_chain = MessageChain().message(f"☀️ 早安！今日天气：\n{summary}")
                        await self.plugin.context.send_message(umo, message_chain)

                except Exception as e:
                    logger.error(f"推送天气给用户 {user_id} 失败: {e}")

            logger.info(f"天气推送完成，共 {len(subscribers)} 位用户")

        except Exception as e:
            logger.error(f"天气推送任务执行失败: {e}")

    async def check_sensors_and_alert(self):
        """检查传感器并告警"""
        try:
            sensors = self.plugin.config.get("sensors", [])
            if not sensors:
                return

            for sensor in sensors:
                # 跳过非字典类型的配置项
                if not isinstance(sensor, dict):
                    continue

                if not sensor.get("enabled", True):
                    continue

                entity_id = sensor.get("entity_id")
                if not entity_id:
                    continue

                # 获取传感器值
                value = await self.plugin.ha_client.get_sensor_value(entity_id)
                if value is None:
                    continue

                # 检查阈值
                alert_info = self._check_threshold(sensor, value)
                if alert_info:
                    await self._send_sensor_alert(sensor, value, alert_info)

        except Exception as e:
            logger.error(f"传感器监控任务执行失败: {e}")

    def _check_threshold(self, sensor: dict, value: float) -> Optional[dict]:
        """
        检查传感器值是否超出阈值

        Args:
            sensor: 传感器配置
            value: 当前值

        Returns:
            告警信息，正常返回 None
        """
        low = sensor.get("low_threshold")
        high = sensor.get("high_threshold")
        # 从 template_list 的 __template_key 获取传感器类型
        sensor_type = sensor.get("__template_key", "generic")

        if low is not None and value < low:
            return {"type": "low", "threshold": low, "sensor_type": sensor_type}

        if high is not None and value > high:
            return {"type": "high", "threshold": high, "sensor_type": sensor_type}

        return None

    async def _send_sensor_alert(
        self, sensor: dict, value: float, alert_info: dict
    ):
        """
        发送传感器告警

        Args:
            sensor: 传感器配置
            value: 当前值
            alert_info: 告警信息
        """
        try:
            # 获取告警订阅用户
            subscribers = await self._get_alert_subscribers()
            if not subscribers:
                return

            name = sensor.get("name", sensor.get("entity_id", "传感器"))
            unit = sensor.get("unit", "")
            alert_type = "过低" if alert_info["type"] == "low" else "过高"
            threshold = alert_info["threshold"]

            message = f"⚠️ 传感器告警\n{name}: 当前值 {value}{unit}，{alert_type}阈值 {threshold}{unit}"

            from astrbot.api.event import MessageChain

            message_chain = MessageChain().message(message)

            for user_id, sub_info in subscribers.items():
                umo = sub_info.get("umo")
                if umo:
                    await self.plugin.context.send_message(umo, message_chain)

        except Exception as e:
            logger.error(f"发送传感器告警失败: {e}")

    async def _get_weather_subscribers(self) -> dict:
        """获取天气推送订阅用户"""
        # 这里需要遍历 KV 存储
        # 由于 AstrBot 没有提供遍历接口，我们使用一个特殊的 key 来存储订阅列表
        subscribers = await self.plugin.get_kv_data("weather_subscribers", {})
        return subscribers

    async def _get_alert_subscribers(self) -> dict:
        """获取告警订阅用户"""
        subscribers = await self.plugin.get_kv_data("alert_subscribers", {})
        return subscribers

    async def add_weather_subscriber(self, user_id: str, umo: str):
        """
        添加天气推送订阅

        Args:
            user_id: 用户 ID
            umo: 消息来源
        """
        subscribers = await self._get_weather_subscribers()
        subscribers[user_id] = {"umo": umo, "subscribed_at": datetime.now().isoformat()}
        await self.plugin.put_kv_data("weather_subscribers", subscribers)

    async def remove_weather_subscriber(self, user_id: str):
        """
        移除天气推送订阅

        Args:
            user_id: 用户 ID
        """
        subscribers = await self._get_weather_subscribers()
        if user_id in subscribers:
            del subscribers[user_id]
            await self.plugin.put_kv_data("weather_subscribers", subscribers)

    async def add_alert_subscriber(self, user_id: str, umo: str):
        """
        添加告警订阅

        Args:
            user_id: 用户 ID
            umo: 消息来源
        """
        subscribers = await self._get_alert_subscribers()
        subscribers[user_id] = {"umo": umo, "subscribed_at": datetime.now().isoformat()}
        await self.plugin.put_kv_data("alert_subscribers", subscribers)

    async def remove_alert_subscriber(self, user_id: str):
        """
        移除告警订阅

        Args:
            user_id: 用户 ID
        """
        subscribers = await self._get_alert_subscribers()
        if user_id in subscribers:
            del subscribers[user_id]
            await self.plugin.put_kv_data("alert_subscribers", subscribers)
