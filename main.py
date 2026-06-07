import os
import json
import time
import threading
from datetime import datetime
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
USDT_ADDRESS = os.getenv("USDT_ADDRESS", "请联系管理员获取收款地址")

ORDERS_FILE = "orders.json"

app = Flask(__name__)


@app.route("/")
def home():
    return "Global Resource Desk Bot is running."


def run_web():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


def load_orders():
    if not os.path.exists(ORDERS_FILE):
        return {}
    with open(ORDERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_orders(orders):
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)


def generate_order_id():
    return "DD" + datetime.now().strftime("%Y%m%d%H%M%S")


def parse_order_text(text):
    return text.strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Global Resource Desk 全球资源中心已启动。\n\n"
        "群内发送需求后，我会自动登记订单并返回付款信息。"
    )


async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    chat = message.chat
    user = message.from_user
    text = message.text.strip()

    keywords = ["地区", "数量", "年龄", "TG", "tg", "Telegram", "telegram", "活跃"]

    if not any(k in text for k in keywords):
        return

    order_id = generate_order_id()
    orders = load_orders()

    orders[order_id] = {
        "order_id": order_id,
        "chat_id": chat.id,
        "chat_title": chat.title,
        "user_id": user.id,
        "username": user.username,
        "customer_name": user.full_name,
        "request_text": parse_order_text(text),
        "status": "pending_payment",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    save_orders(orders)

    reply = f"""✅ 需求已登记

订单号：{order_id}

📌 需求内容：
{text}

当前需求已进入处理队列。

💳 USDT-TRC20 收款地址：
{USDT_ADDRESS}

付款后请发送转账截图或 TXID，方便核对。

款项确认后，将按照需求条件进行筛选整理，完成后由机器人在本群内交付。

请确认需求信息无误后付款。"""

    await message.reply_text(reply)


async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    orders = load_orders()
    if not orders:
        await update.message.reply_text("当前没有订单。")
        return

    lines = []
    for order_id, order in list(orders.items())[-20:]:
        lines.append(
            f"订单号：{order_id}\n"
            f"群：{order.get('chat_title')}\n"
            f"状态：{order.get('status')}\n"
            f"需求：{order.get('request_text')}\n"
        )

    await update.message.reply_text("\n----------------\n".join(lines))


async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) < 1:
        await update.message.reply_text("格式错误：/paid 订单号")
        return

    order_id = context.args[0].strip()
    orders = load_orders()

    if order_id not in orders:
        await update.message.reply_text("没有找到这个订单号。")
        return

    orders[order_id]["status"] = "paid_processing"
    save_orders(orders)

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
    orders = load_orders()

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

    orders = load_orders()

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
    save_orders(orders)

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
    application.add_handler(CommandHandler("orders", my_orders))
    application.add_handler(CommandHandler("paid", paid))
    application.add_handler(CommandHandler("deliver", deliver_command))
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler))
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.GROUPS, group_message_handler))

    application.add_error_handler(error_handler)

    application.run_polling()


if __name__ == "__main__":
    main()
