import os
import json
import requests
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes
from telegram.ext.filters import TEXT, COMMAND
import asyncio
import time
import math  # Added for ceil

# Initialize Flask app
app = Flask(__name__)

# Initialize Telegram application
telegram_token = os.environ["TELEGRAM_TOKEN"]
webhook_url = os.environ["WEBHOOK_URL"]
openrouter_api_key = os.environ["OPENROUTER_API_KEY"]
application = Application.builder().token(telegram_token).build()

# Pricing coefficients
PRICING_STRATEGIES = {
    "Complex work or low quantity": 2.8,
    "Assembly required, more quantity": 2.5,
    "Routine assembly, large quantity": 2.0,
    "Competitive pricing": 1.6,
    "Discount": 0.8
}

# Store user data
user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Light Box", callback_data="lightbox"),
         InlineKeyboardButton("Container Box", callback_data="container")],
        [InlineKeyboardButton("Protection Case", callback_data="protection"),
         InlineKeyboardButton("Laser Cut", callback_data="laser_cut")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select box type:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data[user_id] = {"box_type": query.data}
    if query.data == "laser_cut":
        await query.message.reply_text("Enter width, length, thickness, quantity (e.g., 1200 1800 3 10):")
    else:
        await query.message.reply_text("Enter width, length, height, thickness, quantity (e.g., 1200 1800 100 3 10):")
    if query.data == "container":
        await query.message.reply_text("Include lock? Reply 'yes' or 'no'.")
    elif query.data == "protection":
        keyboard = [[InlineKeyboardButton("Countertop Base", callback_data="base"),
                    InlineKeyboardButton("Side Back", callback_data="side_back")]]
        await query.message.reply_text("Select installation solution:", reply_markup=InlineKeyboardMarkup(keyboard))

async def installation_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data[user_id]["installation"] = query.data
    await query.message.reply_text("Now enter width, length, height, thickness, quantity (e.g., 1200 1800 100 3 10):")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    data = user_data.get(user_id, {})
    text = update.message.text.strip().lower()

    if "box_type" in data and "dimensions" not in data:
        try:
            dims = [float(x) for x in text.split()]
            if data["box_type"] == "laser_cut" and len(dims) == 4:
                data["width"], data["length"], data["thickness"], data["quantity"] = dims
            elif len(dims) == 5:
                data["width"], data["length"], data["height"], data["thickness"], data["quantity"] = dims
            else:
                await update.message.reply_text("Invalid input. Please provide correct number of dimensions.")
                return
            data["quantity"] = int(data["quantity"])
            data["dimensions"] = True
        except ValueError:
            await update.message.reply_text("Invalid input. Please use numbers (e.g., 1200 1800 100 3 10).")
            return

    if data.get("box_type") == "container" and "lock" not in data:
        data["lock"] = (text == "yes")
        user_data[user_id] = data
        return

    # Calculate price
    result = calculate_price(data)
    strategy = result["pricing_strategy"]
    await update.message.reply_text(
        f"Box Type: {data['box_type']}\n"
        f"Material Cost: ${result['material_cost']:.2f}\n"
        f"Component Cost: ${result['component_cost']:.2f}\n"
        f"Pricing Strategy: {strategy} ({result['coefficient']*100:.0f}%)\n"
        f"Total Price: ${result['total_price']:.2f}"
    )
    user_data[user_id] = {}  # Reset for next calculation

def calculate_price(data):
    box_type = data["box_type"]
    w, l, t, q = data["width"], data["length"], data["thickness"], data["quantity"]
    h = data.get("height", 0)
    material_cost_per_mm3 = 0.001

    # Material cost
    if box_type == "laser_cut":
        surface_area = w * l
        material_volume = surface_area * t
    elif box_type == "protection":
        surface_area = w * l + 2 * (w * h + l * h)
        material_volume = surface_area * t
    else:  # lightbox, container
        surface_area = 2 * (w * l + w * h + l * h)
        material_volume = surface_area * t
    material_cost = material_volume * material_cost_per_mm3 * q

    # Component cost
    component_cost = 0
    if box_type == "lightbox":
        leds = math.ceil((w * l) / 50000)  # Fixed ceiling calculation
        power = leds * 10
        transformers = math.ceil(power / 100)  # Fixed ceiling calculation
        wire_length = 2 * (w + l)  # Simplified and corrected
        component_cost = q * (leds * 5 + transformers * 20 + wire_length * 0.1)
    elif box_type == "container":
        component_cost = q * (6 + (10 if data.get("lock") else 0))
    elif box_type == "protection":
        component_cost = q * (15 if data.get("installation") == "base" else 10)
    elif box_type == "laser_cut":
        cut_length = 2 * (w + l) / 1000  # meters
        component_cost = q * (cut_length * 0.5)  # Fixed parenthesis

    # AI pricing strategy
    strategy_data = get_ai_pricing_strategy(w, l, h, t, q, box_type)
    coefficient = strategy_data["coefficient"]

    return {
        "material_cost": material_cost,
        "component_cost": component_cost,
        "pricing_strategy": strategy_data["strategy"],
        "coefficient": coefficient,
        "total_price": (material_cost + component_cost) * coefficient
    }

def get_ai_pricing_strategy(width, length, height, thickness, quantity, box_type):
    prompt = f"""
    You are a pricing strategy expert. Given:
    - Width: {width} mm
    - Length: {length} mm
    - Height: {height} mm
    - Thickness: {thickness} mm
    - Quantity: {quantity}
    - Box Type: {box_type}
    
    Choose a pricing strategy:
    1. Complex work or low quantity: 280% (2.8)
    2. Assembly required, more quantity: 250% (2.5)
    3. Routine assembly, large quantity: 200% (2.0)
    4. Competitive pricing: 160% (1.6)
    5. Discount: 80% (0.8)
    
    Consider: low quantity (≤10), medium (11-50), high (>50); lightbox is complex, protection/laser cut simpler. Return JSON:
    ```json
    {{"strategy": "<strategy_name>", "coefficient": <coefficient>}}
    ```
    """

    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": os.environ["WEBHOOK_URL"],
                "X-Title": "Box Pricing Bot"
            },
            json={
                "model": "openai/gpt-3.5-turbo",
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            }
        )
        response.raise_for_status()
        return json.loads(response.json()["choices"][0]["message"]["content"])
    except Exception as e:
        print(f"Error in AI call: {e}")
        return {"strategy": "Competitive pricing", "coefficient": 1.6}

# Webhook route
@app.route('/webhook', methods=['POST'])
async def webhook():
    update = Update.de_json(request.get_json(), application.bot)
    await application.process_update(update)
    return jsonify({"status": "ok"})

# Health check endpoints for LeapCell
@app.route('/kaithhealthcheck', methods=['GET'])
@app.route('/kaithheathcheck', methods=['GET'])
def healthcheck():
    return jsonify({"status": "healthy"}), 200

# Set webhook with retry logic
async def set_webhook():
    max_retries = 5
    retry_delay = 5  # seconds
    for attempt in range(max_retries):
        try:
            await application.bot.set_webhook(url=webhook_url)
            print(f"Webhook set to {webhook_url}")
            return
        except Exception as e:
            print(f"Retry {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
    print("Failed to set webhook after retries")

if __name__ == '__main__':
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button, pattern="^(lightbox|container|protection|laser_cut)$"))
    application.add_handler(CallbackQueryHandler(installation_button, pattern="^(base|side_back)$"))
    application.add_handler(MessageHandler(TEXT & ~COMMAND, handle_message))

    # Initialize application and set webhook
    import asyncio
    asyncio.run(set_webhook())

    # Run Flask app
    app.run(host='0.0.0.0', port=8080)  # Match LeapCell port