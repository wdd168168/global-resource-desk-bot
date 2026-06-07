import os
import logging
import time
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

# ============ 配置 ============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
BOSS_USERNAME = "LOVE_Wl_YOU"
BOSS_LINK = "https://t.me/LOVE_Wl_YOU"
USDT_ADDRESS = os.environ.get("USDT_ADDRESS", "请设置USDT_ADDRESS环境变量")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ============ 定价表 ============
# key: (地区, 平台, 性别, 年龄段, 活跃状态) -> 单价(RMB)
PRICE_TABLE = {
    ("德国", "TG", "男", "30+", "3天活跃"): 0.28,
    ("德国", "TG", "女", "30+", "3天活跃"): 0.32,
    ("德国", "TG", "男", "18-29", "3天活跃"): 0.30,
    ("德国", "TG", "女", "18-29", "3天活跃"): 0.35,
    ("德国", "WS", "男", "30+", "3天活跃"): 0.35,
    ("德国", "WS", "女", "30+", "3天活跃"): 0.40,
    ("美国", "TG", "男", "30+", "3天活跃"): 0.22,
    ("美国", "TG", "女", "30+", "3天活跃"): 0.26,
    ("英国", "TG", "男", "30+", "3天活跃"): 0.25,
    ("日本", "LINE", "男", "30+", "7天活跃"): 0.45,
    # 按需追加...
}

# 选项列表
REGIONS = ["德国", "美国", "英国", "日本", "韩国", "东南亚", "全球混合"]
PLATFORMS = ["TG", "WS", "LINE", "Facebook", "Instagram", "Twitter"]
GENDERS = ["男", "女", "混合"]
AGE_RANGES = ["18-29", "30+", "40+", "不限"]
ACTIVITY_LEVELS = ["3天活跃", "7天活跃", "30天活跃", "不限"]

# 会话状态
(
    SELECT_REGION,
    SELECT_PLATFORM,
    SELECT_GENDER,
    SELECT_AGE,
    SELECT_ACTIVITY,
    INPUT_QUANTITY,
    CONFIRM_ORDER,
) = range(7)


# ============ OKX 汇率 ============
def get_usdt_cny_rate() -> float:
    """从OKX获取USDT/CNY实时汇率"""
    try:
        url = "https://www.okx.com/v3/c2c/otc-ticker/quotedPrice"
        params = {
            "baseCurrency": "USDT",
            "quoteCurrency": "CNY",
            "side": "sell",
        }
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        if data.get("code") == 0 and data.get("data"):
            price = float(data["data"].get("bestOption", {}).get("price", 0))
            if price > 0:
                return price
    except Exception as e:
        logger.warning(f"OKX汇率获取失败: {e}")

    # 备用：OKX市场行情API
    try:
        url2 = "https://www.okx.com/api/v5/market/ticker?instId=USDT-CNY"
        resp2 = requests.get(url2, headers=headers, timeout=10)
        data2 = resp2.json()
        if data2.get("data"):
            return float(data2["data"][0]["last"])
    except Exception as e:
        logger.warning(f"OKX备用汇率获取失败: {e}")

    return 7.25  # 兜底汇率


def rmb_to_usdt(rmb_amount: float) -> tuple:
    """RMB转USDT，返回 (usdt金额, 汇率)"""
    rate = get_usdt_cny_rate()
    usdt = round(rmb_amount / rate, 2)
    return usdt, rate


# ============ 键盘生成 ============
def build_keyboard(options: list, prefix: str, cols: int = 3) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=opt, callback_data=f"{prefix}:{opt}")
        for opt in options
    ]
    rows = [buttons[i : i + cols] for i in range(0, len(buttons), cols)]
    return InlineKeyboardMarkup(rows)


# ============ 命令处理 ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "欢迎使用数据自动报价机器人\n\n"
        "发送 /order 开始下单\n"
        "发送 /price 查看价格表\n"
        f"人工客服: {BOSS_LINK}\n\n"
        "支持地区: 德国/美国/英国/日本/韩国/东南亚\n"
        "支持平台: TG/WS/LINE/FB/IG/Twitter"
    )
    await update.message.reply_text(text)


async def price_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["当前价格表 (单位: RMB/条)\n"]
    for key, price in PRICE_TABLE.items():
        region, platform, gender, age, activity = key
        lines.append(
            f"  {region} | {platform} | {gender} | {age} | {activity} → ¥{price}"
        )
    lines.append(f"\n实时汇率通过OKX获取")
    lines.append(f"人工咨询: {BOSS_LINK}")
    await update.message.reply_text("\n".join(lines))


# ============ 下单会话流程 ============
async def order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    kb = build_keyboard(REGIONS, "region")
    await update.message.reply_text("【第1步】请选择地区:", reply_markup=kb)
    return SELECT_REGION


async def region_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    context.user_data["region"] = value
    kb = build_keyboard(PLATFORMS, "platform")
    await query.edit_message_text(
        f"地区: {value}\n\n【第2步】请选择平台:", reply_markup=kb
    )
    return SELECT_PLATFORM


async def platform_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    context.user_data["platform"] = value
    kb = build_keyboard(GENDERS, "gender")
    region = context.user_data["region"]
    await query.edit_message_text(
        f"地区: {region} | 平台: {value}\n\n【第3步】请选择性别:",
        reply_markup=kb,
    )
    return SELECT_GENDER


async def gender_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    context.user_data["gender"] = value
    kb = build_keyboard(AGE_RANGES, "age")
    ud = context.user_data
    await query.edit_message_text(
        f"地区: {ud['region']} | 平台: {ud['platform']} | 性别: {value}\n\n"
        f"【第4步】请选择年龄段:",
        reply_markup=kb,
    )
    return SELECT_AGE


async def age_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    context.user_data["age"] = value
    kb = build_keyboard(ACTIVITY_LEVELS, "activity")
    ud = context.user_data
    await query.edit_message_text(
        f"地区: {ud['region']} | 平台: {ud['platform']} | "
        f"性别: {ud['gender']} | 年龄: {value}\n\n"
        f"【第5步】请选择活跃状态:",
        reply_markup=kb,
    )
    return SELECT_ACTIVITY


async def activity_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    value = query.data.split(":", 1)[1]
    context.user_data["activity"] = value
    ud = context.user_data
    await query.edit_message_text(
        f"地区: {ud['region']} | 平台: {ud['platform']} | "
        f"性别: {ud['gender']} | 年龄: {ud['age']} | 活跃: {value}\n\n"
        f"【第6步】请输入购买数量（纯数字）:"
    )
    return INPUT_QUANTITY


async def quantity_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("请输入有效的正整数数量:")
        return INPUT_QUANTITY

    qty = int(text)
    context.user_data["quantity"] = qty
    ud = context.user_data

    # 查价
    key = (ud["region"], ud["platform"], ud["gender"], ud["age"], ud["activity"])
    unit_price = PRICE_TABLE.get(key)

    if unit_price is None:
        # 尝试模糊匹配或给默认价
        unit_price = find_closest_price(key)

    if unit_price is None:
        await update.message.reply_text(
            f"当前组合暂无定价，请联系人工客服: {BOSS_LINK}"
        )
        return ConversationHandler.END

    total_rmb = round(unit_price * qty, 2)
    usdt_amount, rate = rmb_to_usdt(total_rmb)
    context.user_data["unit_price"] = unit_price
    context.user_data["total_rmb"] = total_rmb
    context.user_data["usdt_amount"] = usdt_amount
    context.user_data["rate"] = rate

    summary = (
        "═══ 订单确认 ═══\n\n"
        f"地区: {ud['region']}\n"
        f"平台: {ud['platform']}\n"
        f"性别: {ud['gender']}\n"
        f"年龄: {ud['age']}\n"
        f"活跃: {ud['activity']}\n"
        f"数量: {qty} 条\n\n"
        f"单价: ¥{unit_price}/条\n"
        f"总价: ¥{total_rmb}\n"
        f"汇率: {rate} (OKX实时)\n"
        f"折合: {usdt_amount} USDT\n\n"
        f"确认下单请点击下方按钮"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("确认下单", callback_data="confirm:yes"),
                InlineKeyboardButton("取消", callback_data="confirm:no"),
            ]
        ]
    )
    await update.message.reply_text(summary, reply_markup=kb)
    return CONFIRM_ORDER


async def order_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data.split(":", 1)[1]

    if choice == "no":
        await query.edit_message_text("订单已取消。发送 /order 重新下单。")
        return ConversationHandler.END

    ud = context.user_data
    order_id = f"ORD{int(time.time())}"

    payment_msg = (
        f"═══ 支付信息 ═══\n\n"
        f"订单号: {order_id}\n"
        f"应付: {ud['usdt_amount']} USDT\n\n"
        f"收款网络: TRC20\n"
        f"收款地址:\n{USDT_ADDRESS}\n\n"
        f"付款后请将TxHash发送给客服确认\n"
        f"客服: {BOSS_LINK}\n\n"
        f"请在30分钟内完成付款，超时需重新下单"
    )
    await query.edit_message_text(payment_msg)

    # 通知老板
    try:
        boss_msg = (
            f"新订单 {order_id}\n"
            f"地区:{ud['region']} 平台:{ud['platform']} "
            f"性别:{ud['gender']} 年龄:{ud['age']} 活跃:{ud['activity']}\n"
            f"数量:{ud['quantity']} 总价:¥{ud['total_rmb']} = {ud['usdt_amount']}U\n"
            f"用户: @{query.from_user.username or query.from_user.id}"
        )
        # 如果知道boss的chat_id可以直接发
        # await context.bot.send_message(chat_id=BOSS_CHAT_ID, text=boss_msg)
        logger.info(boss_msg)
    except Exception as e:
        logger.error(f"通知老板失败: {e}")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("已取消。发送 /order 重新开始。")
    return ConversationHandler.END


# ============ 模糊匹配 ============
def find_closest_price(key: tuple) -> float | None:
    """找最接近的定价，优先匹配地区+平台"""
    region, platform, gender, age, activity = key
    candidates = []
    for k, v in PRICE_TABLE.items():
        score = 0
        if k[0] == region:
            score += 10
        if k[1] == platform:
            score += 5
        if k[2] == gender:
            score += 2
        if k[3] == age:
            score += 2
        if k[4] == activity:
            score += 1
        if score >= 15:  # 至少地区+平台匹配
            candidates.append((score, v))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return None


# ============ 通用消息 ============
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if any(kw in text for kw in ["价格", "报价", "多少钱", "price"]):
        await price_list(update, context)
    elif any(kw in text for kw in ["下单", "购买", "买", "order"]):
        return await order_start(update, context)
    else:
        await update.message.reply_text(
            f"发送 /order 自动报价下单\n发送 /price 查看价格表\n人工客服: {BOSS_LINK}"
        )


# ============ 主函数 ============
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN 未设置")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("order", order_start)],
        states={
            SELECT_REGION: [
                CallbackQueryHandler(region_selected, pattern=r"^region:")
            ],
            SELECT_PLATFORM: [
                CallbackQueryHandler(platform_selected, pattern=r"^platform:")
            ],
            SELECT_GENDER: [
                CallbackQueryHandler(gender_selected, pattern=r"^gender:")
            ],
            SELECT_AGE: [
                CallbackQueryHandler(age_selected, pattern=r"^age:")
            ],
            SELECT_ACTIVITY: [
                CallbackQueryHandler(activity_selected, pattern=r"^activity:")
            ],
            INPUT_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quantity_input)
            ],
            CONFIRM_ORDER: [
                CallbackQueryHandler(order_confirm, pattern=r"^confirm:")
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price_list))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot启动成功")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
