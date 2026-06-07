import re
import html
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = "8889862305:AAGm95LW8I9midz7YzaGCrCZFd33ecM7bTs"

BOSS_USERNAME = "LOVE_Wl_YOU"
BOSS_URL = f"https://t.me/{BOSS_USERNAME}"

CAMBODIA_TZ = ZoneInfo("Asia/Phnom_Penh")


def now_cambodia():
    return datetime.now(CAMBODIA_TZ)


def make_order_id():
    return "GD" + now_cambodia().strftime("%Y%m%d%H%M%S")


def normalize_channel(channel: str) -> str:
    channel = channel.strip().lower()

    mapping = {
        "tg": "Telegram",
        "telegram": "Telegram",
        "wa": "WhatsApp",
        "whatsapp": "WhatsApp",
        "line": "LINE",
        "fb": "Facebook",
        "facebook": "Facebook",
    }

    return mapping.get(channel, channel.upper())


def parse_requirement(text: str):
    text = text.strip()

    pattern = r"^(?P<region>\S+)\s+(?P<channel>\S+)\s+(?P<gender>男|女|不限|全部)\s+(?P<age>\d{1,2}\s*-\s*\d{1,2})\s+(?P<status>\S+)\s+(?P<amount>\d+(?:\.\d+)?\s*[Kk万千]?)$"

    match = re.match(pattern, text)
    if not match:
        return None

    data = match.groupdict()
    data["channel"] = normalize_channel(data["channel"])
    data["age"] = data["age"].replace(" ", "")
    data["amount"] = data["amount"].upper().replace(" ", "")

    return data


def order_keyboard(order_id: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ 确认需求",
                callback_data=f"confirm_order:{order_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ 返回修改",
                callback_data=f"edit_order:{order_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🌐 更多定制联系 BOSS",
                url=BOSS_URL
            )
        ],
    ])


def boss_only_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🌐 更多定制联系 BOSS",
                url=BOSS_URL
            )
        ]
    ])


def build_order_text(order_id: str, data: dict):
    time_text = now_cambodia().strftime("%Y-%m-%d %H:%M:%S")

    return f"""全球资源中心
━━━━━━━━━━━━━━
🌐 Global Resource Desk｜全球资源中心

✅ 需求单已生成，请再次确认相关信息
确认完成后，将同步下一步处理安排。

订单号：{html.escape(order_id)}

📊 需求参数
时间：{html.escape(time_text)}（柬埔寨时间）
地区：{html.escape(data["region"])}
渠道：{html.escape(data["channel"])}
性别：{html.escape(data["gender"])}
年龄分布：{html.escape(data["age"])}
数据量：{html.escape(data["amount"])}
状态：{html.escape(data["status"])}

请核对以上信息，确认无误后点击下方按钮。"""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """全球资源中心

请直接发送需求，格式如下：

美国 TG 男 25-45 3天活跃 3K"""
    await update.message.reply_text(text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text.strip()
    data = parse_requirement(user_text)

    if not data:
        await update.message.reply_text(
            """需求格式不正确。

请按这个格式发送：

美国 TG 男 25-45 3天活跃 3K"""
        )
        return

    order_id = make_order_id()

    context.user_data["last_order"] = {
        "order_id": order_id,
        "data": data,
        "raw_text": user_text,
    }

    await update.message.reply_text(
        build_order_text(order_id, data),
        parse_mode="HTML",
        reply_markup=order_keyboard(order_id)
    )


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action_data = query.data

    if action_data.startswith("confirm_order:"):
        order_id = action_data.split(":", 1)[1]

        text = f"""⏳ 订单状态

系统已确认本次需求，后台正在进行人工确认...
请勿重复提交相同需求，避免生成重复订单。

如需调整地区、渠道、数量或状态，请直接补充说明。

订单号：{html.escape(order_id)}"""

        await query.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=boss_only_keyboard()
        )

    elif action_data.startswith("edit_order:"):
        order_id = action_data.split(":", 1)[1]

        text = f"""↩️ 已返回修改模式

请重新发送完整需求。

订单号：{html.escape(order_id)}

示例：
美国 TG 男 25-45 3天活跃 3K"""

        await query.message.reply_text(text, parse_mode="HTML")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("机器人已启动...")
    app.run_polling()


if __name__ == "__main__":
    main()
