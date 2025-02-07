from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
import requests

@register("Astrbot_Plugin_HAOS_scwunai", "scwunai", "获取HomeAssistant的温湿度传感器数据的插件", "1.0.0", "https://github.com/scwunai/Astrbot_Plugin_HAOS_scwunai")
class SensorDataPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.home_assistant_url = self.config.get("home_assistant_url")
        self.token = self.config.get("token")
        self.temperature_sensor_id = self.config.get("temperature_sensor_id")
        self.humidity_sensor_id = self.config.get("humidity_sensor_id")

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
        yield event.plain_result(f"使用本插件前，请先在配置文件中配置好HomeAssistant的相关信息，例如URL，token以及温湿度传感器的sensor id。备注：URL即为HAOS后台页面，Access Token可以在HAOS后台点击<用户名>-安全-长期访问令牌处找到或者新建，sensor id请在HAOS后台-设置-设备与服务-实体-实体标识符处寻找，需要完整的sensor.xxx。\n配置完成后，使用/get_temperature 指令获取温度数据，以及使用/get_humidity指令获取湿度数据\n")