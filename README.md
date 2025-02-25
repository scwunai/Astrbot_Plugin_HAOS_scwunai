# Astrbot_Plugin_HAOS_scwunai

Astrbot 的 HomeAssistant 设备联动插件

尝试简单的物联网应用

使用本插件前，请先在配置文件中配置好HomeAssistant的相关信息，例如URL，token以及温湿度传感器的sensor id。
备注：URL即为HAOS后台页面，Access Token可以在HAOS后台点击<用户名>-安全-长期访问令牌处找到或者新建，sensor id请在HAOS后台-设置-设备与服务-实体-实体标识符处寻找，需要完整的sensor.xxx。  
配置完成后，使用/get_temperature 指令获取温度数据，以及使用/get_humidity指令获取湿度数据  

20250212  
新增了 /monitor_temp 以及 /stop_monitor 指令:  
/monitor_temp 启动定时(默认为10,单位为秒)监控当前温度数值,当温度大于配置的最高值(默认为30°C)或者小于最小值(默认为10°C),机器人会发送一条报警消息,检测时间间隔以及最大最小值均可在配置文件中配置,具体参考相关配置信息.   
/stop_monitor 停止当前定时监控任务  

20250225
根据issue的请求，新增了自然语言执行温湿度查询指令以及温度监控开关的功能，

# 支持

[帮助文档](https://astrbot.soulter.top/center/docs/%E5%BC%80%E5%8F%91/%E6%8F%92%E4%BB%B6%E5%BC%80%E5%8F%91/
)
