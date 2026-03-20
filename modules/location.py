"""
位置管理模块

处理用户位置设置、行政区划匹配和 IP 定位
"""

import aiohttp
import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class LocationManager:
    """位置管理器"""

    # 内置主要城市行政区划代码（作为后备数据）
    MAJOR_CITIES = {
        # 直辖市
        "北京": {"adcode": "110100", "province": "北京市", "city": "北京市"},
        "北京市": {"adcode": "110100", "province": "北京市", "city": "北京市"},
        "上海": {"adcode": "310100", "province": "上海市", "city": "上海市"},
        "上海市": {"adcode": "310100", "province": "上海市", "city": "上海市"},
        "天津": {"adcode": "120100", "province": "天津市", "city": "天津市"},
        "天津市": {"adcode": "120100", "province": "天津市", "city": "天津市"},
        "重庆": {"adcode": "500100", "province": "重庆市", "city": "重庆市"},
        "重庆市": {"adcode": "500100", "province": "重庆市", "city": "重庆市"},
        # 省会城市
        "广州": {"adcode": "440100", "province": "广东省", "city": "广州市"},
        "广州市": {"adcode": "440100", "province": "广东省", "city": "广州市"},
        "深圳": {"adcode": "440300", "province": "广东省", "city": "深圳市"},
        "深圳市": {"adcode": "440300", "province": "广东省", "city": "深圳市"},
        "杭州": {"adcode": "330100", "province": "浙江省", "city": "杭州市"},
        "杭州市": {"adcode": "330100", "province": "浙江省", "city": "杭州市"},
        "南京": {"adcode": "320100", "province": "江苏省", "city": "南京市"},
        "南京市": {"adcode": "320100", "province": "江苏省", "city": "南京市"},
        "成都": {"adcode": "510100", "province": "四川省", "city": "成都市"},
        "成都市": {"adcode": "510100", "province": "四川省", "city": "成都市"},
        "武汉": {"adcode": "420100", "province": "湖北省", "city": "武汉市"},
        "武汉市": {"adcode": "420100", "province": "湖北省", "city": "武汉市"},
        "西安": {"adcode": "610100", "province": "陕西省", "city": "西安市"},
        "西安市": {"adcode": "610100", "province": "陕西省", "city": "西安市"},
        "郑州": {"adcode": "410100", "province": "河南省", "city": "郑州市"},
        "郑州市": {"adcode": "410100", "province": "河南省", "city": "郑州市"},
        "长沙": {"adcode": "430100", "province": "湖南省", "city": "长沙市"},
        "长沙市": {"adcode": "430100", "province": "湖南省", "city": "长沙市"},
        "济南": {"adcode": "370100", "province": "山东省", "city": "济南市"},
        "济南市": {"adcode": "370100", "province": "山东省", "city": "济南市"},
        "青岛": {"adcode": "370200", "province": "山东省", "city": "青岛市"},
        "青岛市": {"adcode": "370200", "province": "山东省", "city": "青岛市"},
        "沈阳": {"adcode": "210100", "province": "辽宁省", "city": "沈阳市"},
        "沈阳市": {"adcode": "210100", "province": "辽宁省", "city": "沈阳市"},
        "大连": {"adcode": "210200", "province": "辽宁省", "city": "大连市"},
        "大连市": {"adcode": "210200", "province": "辽宁省", "city": "大连市"},
        "哈尔滨": {"adcode": "230100", "province": "黑龙江省", "city": "哈尔滨市"},
        "哈尔滨市": {"adcode": "230100", "province": "黑龙江省", "city": "哈尔滨市"},
        "长春": {"adcode": "220100", "province": "吉林省", "city": "长春市"},
        "长春市": {"adcode": "220100", "province": "吉林省", "city": "长春市"},
        "石家庄": {"adcode": "130100", "province": "河北省", "city": "石家庄市"},
        "石家庄市": {"adcode": "130100", "province": "河北省", "city": "石家庄市"},
        "福州": {"adcode": "350100", "province": "福建省", "city": "福州市"},
        "福州市": {"adcode": "350100", "province": "福建省", "city": "福州市"},
        "厦门": {"adcode": "350200", "province": "福建省", "city": "厦门市"},
        "厦门市": {"adcode": "350200", "province": "福建省", "city": "厦门市"},
        "合肥": {"adcode": "340100", "province": "安徽省", "city": "合肥市"},
        "合肥市": {"adcode": "340100", "province": "安徽省", "city": "合肥市"},
        "南昌": {"adcode": "360100", "province": "江西省", "city": "南昌市"},
        "南昌市": {"adcode": "360100", "province": "江西省", "city": "南昌市"},
        "昆明": {"adcode": "530100", "province": "云南省", "city": "昆明市"},
        "昆明市": {"adcode": "530100", "province": "云南省", "city": "昆明市"},
        "贵阳": {"adcode": "520100", "province": "贵州省", "city": "贵阳市"},
        "贵阳市": {"adcode": "520100", "province": "贵州省", "city": "贵阳市"},
        "兰州": {"adcode": "620100", "province": "甘肃省", "city": "兰州市"},
        "兰州市": {"adcode": "620100", "province": "甘肃省", "city": "兰州市"},
        "乌鲁木齐": {"adcode": "650100", "province": "新疆维吾尔自治区", "city": "乌鲁木齐市"},
        "乌鲁木齐市": {"adcode": "650100", "province": "新疆维吾尔自治区", "city": "乌鲁木齐市"},
        "呼和浩特": {"adcode": "150100", "province": "内蒙古自治区", "city": "呼和浩特市"},
        "呼和浩特市": {"adcode": "150100", "province": "内蒙古自治区", "city": "呼和浩特市"},
        "南宁": {"adcode": "450100", "province": "广西壮族自治区", "city": "南宁市"},
        "南宁市": {"adcode": "450100", "province": "广西壮族自治区", "city": "南宁市"},
        "海口": {"adcode": "460100", "province": "海南省", "city": "海口市"},
        "海口市": {"adcode": "460100", "province": "海南省", "city": "海口市"},
        "太原": {"adcode": "140100", "province": "山西省", "city": "太原市"},
        "太原市": {"adcode": "140100", "province": "山西省", "city": "太原市"},
        "西宁": {"adcode": "630100", "province": "青海省", "city": "西宁市"},
        "西宁市": {"adcode": "630100", "province": "青海省", "city": "西宁市"},
        "银川": {"adcode": "640100", "province": "宁夏回族自治区", "city": "银川市"},
        "银川市": {"adcode": "640100", "province": "宁夏回族自治区", "city": "银川市"},
        "拉萨": {"adcode": "540100", "province": "西藏自治区", "city": "拉萨市"},
        "拉萨市": {"adcode": "540100", "province": "西藏自治区", "city": "拉萨市"},
        "苏州": {"adcode": "320500", "province": "江苏省", "city": "苏州市"},
        "苏州市": {"adcode": "320500", "province": "江苏省", "city": "苏州市"},
        "无锡": {"adcode": "320200", "province": "江苏省", "city": "无锡市"},
        "无锡市": {"adcode": "320200", "province": "江苏省", "city": "无锡市"},
        "宁波": {"adcode": "330200", "province": "浙江省", "city": "宁波市"},
        "宁波市": {"adcode": "330200", "province": "浙江省", "city": "宁波市"},
        "东莞": {"adcode": "441900", "province": "广东省", "city": "东莞市"},
        "东莞市": {"adcode": "441900", "province": "广东省", "city": "东莞市"},
        "佛山": {"adcode": "440600", "province": "广东省", "city": "佛山市"},
        "佛山市": {"adcode": "440600", "province": "广东省", "city": "佛山市"},
        "珠海": {"adcode": "440400", "province": "广东省", "city": "珠海市"},
        "珠海市": {"adcode": "440400", "province": "广东省", "city": "珠海市"},
        "温州": {"adcode": "330300", "province": "浙江省", "city": "温州市"},
        "温州市": {"adcode": "330300", "province": "浙江省", "city": "温州市"},
    }

    def __init__(self, data_dir: Optional[Path] = None):
        """
        初始化位置管理器

        Args:
            data_dir: 数据目录路径
        """
        self.data_dir = data_dir
        self.adcode_data = {}
        self._load_adcode_data()

    def _load_adcode_data(self):
        """加载行政区划数据"""
        loaded_from_file = False

        # 优先尝试从 JSON 缓存文件加载
        if self.data_dir:
            cache_path = self.data_dir / "adcode_cache.json"
            if cache_path.exists():
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        self.adcode_data = json.load(f)
                    logger.info(f"从缓存加载行政区划数据: {len(self.adcode_data)} 条")
                    loaded_from_file = True
                except Exception as e:
                    logger.warning(f"加载缓存文件失败: {e}")

        # 如果缓存不存在，尝试从 xlsx 文件加载
        if not loaded_from_file and self.data_dir:
            xlsx_path = self.data_dir / "National_administrative_division_codes_data.xlsx"
            if xlsx_path.exists():
                try:
                    loaded_from_file = self._load_from_xlsx(xlsx_path)
                    # 加载成功后保存缓存
                    if loaded_from_file:
                        self._save_cache()
                except Exception as e:
                    logger.warning(f"从 xlsx 加载行政区划数据失败: {e}")

        # 合并内置数据（作为后备和补充）
        for name, info in self.MAJOR_CITIES.items():
            if name not in self.adcode_data:
                self.adcode_data[name] = info

        logger.info(f"行政区划数据总计: {len(self.adcode_data)} 条")

    def _save_cache(self):
        """保存数据到缓存文件"""
        if not self.data_dir:
            return
        try:
            cache_path = self.data_dir / "adcode_cache.json"
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(self.adcode_data, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存行政区划数据缓存: {cache_path}")
        except Exception as e:
            logger.warning(f"保存缓存文件失败: {e}")

    def _load_from_xlsx(self, xlsx_path: Path) -> bool:
        """
        从 xlsx 文件加载行政区划数据（遍历所有 sheet）

        Args:
            xlsx_path: xlsx 文件路径

        Returns:
            是否加载成功
        """
        try:
            import pandas as pd

            # 获取所有 sheet 名称
            xl = pd.ExcelFile(xlsx_path)
            sheet_names = xl.sheet_names

            total_count = 0
            for sheet_name in sheet_names:
                # 读取当前 sheet
                df = pd.read_excel(xlsx_path, sheet_name=sheet_name)

                # 筛选层级3（县级）数据
                county_level = df[df['行政层级'] == 3].copy()

                # 提取行政区划代码前6位
                county_level['adcode'] = county_level['行政区域代码'].astype(str).str[:6]

                # 根据行政区划代码推断省份
                province = self._get_province_by_adcode(
                    county_level['adcode'].iloc[0] if len(county_level) > 0 else ""
                )

                # 构建位置数据字典
                for _, row in county_level.iterrows():
                    name = row['行政区域名称']
                    adcode = row['adcode']

                    # 跳过"市辖区"这种占位符
                    if name == "市辖区":
                        continue

                    # 如果已存在同名地区，跳过（保留第一个匹配的）
                    if name in self.adcode_data:
                        continue

                    # 判断是否为市级行政区
                    is_city = name.endswith('市')
                    # 判断是否为区/县级
                    is_district = name.endswith('区') or name.endswith('县') or name.endswith('旗')

                    self.adcode_data[name] = {
                        "adcode": adcode,
                        "province": province,
                        "city": name if is_city else province,  # 市级用自身名，区县级用省份名
                        "district": name if is_district else ""
                    }
                    total_count += 1

            logger.info(f"从 xlsx 加载行政区划数据: {len(sheet_names)} 个省级行政区, {total_count} 条县级数据")
            return True

        except ImportError:
            logger.warning("未安装 pandas 或 openpyxl，无法读取 xlsx 文件")
            return False
        except Exception as e:
            logger.error(f"解析 xlsx 文件失败: {e}")
            return False

    def _get_province_by_adcode(self, adcode: str) -> str:
        """
        根据行政区划代码推断省份

        Args:
            adcode: 6位行政区划代码

        Returns:
            省份名称
        """
        # 行政区划代码前2位对应省份
        province_map = {
            "11": "北京市",
            "12": "天津市",
            "13": "河北省",
            "14": "山西省",
            "15": "内蒙古自治区",
            "21": "辽宁省",
            "22": "吉林省",
            "23": "黑龙江省",
            "31": "上海市",
            "32": "江苏省",
            "33": "浙江省",
            "34": "安徽省",
            "35": "福建省",
            "36": "江西省",
            "37": "山东省",
            "41": "河南省",
            "42": "湖北省",
            "43": "湖南省",
            "44": "广东省",
            "45": "广西壮族自治区",
            "46": "海南省",
            "50": "重庆市",
            "51": "四川省",
            "52": "贵州省",
            "53": "云南省",
            "54": "西藏自治区",
            "61": "陕西省",
            "62": "甘肃省",
            "63": "青海省",
            "64": "宁夏回族自治区",
            "65": "新疆维吾尔自治区",
            "71": "台湾省",
            "81": "香港特别行政区",
            "82": "澳门特别行政区",
        }

        prefix = adcode[:2]
        return province_map.get(prefix, "未知省份")

    def match_location(self, text: str) -> Optional[dict]:
        """
        从文本匹配位置信息

        Args:
            text: 用户输入的位置文本

        Returns:
            位置信息字典，未匹配返回 None
        """
        if not text:
            return None

        # 清理文本
        text = text.strip()

        # 直接匹配
        if text in self.adcode_data:
            return self.adcode_data[text].copy()

        # 模糊匹配：尝试匹配城市名
        for city_name, info in self.adcode_data.items():
            if city_name in text or text in city_name:
                return info.copy()

        # 尝试提取城市名（去掉"市"、"省"、"区"、"县"等后缀）
        patterns = [
            r"([\u4e00-\u9fa5]+)市",
            r"([\u4e00-\u9fa5]+)省([\u4e00-\u9fa5]+)市",
            r"([\u4e00-\u9fa5]+省)?([\u4e00-\u9fa5]+[市区县])",
            r"([\u4e00-\u9fa5]{2,})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                # 获取最后一个捕获组
                groups = match.groups()
                extracted = groups[-1] if groups else match.group(0)

                # 尝试直接匹配
                if extracted in self.adcode_data:
                    return self.adcode_data[extracted].copy()

                # 尝试去掉后缀匹配
                for suffix in ["市", "区", "县", "镇", "乡"]:
                    if extracted.endswith(suffix):
                        base = extracted[:-1]
                        if base in self.adcode_data:
                            return self.adcode_data[base].copy()

                # 尝试加"市"后缀
                if extracted + "市" in self.adcode_data:
                    return self.adcode_data[extracted + "市"].copy()

                # 尝试加"区"后缀
                if extracted + "区" in self.adcode_data:
                    return self.adcode_data[extracted + "区"].copy()

        return None

    async def get_location_by_ip(self) -> Optional[dict]:
        """
        通过本机 IP 获取位置

        Returns:
            位置信息字典
        """
        try:
            async with aiohttp.ClientSession() as session:
                # 使用 ip-api.com 获取位置
                async with session.get(
                    "http://ip-api.com/json/?lang=zh-CN"
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "success":
                            city = data.get("city", "")
                            province = data.get("regionName", "")
                            # 尝试匹配城市
                            location = self.match_location(city)
                            if location:
                                location["ip"] = data.get("query", "")
                                return location
                            # 尝试匹配省份
                            location = self.match_location(province)
                            if location:
                                location["ip"] = data.get("query", "")
                                return location
        except Exception as e:
            logger.error(f"IP 定位失败: {e}")

        return None

    def parse_location_text(self, text: str) -> dict:
        """
        解析用户输入的位置文本

        Args:
            text: 用户输入

        Returns:
            解析结果，包含 success 和 location 或 error
        """
        location = self.match_location(text)
        if location:
            return {"success": True, "location": location}
        return {
            "success": False,
            "error": f"无法识别位置: {text}，请输入城市名称，如：北京、上海、广州",
        }

    def format_location(self, location: dict) -> str:
        """
        格式化位置信息

        Args:
            location: 位置信息字典

        Returns:
            格式化的位置文本
        """
        if not location:
            return "未知位置"

        province = location.get("province", "")
        city = location.get("city", "")
        district = location.get("district", "")

        # 去重：如果 city 和 province 相同，只保留一个
        if city == province:
            city = ""

        # 去重：如果 district 包含在 city 中，不重复显示
        if district and city and district in city:
            district = ""

        parts = [province, city, district]
        return "".join(filter(None, parts)) or "未知位置"
