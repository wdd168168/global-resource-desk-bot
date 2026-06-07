import os
import re
import json
import threading
from html import escape
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

ORDERS_FILE = "orders.json"
PENDING_FILE = "pending_requests.json"

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
    ("Telegram", r"\bTG\b|telegram|电报"),
    ("WhatsApp", r"whatsapp|\bwa\b|\bwpp\b|\bws\b"),
    ("Facebook", r"facebook|\bfb\b|脸书"),
    ("Instagram", r"instagram|\big\b|\bins\b"),
    ("TikTok", r"tiktok|\btk\b|\btt\b|抖音国际"),
    ("LINE", r"\bline\b|Line"),
    ("Zalo", r"\bzalo\b"),
    ("X/Twitter", r"twitter|\bx\b|推特"),
    ("Google", r"google|谷歌"),
    ("YouTube", r"youtube|yt|油管"),
]

PROJECT_PATTERNS = [
    ("广告投放", r"广告|投放|推广|获客|引流|曝光|转化"),
    ("市场调研", r"调研|市场研究|问卷|样本|分析|报告"),
    ("社群运营", r"社群|群运营|群管理|社区|私域"),
    ("内容分发", r"素材|内容|帖子|视频|图文|发布"),
    ("品牌曝光", r"品牌|曝光|声量|知名度"),
    ("客户支持", r"客服|售后|咨询|支持"),
]


def clean_text(value):
    return value.strip(" ：:，,。;；|/\n\t")


def detect_region(text):
    label_match = re.search(r"(地区|国家|市场|区域)\s*[:：]?\s*([A-Za-z\u4e00-\u9fa5\s]{2,40})", text, re.I)
    if label_match:
        raw = clean_text(label_match.group(2))
        raw = re.sub(r"(TG|Telegram|电报|WhatsApp|WA|WPP|WS|Facebook|FB|IG|INS|Instagram|TikTok|TK|TT|LINE|Zalo|Google|YouTube).*", "", raw, flags=re.I)
        raw = clean_text(raw)
        if raw:
            return raw

    platform_words = r"TG|Telegram|电报|WhatsApp|WA|WPP|WS|Facebook|FB|IG|INS|Instagram|TikTok|TK|TT|LINE|Zalo|Google|YouTube"
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


def detect_project_type(text):
    for name, pattern in PROJECT_PATTERNS:
        if re.search(pattern, text, re.I):
            return name
    return None


def detect_audience(text):
    if re.search(r"男性|男用户|男\b|male|men", text, re.I):
        return "男性用户"
    if re.search(r"女性|女用户|女\b|female|women", text, re.I):
        return "女性用户"
    if re.search(r"不限|混合|全部|所有|all", text, re.I):
        return "不限/混合"
    if re.search(r"商家|店主|电商|卖家", text):
        return "电商/商家人群"
    if re.search(r"本地|当地|local", text, re.I):
        return "本地目标人群"
    if re.search(r"高净值|投资|老板|企业主|B2B|b2b", text, re.I):
        return "商业/高价值人群"
    return None


def detect_age_or_profile(text):
    range_match = re.search(r"(\d{2})\s*[-~到至]\s*(\d{2})\s*岁?", text)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}"

    plus_match = re.search(r"(\d{2})\s*(\+|岁以上|以上)", text)
    if plus_match:
        return f"{plus_match.group(1)}+"

    label_match = re.search(r"(年龄|受众年龄|人群年龄)\s*[:：]?\s*(\d{2})\s*(\+|岁以上|以上)?", text)
    if label_match:
        suffix = "+" if label_match.group(3) else ""
        return f"{label_match.group(2)}{suffix}"

    return None


def detect_period(text):
    if re.search(r"当天|当日|今日", text):
        return "当天"
    if re.search(r"一周|7天|七天", text):
        return "7天"
    if re.search(r"半个月|15天|十五天", text):
        return "15天"
    if re.search(r"一个月|30天|三十天", text):
        return "30天"

    range_match = re.search(r"(\d{1,2})\s*[-~到至]\s*(\d{1,2})\s*(天|日)", text)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}天"

    day_match = re.search(r"(\d{1,2})\s*(天|日)", text)
    if day_match:
        return f"{day_match.group(1)}天"

    return None


def normalize_scale(raw):
    raw = raw.replace(",", "").replace(" ", "")
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


def detect_scale(text):
    budget_match = re.search(r"(预算|金额|费用)\s*[:：]?\s*([$¥]?\s*\d+(?:\.\d+)?\s*(?:美金|美元|人民币|U|u|USD|usd)?)", text)
    if budget_match:
        return clean_text(budget_match.group(2))

    scale_match = re.search(r"(规模|数量|样本|需求量)\s*[:：]?\s*(\d+(?:\.\d+)?\s*(?:[kK]|w|W|万|千)?|\d{3,})\s*(份|个|条|人|组)?", text)
    if scale_match:
        return normalize_scale(scale_match.group(2))

    unit_match = re.search(r"(\d+(?:\.\d+)?\s*(?:[kK]|w|W|万|千))\s*(份|个|条|人|组)?", text)
    if unit_match:
        return normalize_scale(unit_match.group(1))

    big_number_match = re.search(r"\b(\d{4,6})\b\s*(份|个|条|人|组)?", text)
    if big_number_match:
        return normalize_scale(big_number_match.group(1))

    return None


def parse_request_text(text):
    return {
        "region": detect_region(text),
        "platform": detect_platform(text),
        "project_type": detect_project_type(text),
        "audience": detect_audience(text),
        "age_or_profile": detect_age_or_profile(text),
        "period": detect_period(text),
        "scale": detect_scale(text),
    }


FIELD_NAMES = {
    "region": "目标地区",
    "platform": "投放/服务平台",
    "project_type": "项目类型",
    "audience": "目标人群",
    "age_or_profile": "年龄/画像",
    "period": "执行周期",
    "scale": "预算/规模",
}

FIELD_EXAMPLES = {
    "region": "美国 / 迪拜 / 柬埔寨 / 日本 / 全球任意国家",
    "platform": "Telegram / WhatsApp / LINE / TikTok / Facebook / Instagram",
    "project_type": "广告投放 / 市场调研 / 社群运营 / 内容分发",
    "audience": "男 / 女 / 不限 / 本地用户 / 电商商家 / 企业主",
    "age_or_profile": "25-45 / 30-55 / 商家 / 本地人群 / 高价值客户",
    "period": "1天 / 3天 / 7天 / 30天",
    "scale": "预算500U / 样本300 / 规模3K / 数量10000",
}

REQUIRED_FIELDS = ["region", "platform", "project_type", "audience", "period", "scale"]


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
    for key in ["region", "platform", "project_type", "audience", "age_or_profile", "period", "scale"]:
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
目标地区：美国 / 迪拜 / 柬埔寨 / 日本 / 全球任意国家
平台渠道：Telegram / WhatsApp / LINE / TikTok / Facebook / Instagram
项目类型：广告投放 / 市场调研 / 社群运营 / 内容分发
目标人群：男 / 女 / 不限 / 本地用户 / 电商商家 / 企业主
年龄画像：25-45 / 30-55 / 商家 / 本地人群 / 高价值客户
执行周期：1天 / 3天 / 7天 / 30天
预算规模：预算500U / 样本300 / 规模3K / 数量10000

请直接补充缺少条件，系统会自动合并生成完整需求单。"""


def build_order_reply(order_id, data):
    return f"""✅ 需求已受理

订单号：<b>{escape(order_id)}</b>

📌 需求概览
目标地区：{escape(str(data.get("region")))}
平台渠道：{escape(str(data.get("platform")))}
项目类型：{escape(str(data.get("project_type")))}
目标人群：{escape(str(data.get("audience")))}
年龄画像：{escape(str(data.get("age_or_profile") or "未指定"))}
执行周期：{escape(str(data.get("period")))}
预算规模：{escape(str(data.get("scale")))}

📍 当前状态
需求已完成登记，等待管理员确认。

管理员确认后，将根据以上条件进入处理流程。

如需修改条件，请直接补充说明。"""


def should_trigger_order(text, parsed, has_pending):
    if has_pending and recognized_count(parsed) > 0:
        return True

    trigger_words = [
        "地区", "国家", "市场", "平台", "预算", "规模", "数量", "周期",
        "广告", "投放", "推广", "调研", "样本", "报告", "社群", "运营",
        "TG", "telegram", "电报", "whatsapp", "facebook", "fb",
        "instagram", "ig", "tiktok", "tk", "line", "zalo",
        "男", "女", "男性", "女性", "本地", "商家"
    ]

    if any(word.lower() in text.lower() for word in trigger_words):
        return recognized_count(parsed) >= 2

    return recognized_count(parsed) >= 3


FAQ_RULES = [
    {
        "patterns": ["怎么下单", "如何下单", "怎么提交", "下单格式", "格式"],
        "reply": """🧾 下单格式很简单

直接在群里发送需求即可。

示例：
美国 Telegram 广告投放 男性用户 7天 预算500U

系统会自动识别条件，缺什么我会追问。放心，我不挑食，但我挑格式。"""
    },
    {
        "patterns": ["多久", "多长时间", "什么时候", "交付时间"],
        "reply": """⏱️ 时间取决于地区、平台、项目类型和规模。

条件越细，处理时间越长。
需求越清楚，推进越快。

模糊需求会消耗时间，清晰需求会节省预算。"""
    },
    {
        "patterns": ["支持什么平台", "支持哪些平台", "有哪些平台", "平台"],
        "reply": """📌 当前支持的常见平台：

Telegram / WhatsApp / LINE / TikTok / Facebook / Instagram / Google / YouTube

其他平台也可以直接发需求，我会自动识别，识别不了就提醒你补充。"""
    },
    {
        "patterns": ["支持哪些地区", "什么地区", "哪些国家", "国家"],
        "reply": """🌍 支持全球地区需求登记。

示例：
美国 / 德国 / 日本 / 柬埔寨 / 迪拜 / 东南亚 / 欧美 / 全球

你负责说目标，我负责把需求整理清楚。"""
    },
    {
        "patterns": ["保效果", "保证效果", "转化率", "回复率", "成交率"],
        "reply": """📌 结果说明

项目执行会按确认条件处理，但不承诺具体转化结果。

最终效果受预算、素材、账号状态、执行时间、话术、市场环境等因素影响。

我能帮你把需求登记清楚，效果还得靠执行别掉链子。"""
    },
    {
        "patterns": ["老板在吗", "人在吗", "有人吗", "客服在吗"],
        "reply": """在。

机器人在，管理员也会看。

你直接发需求，我先帮你整理。别让一个“在吗”耽误一单生意。"""
    },
    {
        "patterns": ["价格", "报价", "多少钱", "费用"],
        "reply": """💰 报价需要先看完整条件。

请补充：
目标地区
平台渠道
项目类型
目标人群
执行周期
预算或规模

条件越完整，报价越准确。猜价格这种事，我不建议你信。"""
    },
]


def get_faq_reply(text):
    lower = text.lower()
    for rule in FAQ_RULES:
        for pattern in rule["patterns"]:
            if pattern.lower() in lower:
                return rule["reply"]
    return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Global Resource Desk 全球资源中心已启动。\n\n"
        "群内发送广告投放、市场调研或服务需求后，我会自动整理需求并追问缺失信息。"
    )


async def cancel_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pending = load_json(PENDING_FILE)
    key = f"{update.effective_chat.id}:{update.effective_user.id}"

    if key in pending:
        pending.pop(key)
        save_json(PENDING_FILE, pending)
        await update.message.reply_text("当前未完成需求已取消。")
    else:
        await update.message.reply_text("当前没有未完成需求。")


async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    if message.from_user and message.from_user.is_bot:
        return

    text = message.text.strip()

    if text.startswith("/"):
        return

    chat = message.chat
    user = message.from_user

    pending = load_json(PENDING_FILE)
    pending_key = f"{chat.id}:{user.id}"

    parsed = parse_request_text(text)
    has_pending = pending_key in pending

    if should_trigger_order(text, parsed, has_pending):
        current_data = pending.get(pending_key, {}).get("fields", {})
        merged = merge_fields(current_data, parsed)
        missing = missing_fields(merged)

        if missing:
            pending[pending_key] = {
                "chat_id": chat.id,
                "chat_title": chat.title,
                "user_id": user.id,
                "username": user.username,
                "customer_name": user.full_name,
                "fields": merged,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            save_json(PENDING_FILE, pending)

            await message.reply_text(
                build_pending_reply(merged),
                parse_mode="HTML"
            )
            return

        order_id = generate_order_id()
        orders = load_json(ORDERS_FILE)

        orders[order_id] = {
            "order_id": order_id,
            "chat_id": chat.id,
            "chat_title": chat.title,
            "user_id": user.id,
            "username": user.username,
            "customer_name": user.full_name,
            "fields": merged,
            "raw_text": text,
            "status": "pending_admin_confirm",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        save_json(ORDERS_FILE, orders)

        if pending_key in pending:
            pending.pop(pending_key)
            save_json(PENDING_FILE, pending)

        await message.reply_text(
            build_order_reply(order_id, merged),
            parse_mode="HTML"
        )
        return

    faq_reply = get_faq_reply(text)
    if faq_reply:
        await message.reply_text(faq_reply)
        return


async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    orders = load_json(ORDERS_FILE)
    if not orders:
        await update.message.reply_text("当前没有需求单。")
        return

    lines = []
    for order_id, order in list(orders.items())[-20:]:
        fields = order.get("fields", {})
        lines.append(
            f"订单号：{order_id}\n"
            f"群：{order.get('chat_title')}\n"
            f"状态：{order.get('status')}\n"
            f"地区：{fields.get('region')}\n"
            f"平台：{fields.get('platform')}\n"
            f"项目：{fields.get('project_type')}\n"
            f"规模：{fields.get('scale')}\n"
        )

    await update.message.reply_text("\n----------------\n".join(lines))


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 1:
        await update.message.reply_text("格式错误：/approve 订单号")
        return

    order_id = context.args[0].strip()
    orders = load_json(ORDERS_FILE)

    if order_id not in orders:
        await update.message.reply_text("没有找到这个订单号。")
        return

    orders[order_id]["status"] = "confirmed_processing"
    orders[order_id]["confirmed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_json(ORDERS_FILE, orders)

    chat_id = orders[order_id]["chat_id"]

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"""✅ 需求已确认

订单号：{order_id}

管理员已确认需求，项目进入处理流程。

感谢信任，后续进度会在本群同步。"""
    )

    await update.message.reply_text(f"已确认并通知群内：{order_id}")


async def deliver_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 1:
        await update.message.reply_text("格式错误：/deliver 订单号\n然后再发送交付文件。")
        return

    order_id = context.args[0].strip()
    orders = load_json(ORDERS_FILE)

    if order_id not in orders:
        await update.message.reply_text("没有找到这个订单号。")
        return

    context.user_data["deliver_order_id"] = order_id
    await update.message.reply_text(f"已选择订单：{order_id}\n现在请发送交付文件。")


async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    order_id = context.user_data.get("deliver_order_id")
    if not order_id:
        await update.message.reply_text("请先发送：/deliver 订单号")
        return

    orders = load_json(ORDERS_FILE)

    if order_id not in orders:
        await update.message.reply_text("订单不存在。")
        return

    chat_id = orders[order_id]["chat_id"]
    document = update.message.document

    caption = f"""✅ 订单 {order_id} 已完成交付

📎 文件已上传，请及时查看。

📌 交付说明

本次交付以确认后的项目需求为准。

如对文件内容存在疑问，请于交付后24小时内联系管理员反馈处理，超出时限不予受理。

感谢您的支持与信任。"""

    await context.bot.send_document(
        chat_id=chat_id,
        document=document.file_id,
        caption=caption
    )

    orders[order_id]["status"] = "delivered"
    orders[order_id]["delivered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    save_json(ORDERS_FILE, orders)

    context.user_data.pop("deliver_order_id", None)

    await update.message.reply_text(f"订单 {order_id} 已发送到对应群内。")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"Error: {context.error}")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("缺少 BOT_TOKEN 环境变量")

    threading.Thread(target=run_web, daemon=True).start()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel_request))
    application.add_handler(CommandHandler("orders", my_orders))
    application.add_handler(CommandHandler("approve", approve))
    application.add_handler(CommandHandler("deliver", deliver_command))
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, group_message_handler))

    application.add_error_handler(error_handler)

    application.run_polling()


if __name__ == "__main__":
    main()
