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
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "请联系管理员获取收款地址")

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
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_order_id():
    return "DD" + datetime.now().strftime("%Y%m%d%H%M%S")


PLATFORM_PATTERNS = [
    ("Telegram", r"\bTG\b|telegram|电报"),
    ("WhatsApp", r"whatsapp|\bwa\b|\bwpp\b|\bws\b"),
    ("Facebook", r"facebook|\bfb\b|脸书"),
    ("Instagram", r"instagram|\big\b|\bins\b"),
    ("TikTok", r"tiktok|\btk\b|\btt\b|抖音国际"),
    ("LINE", r"\bline\b"),
    ("Zalo", r"\bzalo\b"),
    ("X/Twitter", r"\btwitter\b|\bx\b|推特"),
]

REGION_LIST = [
    "美国", "德国", "英国", "法国", "意大利", "西班牙", "葡萄牙", "荷兰", "比利时", "瑞士",
    "奥地利", "瑞典", "挪威", "丹麦", "芬兰", "波兰", "捷克", "希腊", "土耳其", "俄罗斯",
    "乌克兰", "加拿大", "澳大利亚", "新西兰", "巴西", "墨西哥", "阿根廷", "智利", "哥伦比亚",
    "日本", "韩国", "泰国", "越南", "菲律宾", "马来西亚", "新加坡", "印尼", "印度", "巴基斯坦",
    "阿联酋", "沙特", "卡塔尔", "科威特", "以色列", "南非", "尼日利亚", "肯尼亚", "埃及",
    "柬埔寨", "老挝", "缅甸", "全球", "欧美", "东南亚", "中东", "拉美", "欧洲", "亚洲",
    "USA", "US", "United States", "Germany", "UK", "United Kingdom", "France", "Italy",
    "Spain", "Canada", "Australia", "Brazil", "Mexico", "Japan", "Korea", "Thailand",
    "Vietnam", "Philippines", "Malaysia", "Singapore", "Indonesia", "India", "Global"
]


def clean_region(value):
    value = value.strip()
    value = re.sub(r"^(要|需要|求|找|来|安排|地区|国家|市场|区域)[:：\s]*", "", value)
    value = re.sub(r"(TG|Telegram|电报|WhatsApp|WA|WPP|WS|Facebook|FB|IG|INS|Instagram|TikTok|TK|TT|LINE|Zalo).*", "", value, flags=re.I)
    value = value.strip(" ：:，,。;；|/")
    return value


def detect_region(text):
    label_match = re.search(r"(地区|国家|市场|区域)\s*[:：]?\s*([A-Za-z\u4e00-\u9fa5\s]{2,40})", text, re.I)
    if label_match:
        region = clean_region(label_match.group(2))
        if region:
            return region

    platform_words = r"TG|Telegram|电报|WhatsApp|WA|WPP|WS|Facebook|FB|IG|INS|Instagram|TikTok|TK|TT|LINE|Zalo"
    before_platform = re.search(rf"([A-Za-z\u4e00-\u9fa5\s]{{2,40}}?)\s*({platform_words})", text, re.I)
    if before_platform:
        region = clean_region(before_platform.group(1))
        if region:
            return region

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
    if re.search(r"男女|混合|不限|全部|all", text, re.I):
        return "不限/混合"
    if re.search(r"男性|男粉|男用户|男\b|male|men", text, re.I):
        return "男性用户"
    if re.search(r"女性|女粉|女用户|女\b|female|women", text, re.I):
        return "女性用户"
    return None


def detect_active(text):
    if re.search(r"当日活跃|当天活跃|今日活跃|当天|今日|当日", text):
        return "当日活跃"

    range_match = re.search(r"(\d{1,2})\s*[-~到至]\s*(\d{1,2})\s*(天|日)", text)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}天活跃"

    near_match = re.search(r"(近|最近)?\s*(\d{1,2})\s*(天|日)(内)?\s*活跃?", text)
    if near_match:
        return f"近{near_match.group(2)}天活跃"

    active_match = re.search(r"活跃\s*(\d{1,2})\s*(天|日)", text)
    if active_match:
        return f"近{active_match.group(1)}天活跃"

    return None


def detect_age(text):
    range_match = re.search(r"(\d{2})\s*[-~到至]\s*(\d{2})\s*岁?", text)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}"

    plus_match = re.search(r"(\d{2})\s*(\+|岁以上|以上)", text)
    if plus_match:
        return f"{plus_match.group(1)}+"

    label_match = re.search(r"年龄\s*[:：]?\s*(\d{2})\s*(\+|岁以上|以上)?", text)
    if label_match:
        suffix = "+" if label_match.group(2) else ""
        return f"{label_match.group(1)}{suffix}"

    return None


def normalize_quantity(raw):
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


def detect_quantity(text):
    label_match = re.search(r"(数量|需求数量|规模)\s*[:：]?\s*(\d+(?:\.\d+)?\s*(?:[kK]|w|W|万|千)?|\d{3,})\s*(条|个|份)?", text)
    if label_match:
        return normalize_quantity(label_match.group(2))

    unit_match = re.search(r"(\d+(?:\.\d+)?\s*(?:[kK]|w|W|万|千))\s*(条|个|份)?", text)
    if unit_match:
        return normalize_quantity(unit_match.group(1))

    big_number_match = re.search(r"\b(\d{4,6})\b\s*(条|个|份)?", text)
    if big_number_match:
        return normalize_quantity(big_number_match.group(1))

    return None


def parse_request_text(text):
    return {
        "region": detect_region(text),
        "platform": detect_platform(text),
        "gender": detect_gender(text),
        "active": detect_active(text),
        "age": detect_age(text),
        "quantity": detect_quantity(text),
    }


FIELD_NAMES = {
    "region": "地区",
    "platform": "平台",
    "gender": "类型",
    "active": "活跃度",
    "age": "年龄条件",
    "quantity": "需求数量",
}

FIELD_EXAMPLES = {
    "region": "例如：美国 / 德国 / 巴西 / 全球",
    "platform": "例如：TG / WhatsApp / FB / IG / TK",
    "gender": "例如：男性 / 女性 / 不限",
    "active": "例如：当日活跃 / 1-3天 / 1-7天",
    "age": "例如：25+ / 30+ / 25-55",
    "quantity": "例如：1000 / 3K / 10000条",
}

REQUIRED_FIELDS = ["region", "platform", "gender", "active", "age", "quantity"]


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
    lines = []
    for key in fields:
        lines.append(f"{FIELD_NAMES[key]}：{FIELD_EXAMPLES[key]}")
    return "\n".join(lines)


def should_trigger(text, parsed, has_pending):
    if has_pending and recognized_count(parsed) > 0:
        return True

    trigger_words = [
        "地区", "国家", "市场", "数量", "年龄", "活跃",
        "TG", "telegram", "电报", "whatsapp", "facebook", "fb",
        "instagram", "ig", "tiktok", "tk", "line", "zalo",
        "男", "女", "男性", "女性"
    ]

    if any(word.lower() in text.lower() for word in trigger_words):
        return recognized_count(parsed) >= 2

    return recognized_count(parsed) >= 3


def build_pending_reply(data):
    missing = missing_fields(data)

    return f"""📌 已识别到部分需求

当前已识别：
{format_current_fields(data)}

还需要补充：
{format_missing_fields(missing)}

请直接补充缺少条件，系统会自动合并为完整订单。"""


def build_order_reply(order_id, data):
    return f"""✅ 需求已受理

订单号：<b>{escape(order_id)}</b>

📌 需求概览
地区：{escape(str(data.get("region")))}
平台：{escape(str(data.get("platform")))}
类型：{escape(str(data.get("gender")))}
活跃度：{escape(str(data.get("active")))}
年龄条件：{escape(str(data.get("age")))}
需求数量：{escape(str(data.get("quantity")))}

📍 当前状态
需求已完成登记，正在等待付款确认。

💳 USDT-TRC20 收款地址：
<code>{escape(USDT_ADDRESS)}</code>

付款后请发送转账截图或 TXID，方便核对。

款项确认后，将按照以上条件进行筛选整理，完成后由机器人在本群交付。

请确认需求信息无误后付款。"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Global Resource Desk 全球资源中心已启动。\n\n"
        "群内发送需求后，我会自动登记订单并返回付款信息。"
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

    if not should_trigger(text, parsed, has_pending):
        return

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
        "status": "pending_payment",
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


async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    orders = load_json(ORDERS_FILE)
    if not orders:
        await update.message.reply_text("当前没有订单。")
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
            f"数量：{fields.get('quantity')}\n"
        )

    await update.message.reply_text("\n----------------\n".join(lines))


async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 1:
        await update.message.reply_text("格式错误：/paid 订单号")
        return

    order_id = context.args[0].strip()
    orders = load_json(ORDERS_FILE)

    if order_id not in orders:
        await update.message.reply_text("没有找到这个订单号。")
        return

    orders[order_id]["status"] = "paid_processing"
    save_json(ORDERS_FILE, orders)

    chat_id = orders[order_id]["chat_id"]

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"""✅ 款项已确认到账

订单号：{order_id}

订单已进入处理流程。

感谢您的支持与信任，完成整理后会第一时间在本群交付。"""
    )

    await update.message.reply_text(f"已通知群内：{order_id} 款项到账。")


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

📎 交付文件已上传，请及时下载保存。

📌 交付说明

数据仅保证真实性，不保证添加率、接通率、回复率、成交率及任何转化结果。

数据具有可复制性，交付后因时间、开发方式、市场环境等因素产生的变化，不属于售后范围。

本次交付以实际提供的数据内容为准，不接受未经验证的主观性反馈。

如有疑问，请于交付后24小时内联系管理员反馈处理，超时不予受理。

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
    application.add_handler(CommandHandler("paid", paid))
    application.add_handler(CommandHandler("deliver", deliver_command))
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, group_message_handler))

    application.add_error_handler(error_handler)

    application.run_polling()


if __name__ == "__main__":
    main()
