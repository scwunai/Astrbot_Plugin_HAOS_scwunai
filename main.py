from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api.event import MessageChain
from astrbot.api.message_components import *
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from astrbot.api.provider import ProviderRequest
from astrbot.api.provider import LLMResponse
import asyncio
import requests

@register("Astrbot_Plugin_HAOS_scwunai", "scwunai", "一个获取HomeAssistant的温湿度传感器数据的插件", "1.0.1 ", "https://github.com/scwunai/Astrbot_Plugin_HAOS_scwunai")
class SensorDataPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.home_assistant_url = self.config.get("home_assistant_url")
        self.token = self.config.get("token")
        self.temperature_sensor_id = self.config.get("temperature_sensor_id")
        self.humidity_sensor_id = self.config.get("humidity_sensor_id")

        self.low_threshold = self.config.get("low_threshold", 10)
        self.high_threshold = self.config.get("high_threshold", 30)
        self.check_interval = self.config.get("check_interval", 10)

        # 初始化调度器
        self.scheduler = AsyncIOScheduler()
        
    @filter.command("monitor_temp")
    async def monitor_temperature(self, event: AstrMessageEvent):  
        """启动定时监测"""
        time_interval = self.check_interval
        umo = event.unified_msg_origin  # 保存消息来源

        async def check_and_alert():
            temperature = self._get_temp()
            if temperature is not None:
                if temperature < self.low_threshold:
                    message = f"当前温度 {temperature}°C 过低！"
                elif temperature > self.high_threshold:
                    message = f"当前温度 {temperature}°C 过高！"
                else:
                    return  # 温度正常，不发送消息
            else:
                message = "获取温度失败，请检查配置以及连接情况"

            message_chain = MessageChain().message(message)
            await self.context.send_message(umo, message_chain)

        # 添加任务到调度器，使用闭包捕获umo
        self.scheduler.add_job(check_and_alert, 'interval', seconds=int(time_interval))
        if not self.scheduler.running:
            self.scheduler.start()
            
        yield event.plain_result("温度监控已启动")

    def _get_temp(self) -> float | None:
        """获取温度数据（同步方法）"""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        url = f"{self.home_assistant_url}/api/states/{self.temperature_sensor_id}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return float(response.json().get("state"))
        except (requests.RequestException, ValueError):
            pass
        return None

    @filter.command("stop_monitor") 
    async def stop_monitor(self, event: AstrMessageEvent):
        """关闭定时监测"""
        self.scheduler.shutdown()
        yield event.plain_result("温度监控已停止")



    @filter.command("get_temperature")
    async def get_temperature(self, event: AstrMessageEvent):
        """获取温度数据"""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        # 获取温度数据
        temperature_api_url = f"{self.home_assistant_url}/api/states/{self.temperature_sensor_id}"
        temperature_response = requests.get(temperature_api_url, headers=headers)

        if temperature_response.status_code == 200:
            temperature_data = temperature_response.json()
            temperature = temperature_data.get("state", "N/A")  # 获取温度值
            yield event.plain_result(f"温度: {temperature}°C")
        else:
            yield event.plain_result(f"获取温度数据失败: {temperature_response.status_code} - {temperature_response.text}")

    @filter.command("get_humidity")
    async def get_humidity(self, event: AstrMessageEvent):
        """获取湿度数据"""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        # 获取湿度数据
        humidity_api_url = f"{self.home_assistant_url}/api/states/{self.humidity_sensor_id}"
        humidity_response = requests.get(humidity_api_url, headers=headers)

        if humidity_response.status_code == 200:
            humidity_data = humidity_response.json()
            humidity = humidity_data.get("state", "N/A")  # 获取湿度值
            yield event.plain_result(f"湿度: {humidity}%")
        else:
            yield event.plain_result(f"获取湿度数据失败: {humidity_response.status_code} - {humidity_response.text}")


    @filter.command("haoshelp")
    async def help(self, event: AstrMessageEvent):
        yield event.plain_result(f"使用本插件前，请先在配置文件中配置好HomeAssistant的相关信息，例如URL，token以及温湿度传感器的sensor id。备注：URL即为HAOS后台页面，Access Token可以在HAOS后台点击<用户名>-安全-长期访问令牌处找到或者新建，sensor id请在HAOS后台-设置-设备与服务-实体-实体标识符处寻找，需要完整的sensor.xxx。\n配置完成后，使用/get_temperature 指令获取温度数据，以及使用/get_humidity指令获取湿度数据\n\n\n 20250212 \n新增了 /monitor_temp 以及 /stop_monitor 指令:\n/monitor_temp 启动定时(默认为10,单位为秒)监控当前温度数值,当温度大于配置的最高值(默认为30°C)或者小于最小值(默认为10°C),机器人会发送一条报警消息,检测时间间隔以及最大最小值均可在配置文件中配置,具体参考相关配置信息.\n /stop_monitor 停止当前定时监控任务\n 可以通过自然语言让bot返回温度湿度以及打开关闭监控了。\n")
    
    @filter.on_llm_request()
    async def on_llm_req(self, event: AstrMessageEvent, req: ProviderRequest):
        """优化后的LLM请求处理"""
        system_prompt = """
        根据用户请求直接回复指定指令（不要解释）：
        1. 需要启动监控 → "启用温度监控"
        2. 需要停止监控 → "关闭温度监控"
        3. 询问当前温度 → "检查当前温度"
        4. 询问当前湿度 → "检查当前湿度"
        其他情况正常回答。

        示例：
        用户：帮我盯着点温度 → 启用温度监控
        用户：别监控了 → 关闭温度监控
        用户：现在多少度 → 检查当前温度
        用户：现在湿度是多少 → 检查当前湿度

        当前问题：""" + req.system_prompt
        req.system_prompt = system_prompt

    @filter.on_llm_response()
    async def on_llm_resp(self, event: AstrMessageEvent, resp: LLMResponse):
        """处理LLM响应并执行对应操作"""
        cmd_map = {
            "启用温度监控": self.monitor_temperature,
            "关闭温度监控": self.stop_monitor,
            "检查当前温度": self.get_temperature,
            "检查当前湿度": self.get_humidity
        }
        
        llm_output = resp.completion_text
        
        for key in cmd_map:
            if key in llm_output:
                # 获取对应的指令处理方法
                handler = cmd_map[key]
                
                try:
                    # 执行指令处理函数并获取生成器
                    gen = handler(event)
                    
                    # 遍历所有yield的结果
                    async for result in gen:
                        # 发送实际执行结果
                        await event.send(result)
                    
                    # 清空原始LLM响应
                    resp.completion_text = ""
                
                except Exception as e:
                    await event.send(MessageChain([Plain(f"执行指令失败: {str(e)}")]))
                    resp.completion_text = ""
                
                break
