import os
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ConversationHandler, ContextTypes
)
import httpx
import asyncio

app = Flask(__name__)
bot_token = os.getenv("BOT_TOKEN")
bot = Bot(token=bot_token)

# Define constants
LANGUAGE, WIDTH, LENGTH, HEIGHT, THICKNESS, QUANTITY, BOXTYPE = range(7)
STRATEGY_COEFFICIENTS = {"Complex": 2.8, "Assembly": 2.5, "Routine": 2.0, "Competitive": 1.6, "Discount": 0.8}
MATERIAL_COST_PER_MM3 = 0.000002

TEXTS = {
    "en": {
        "welcome": "Welcome! Please choose your language:",
        "enter_width": "Enter WIDTH in mm:",
        "enter_length": "Enter LENGTH in mm:",
        "enter_height": "Enter HEIGHT in mm:",
        "enter_thickness": "Enter sheet THICKNESS in mm:",
        "enter_quantity": "Enter QUANTITY of boxes:",
        "choose_boxtype": "Choose BOX TYPE:",
        "calculating": "Calculating... Please wait...",
        "final_price": "Pricing Strategy: {strategy}\nFinal Price (approximate): {price:.2f} Toman",
        "cancelled": "Cancelled.",
        "box_types": [["lightbox", "container", "cover", "lasercut"]],
    },
    "fa": {
        "welcome": "خوش آمدید! لطفاً زبان خود را انتخاب کنید:",
        "enter_width": "عرض را وارد کنید (میلیمتر):",
        "enter_length": "طول را وارد کنید (میلیمتر):",
        "enter_height": "ارتفاع را وارد کنید (میلیمتر):",
        "enter_thickness": "ضخامت ورق را وارد کنید (میلیمتر):",
        "enter_quantity": "تعداد جعبه‌ها را وارد کنید:",
        "choose_boxtype": "نوع جعبه را انتخاب کنید:",
        "calculating": "در حال محاسبه... لطفاً صبر کنید...",
        "final_price": "استراتژی قیمت‌گذاری: {strategy}\nقیمت تقریبی: {price:.2f} تومان",
        "cancelled": "لغو شد.",
        "box_types": [["لایت‌باکس", "کانتینر", "پوشش", "برش لیزری"]],
    }
}

# Temporary in-memory user data
user_data = {}

# --- Conversation Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["English", "فارسی"]]
    await update.message.reply_text(
        TEXTS["en"]["welcome"],
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return LANGUAGE

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = "fa" if "فارسی" in update.message.text else "en"
    context.user_data["lang"] = lang
    await update.message.reply_text(TEXTS[lang]["enter_width"])
    return WIDTH

async def get_width(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['width'] = float(update.message.text)
    lang = context.user_data["lang"]
    await update.message.reply_text(TEXTS[lang]["enter_length"])
    return LENGTH

async def get_length(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['length'] = float(update.message.text)
    lang = context.user_data["lang"]
    await update.message.reply_text(TEXTS[lang]["enter_height"])
    return HEIGHT

async def get_height(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['height'] = float(update.message.text)
    lang = context.user_data["lang"]
    await update.message.reply_text(TEXTS[lang]["enter_thickness"])
    return THICKNESS

async def get_thickness(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['thickness'] = float(update.message.text)
    lang = context.user_data["lang"]
    await update.message.reply_text(TEXTS[lang]["enter_quantity"])
    return QUANTITY

async def get_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['quantity'] = int(update.message.text)
    lang = context.user_data["lang"]
    await update.message.reply_text(
        TEXTS[lang]["choose_boxtype"],
        reply_markup=ReplyKeyboardMarkup(TEXTS[lang]["box_types"], one_time_keyboard=True)
    )
    return BOXTYPE

async def get_boxtype(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['boxtype'] = update.message.text
    lang = context.user_data["lang"]
    await update.message.reply_text(TEXTS[lang]["calculating"])

    strategy = await get_pricing_strategy_from_ai(context.user_data)
    if strategy not in STRATEGY_COEFFICIENTS:
        strategy = "Routine"

    context.user_data['strategy'] = strategy
    price = calculate_price(context.user_data)

    await update.message.reply_text(TEXTS[lang]["final_price"].format(strategy=strategy, price=price))
    return ConversationHandler.END

async def get_pricing_strategy_from_ai(data):
    prompt = f"""
You are a factory pricing expert. Given the following:
Width: {data['width']}mm, Length: {data['length']}mm, Height: {data['height']}mm,
Thickness: {data['thickness']}mm, Quantity: {data['quantity']}, Box Type: {data['boxtype']}

Choose a pricing strategy:
1. Complex → 280%
2. Assembly → 250%
3. Routine → 200%
4. Competitive → 160%

Return ONLY one word: Complex, Assembly, Routine, Competitive.
"""
    headers = {
        "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY')}",
        "HTTP-Referer": "https://price-automation-mehrbodcrud285-dzfy6c16.leapcell.dev",
        "X-Title": "Box Pricing Bot"
    }

    body = {
        "model": "openai/gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    }

    async with httpx.AsyncClient() as client:
        response = await client.post("https://openrouter.ai/api/v1/chat/completions", json=body, headers=headers)
        result = response.json()
        return result['choices'][0]['message']['content'].strip()

def calculate_price(data):
    w, l, h, t, qty = data['width'], data['length'], data['height'], data['thickness'], data['quantity']
    face_area = 2 * (w*l + w*h + l*h)
    volume = face_area * t
    total_volume = volume * qty
    material_cost = total_volume * MATERIAL_COST_PER_MM3
    box_type_cost = get_box_type_extra_cost(data['boxtype'], w, l, h, qty)
    return (material_cost + box_type_cost) * STRATEGY_COEFFICIENTS[data['strategy']]

def get_box_type_extra_cost(box_type, w, l, h, qty):
    box_type = box_type.lower()
    if box_type in ["lightbox", "لایت‌باکس"]:
        perimeter = 2 * (w + h) / 100
        led_cost = perimeter * 0.5
        transformer_cost = (qty // 2 + 1) * 5
        return (led_cost + transformer_cost) * qty
    elif box_type in ["container", "کانتینر"]:
        return (2 * 0.8 + 1.2 + 2.5) * qty
    elif box_type in ["cover", "پوشش"]:
        return 3.0 * qty
    elif box_type in ["lasercut", "برش لیزری"]:
        return 4 * (w + h + l) * 0.002 * qty
    return 0

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "en")
    await update.message.reply_text(TEXTS[lang]["cancelled"])
    return ConversationHandler.END

# --- Telegram Webhook Route ---
@app.route(f"/webhook/{bot_token}", methods=["POST"])
def telegram_webhook():
    update = Update.de_json(request.get_json(force=True), bot)
    asyncio.run(application.update_queue.put(update))
    return "ok"

# --- Setup Telegram Bot Handlers ---
application: Application = ApplicationBuilder().token(bot_token).build()

conv_handler = ConversationHandler(
    entry_points=[CommandHandler('start', start)],
    states={
        LANGUAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_language)],
        WIDTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_width)],
        LENGTH: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_length)],
        HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_height)],
        THICKNESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_thickness)],
        QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_quantity)],
        BOXTYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_boxtype)],
    },
    fallbacks=[CommandHandler('cancel', cancel)]
)

application.add_handler(conv_handler)

# --- Start Flask + Telegram ---
if __name__ == "__main__":
    import threading
    threading.Thread(target=application.run_webhook, kwargs={
        "listen": "0.0.0.0",
        "port": int(os.getenv("PORT", 8000)),
        "webhook_url": f"https://price-automation-mehrbodcrud285-dzfy6c16.leapcell.dev/webhook/{bot_token}"
    }).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
