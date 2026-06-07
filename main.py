import os
import re
import json
import threading
import requests
from html import escape
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "请联系管理员获取收款地址")

ORDERS_FILE = "orders.json"
PENDING_FILE = "pending_requests.json"
PAYMENT_IMAGE = os.getenv("PAYMENT_IMAGE", "payment.jpg")

BOSS_USERNAME = "LOVE_Wl_YOU"
BOSS_LINK = f"https://t.me/{BOSS_USERNAME}"

# 定价表：(地区, 平台, 性别, 年龄, 活跃) -> 单价(RMB/条)
# 目前只有一条规则，后续可扩展
PRICING_RULES = [
    {
        "region": "德国",
        "platform": "Telegram",
        "gender": "男",
        "age_min": 30,
        "age_max": None,
        "active": "3天活跃",
        "unit_price_rmb": 0.28,
    },
]

# 默认单价（如果没有匹配到定价规则，走管理员手动报价）
DEFAULT_UNIT_PRICE = None

app = Flask(__name__)


@app.route("/")
def home():
    return "Global Resource Desk Bot is running."


def run_web():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def load_json(file_path):
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_order_id():
    return "GD" + datetime.now().strftime("%Y%m%d%H%M%S")


def get_okx_usdt_cny_rate():
    """从欧意OKX获取USDT/CNY实时汇率"""
    try:
        url = "https://www.okx.com/v3/c2c/otc-ticker/quotedPrice"
        params = {
            "baseCurrency": "USDT",
            "quoteCurrency": "CNY",
            "side": "sell",
        }
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
        }
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0 and data.get("data"):
            price_str = data["data"].get("bestOption", {}).get("price")
            if price_str:
                return float(price_str)
    except Exception:
        pass

    # 备用接口：OKX v5 ticker
    try:
        url2 = "https://www.okx.com/api/v5/market/index-tickers?instId=USDT-CNY"
        headers2 = {"User-Agent": "Mozilla/5.0"}
        resp2 = requests.get(url2, headers=headers2, timeout=10)
        data2 = resp2.json()
        if data2.get("code") == "0" and data2.get("data"):
            idx_px = data2["data"][0].get("idxPx")
            if idx_px:
                return float(idx_px)
    except Exception:
        pass

    # 第三备用：CoinGecko
    try:
        url3 = "https://api.coingecko.com/api/v3/simple/price?ids=tether&vs_currencies=cny"
        resp3 = requests.get(url3, timeout=10)
        data3 = resp3.json()
        cny_price = data3.get("tether", {}).get("cny")
        if cny_price:
            return float(cny_price)
    except Exception:
        pass

    return None


def parse_age_value(age_str):
    """将年龄字符串解析为 (min, max) 元组"""
    if not age_str:
        return None, None

    range_match = re.match(r"(\d+)\s*[-~到至]\s*(\d+)", age_str)
    if range_match:
        return int(range_match.group(1)), int(range_match.group(2))

    plus_match = re.match(r"(\d+)\+?$", age_str)
    if plus_match:
        return int(plus_match.group(1)), None

    return None, None


def match_pricing_rule(fields):
    """根据订单字段匹配定价规则，返回单价(RMB)或None"""
    region = (fields.get("region") or "").strip()
    platform = (fields.get("platform") or "").strip()
    gender = (fields.get("gender") or "").strip()
    age_str = (fields.get("age") or "").strip()
    active = (fields.get("active") or "").strip()

    age_min, age_max = parse_age_value(age_str)

    for rule in PRICING_RULES:
        # 地区匹配
        if rule["region"].lower() != region.lower() and rule["region"] != region:
            # 也检查德国/Germany等别名
            region_aliases = {
                "德国": ["德国", "germany", "de"],
                "美国": ["美国", "usa", "us", "united states"],
                "英国": ["英国", "uk", "united kingdom"],
                "法国": ["法国", "france"],
                "日本": ["日本", "japan"],
            }
            matched_region = False
            for canonical, aliases in region_aliases.items():
                if rule["region"] == canonical and region.lower() in [a.lower() for a in aliases]:
                    matched_region = True
                    break
            if not matched_region:
                continue

        # 平台匹配
        if rule["platform"].lower() != platform.lower():
            platform_aliases = {
                "Telegram": ["telegram", "tg", "电报"],
                "WhatsApp": ["whatsapp", "wa", "wpp", "ws"],
                "Facebook": ["facebook", "fb", "脸书"],
                "Instagram": ["instagram", "ig", "ins"],
                "TikTok": ["tiktok", "tk", "tt"],
                "LINE": ["line"],
                "Zalo": ["zalo"],
            }
            matched_platform = False
            for canonical, aliases in platform_aliases.items():
                if rule["platform"] == canonical and platform.lower() in [a.lower() for a in aliases]:
                    matched_platform = True
                    break
            if not matched_platform:
                continue

        # 性别匹配
        if rule["gender"] != gender:
            continue

        # 年龄匹配
        if age_min is not None:
            if rule["age_min"] is not None and age_min < rule["age_min"]:
                continue
            if rule["age_max"] is not None and age_max is not None and age_max > rule["age_max"]:
                continue
        else:
            if rule["age_min"] is not None:
                continue

        # 活跃状态匹配
        if rule["active"] != active:
            continue

        return rule["unit_price_rmb"]

    return DEFAULT_UNIT_PRICE


def parse_quantity_to_number(qty_str):
    """将数量字符串转为纯数字"""
    if not qty_str:
        return None

    raw = qty_str.replace(",", "").replace("，", "").replace(" ", "")

    match_k = re.match(r"(\d+(?:\.\d+)?)[kK]", raw)
    if match_k:
        return int(float(match_k.group(1)) * 1000)

    match_w = re.match(r"(\d+(?:\.\d+)?)(w|W|万)", raw)
    if match_w:
        return int(float(match_w.group(1)) * 10000)

    digits = re.sub(r"\D", "", raw)
    if digits:
        return int(digits)

    return None


REGION_LIST = [
    "美国", "德国", "英国", "法国", "意大利", "西班牙", "葡萄牙", "荷兰", "比利时", "瑞士",
    "奥地利", "瑞典", "挪威", "丹麦", "芬兰", "波兰", "捷克", "希腊", "土耳其", "俄罗斯",
    "加拿大", "澳大利亚", "新西兰", "巴西", "墨西哥", "阿根廷", "智利", "哥伦比亚",
    "日本", "韩国", "泰国", "越南", "菲律宾", "马来西亚", "新加坡", "印尼", "印度",
    "阿联酋", "迪拜", "沙特", "卡塔尔", "科威特", "以色列", "南非", "尼日利亚",
    "柬埔寨", "老挝", "缅甸", "全球", "欧美", "东南亚", "中东", "拉美", "欧洲", "亚洲",
    "USA", "US", "United States", "Germany", "UK", "United Kingdom", "France", "Italy",
    "Spain", "Canada", "Australia", "Brazil", "Mexico", "Japan", "Korea", "Thailand",
    "Vietnam", "Philippines", "Malaysia", "Singapore", "Indonesia", "India", "Global"
]

PLATFORM_PATTERNS = [
    ("Telegram", r"(?<![A-Za-z])TG(?![A-Za-z])|telegram|电报"),
    ("WhatsApp", r"whatsapp|whtasapp|(?<![A-Za-z])wa(?![A-Za-z])|(?<![A-Za-z])wpp(?![A-Za-z])|(?<![A-Za-z])ws(?![A-Za-z])"),
    ("Facebook", r"facebook|(?<![A-Za-z])fb(?![A-Za-z])|脸书"),
    ("Instagram", r"instagram|(?<![A-Za-z])ig(?![A-Za-z])|(?<![A-Za-z])ins(?![A-Za-z])"),
    ("TikTok", r"tiktok|(?<![A-Za-z])tk(?![A-Za-z])|(?<![A-Za-z])tt(?![A-Za-z])|抖音国际"),
    ("LINE", r"(?<![A-Za-z])line(?![A-Za-z])"),
    ("Zalo", r"(?<![A-Za-z])zalo(?![A-Za-z])"),
    ("X/Twitter", r"twitter|推特"),
    ("Google", r"google|谷歌"),
    ("YouTube", r"youtube|(?<![A-Za-z])yt(?![A-Za-z])|油管"),
]

FAQ_RULES = [
    {
        "patterns": ["怎么下单", "如何下单", "怎么提交", "下单格式", "格式"],
        "reply": """🧾 提交需求很简单

直接在群里发送需求即可。

示例：
德国 TG 男 30+ 3天活跃 3K

系统会自动识别条件并计算价格。
格式清楚，推进就快。"""
    },
    {
        "patterns": ["多久", "多长时间", "什么时候", "交付时间", "处理时间"],
        "reply": """⏱️ 处理时间取决于地区、渠道、条件和数据量。

条件越细，整理时间越长。
需求越清楚，推进越快。

一句话总结：别让模糊需求浪费你的预算。"""
    },
    {
        "patterns": ["支持什么平台", "支持哪些平台", "有哪些平台", "平台", "渠道"],
        "reply": """📌 常见渠道：

Telegram / WhatsApp / LINE / TikTok / Facebook / Instagram

其他渠道也可以直接发需求。
我能识别就登记，识别不了就提醒你补充。"""
    },
    {
        "patterns": ["支持哪些地区", "什么地区", "哪些国家", "国家", "地区"],
        "reply": """🌍 支持全球地区需求登记。

示例：
美国 / 德国 / 日本 / 柬埔寨 / 迪拜 / 东南亚 / 欧美 / 全球

你负责说目标，我负责把需求整理清楚。"""
    },
    {
        "patterns": ["价格", "报价", "多少钱", "费用", "怎么算"],
        "reply": """💰 系统自动报价。

请发送完整需求：
地区 + 渠道 + 性别 + 年龄 + 状态 + 数据量

示例：德国 TG 男 30+ 3天活跃 5K

系统会自动计算总价并换算为 USDT。"""
    },
    {
        "patterns": ["老板在吗", "人在吗", "有人吗", "客服在吗", "管理员在吗"],
        "reply": f"""在。

机器人在，管理员也会看。

你可以直接发需求，系统自动报价。
更多需求请联系我的 BOSS：
<a href="{BOSS_LINK}">@{BOSS_USERNAME}</a>"""
    },
    {
        "patterns": ["联系老板", "联系boss", "boss", "老板", "管理员"],
        "reply": f"""更多需求请直接联系我的 BOSS：

<a href="{BOSS_LINK}">@{BOSS_USERNAME}</a>

你也可以直接在群里发需求，系统会自动报价。"""
    },
]


def clean_text(value):
    return value.strip(" ：:，,。;；|/\n\t")


def detect_region(text):
    label_match = re.search(r"(地区|国家|市场|区域)\s*[:：]?\s*([A-Za-z\u4e00-\u9fa5\s]{2,40})", text, re.I)
    if label_match:
        raw = clean_text(label_match.group(2))
        raw = re.sub(
            r"(TG|Telegram|电报|WhatsApp|Whtasapp|WA|WPP|WS|Facebook|FB|IG|INS|Instagram|TikTok|TK|TT|LINE|Zalo|Google|YouTube).*",
            "",
            raw,
            flags=re.I
        )
        raw = clean_text(raw)
        if raw:
            return raw

    platform_words = r"TG|Telegram|电报|WhatsApp|Whtasapp|WA|WPP|WS|Facebook|FB|IG|INS|Instagram|TikTok|TK|TT|LINE|Zalo|Google|YouTube"
    before_platform = re.search(rf"([A-Za-z\u4e00-\u9fa5\s]{{2,40}}?)\s*({platform_words})", text, re.I)
    if before_platform:
        raw = clean_text(before_platform.group(1))
        raw = re.sub(r"^(要|需要|求|找|安排|做|地区|国家|市场|区域)", "", raw)
        raw = clean_text(raw)
        if raw:
            return raw

    for region in sorted(REGION_LIST, key=len, reverse=True):
        if re.search(re.escape(region), text, re.I):
            return region

    return None


def detect_platform(text):
    for name, pattern in PLATFORM_PATTERNS:
        if re.search(pattern, text, re.I):
            return name
    return None


def detect_gender(text):
    if re.search(r"男女|混合|不限|全部|所有|all", text, re.I):
        return "不限"
    if re.search(r"男性|男用户|男粉|男\b|male|men", text, re.I):
        return "男"
    if re.search(r"女性|女用户|女粉|女\b|female|women", text, re.I):
        return "女"
    if re.search(r"同性", text):
        return "同性"
    return None


def detect_age(text):
    range_match = re.search(r"(\d{2})\s*[-~到至]\s*(\d{2})\s*岁?", text)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}"

    plus_match = re.search(r"(\d{2})\s*(\+|岁以上|以上)", text)
    if plus_match:
        return f"{plus_match.group(1)}+"

    label_match = re.search(r"(年龄|年龄分布|受众年龄|人群年龄)\s*[:：]?\s*(\d{2})\s*(\+|岁以上|以上)?", text)
    if label_match:
        suffix = "+" if label_match.group(3) else ""
        return f"{label_match.group(2)}{suffix}"

    return None


def detect_active(text):
    text = text.strip()

    if re.search(r"当日活跃|当天活跃|今日活跃|当天|今日|当日", text):
        return "1天活跃"

    random_range = re.search(r"(\d{1,2})\s*[-~到至]\s*(\d{1,2})\s*(天|日)\s*(随机)?", text)
    if random_range:
        suffix = "随机" if random_range.group(4) else ""
        return f"{random_range.group(1)}-{random_range.group(2)}天活跃{suffix}"

    near_match = re.search(r"(近|最近)?\s*(\d{1,2})\s*(天|日)(内)?\s*(活跃)?", text)
    if near_match:
        return f"{near_match.group(2)}天活跃"

    active_match = re.search(r"活跃\s*(\d{1,2})\s*(天|日)", text)
    if active_match:
        return f"{active_match.group(1)}天活跃"

    status_match = re.search(r"(状态)\s*[:：]?\s*(.+)", text)
    if status_match:
        raw = clean_text(status_match.group(2))
        if raw:
            return raw[:30]

    return None


def normalize_quantity(raw):
    raw = raw.replace(",", "").replace("，", "").replace(" ", "")

    match_k = re.match(r"(\d+(?:\.\d+)?)[kK]", raw)
    if match_k:
        num = float(match_k.group(1))
        return f"{int(num)}K" if num.is_integer() else f"{num}K"

    match_w = re.match(r"(\d+(?:\.\d+)?)(w|W|万)", raw)
    if match_w:
        num = float(match_w.group(1)) * 10000
        return f"{int(num):,}"

    match_qian = re.match(r"(\d+(?:\.\d+)?)(千)", raw)
    if match_qian:
        num = float(match_qian.group(1)) * 1000
        return f"{int(num):,}"

    digits = re.sub(r"\D", "", raw)
    if digits:
        return f"{int(digits):,}"

    return raw


def detect_quantity(text):
    label_match = re.search(
        r"(数据量|数量|需求量|规模|条数|样本)\s*[:：]?\s*(\d+(?:\.\d+)?\s*(?:[kK]|w|W|万|千)?|\d{3,})\s*(条|个|份|人|组)?",
        text
    )
    if label_match:
        return normalize_quantity(label_match.group(2))

    comma_number_match = re.search(r"(\d{1,3}(?:,\d{3})+)\s*(条|个|份|人|组)?", text)
    if comma_number_match:
        return normalize_quantity(comma_number_match.group(1))

    unit_match = re.search(r"(\d+(?:\.\d+)?\s*(?:[kK]|w|W|万|千))\s*(条|个|份|人|组)?", text)
    if unit_match:
        return normalize_quantity(unit_match.group(1))

    big_number_match = re.search(r"\b(\d{4,6})\b\s*(条|个|份|人|组)?", text)
    if big_number_match:
        return normalize_quantity(big_number_match.group(1))

    return None


def parse_request_text(text):
    return {
        "region": detect_region(text),
        "platform": detect_platform(text),
        "gender": detect_gender(text),
        "age": detect_age(text),
        "quantity": detect_quantity(text),
        "active": detect_active(text),
    }


FIELD_NAMES = {
    "region": "地区",
    "platform": "渠道",
    "gender": "性别",
    "age": "年龄分布",
    "quantity": "数据量",
    "active": "状态",
}

REQUIRED_FIELDS = ["region", "platform", "gender", "age", "quantity", "active"]


def merge_fields(old_data, new_data):
    merged = dict(old_data or {})
    for key, value in new_data.items():
        if value:
            merged[key] = value
    return merged


def missing_fields(data):
    return [field for field in REQUIRED_FIELDS if not data.get(field)]


def recognized_count(data):
    return sum(1 for value in data.values() if value)


def format_current_fields(data):
    lines = []
    for key in REQUIRED_FIELDS:
        if data.get(key):
            lines.append(f"{FIELD_NAMES[key]}：{escape(str(data[key]))}")
    return "\n".join(lines) if lines else "暂无"


def format_missing_fields(fields):
    return "、".join(FIELD_NAMES[field] for field in fields)


def build_pending_reply(data):
    missing = missing_fields(data)

    return f"""📌 已识别到部分需求

当前已识别：
{format_current_fields(data)}

还需补充：
{escape(format_missing_fields(missing))}

📍 填写参考：
渠道：Telegram / WhatsApp / LINE / TikTok / Facebook / Instagram
性别：男 / 女 / 不限
年龄分布：25-45 / 30-55 / 25-80
数据量：2,000 条 / 3K / 10K
状态：1天活跃 / 3天活跃 / 7天活跃 / 30天活跃

请直接补充缺少条件，系统会自动合并并计算价格。

更多需求请直接联系我的 BOSS：
<a href="{BOSS_LINK}">@{BOSS_USERNAME}</a>"""


def build_order_reply_with_price(order_id, data, pricing_info):
    """生成带自动报价的订单回复"""

    base_text = f"""✅ 需求已受理

订单号：<b>{escape(order_id)}</b>

📌 需求概览
地区：{escape(str(data.get("region")))}
渠道：{escape(str(data.get("platform")))}
性别：{escape(str(data.get("gender")))}
年龄分布：{escape(str(data.get("age")))}
数据量：{escape(str(data.get("quantity")))}
状态：{escape(str(data.get("active")))}"""

    if pricing_info:
        price_text = f"""

💰 自动报价
单价：{pricing_info['unit_price_rmb']} RMB / 条
数量：{pricing_info['quantity_num']:,} 条
总价（RMB）：¥{pricing_info['total_rmb']:.2f}
欧意实时汇率：1 USDT ≈ {pricing_info['usdt_rate']:.2f} CNY
总价（USDT）：<b>{pricing_info['total_usdt']:.2f} USDT</b>

💳 USDT-TRC20 收款地址：
<code>{escape(USDT_ADDRESS)}</code>

请使用 TRC20 网络转账，付款后发送 TXID 或转账截图。"""
    else:
        price_text = f"""

💰 报价信息
当前条件暂无自动定价规则，管理员将尽快确认报价。"""

    footer = f"""

更多需求请直接联系我的 BOSS：
<a href="{BOSS_LINK}">@{BOSS_USERNAME}</a>"""

    return base_text + price_text + footer


def build_admin_notice(order_id, order, pricing_info=None):
    fields = order.get("fields", {})

    username = order.get("username")
    username_text = f"@{username}" if username else "无用户名"

    price_section = ""
    if pricing_info:
        price_section = f"""
💰 自动报价结果
单价：{pricing_info['unit_price_rmb']} RMB/条
数量：{pricing_info['quantity_num']:,} 条
总价 RMB：¥{pricing_info['total_rmb']:.2f}
汇率：1 USDT ≈ {pricing_info['usdt_rate']:.2f} CNY
总价 USDT：{pricing_info['total_usdt']:.2f} USDT
"""
    else:
        price_section = "\n⚠️ 无自动定价规则，需手动报价。
