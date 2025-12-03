import logging
import json
import os
from datetime import datetime
import random
import asyncio
from urllib.parse import quote

from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler,
    ContextTypes,
)
from sheets_db import (
    add_order, get_user_orders, get_all_orders,
    add_worker, get_all_workers, is_worker, update_order_status,
    get_worker_orders, get_order_by_id, get_all_unique_users,
    add_payment, get_all_payments, add_feedback, get_all_feedback, get_orders_by_status,
    add_or_update_user, get_workers_by_status, update_worker_status
)
from messages import (
    SHARE_MESSAGE, RAINY, COLD, HOT, SUNDAY, CASUAL, FAQ_MESSAGE
)

# Fixed fees
PACK_FEE = 300

# Centralized price list for all items, using underscores for consistency
PRICES = {
    # Indomie base prices
    "small_chicken": 400,
    "super_chicken": 500,
    "small_onion_chicken": 450,
    "super_onion_chicken": 600,

    # Mixings & Toppings
    "pepper_spice": 200,
    "crayfish_spice": 200,
    "vegetables": 800,
    "suya": 1,  # Special case: price is the quantity
    "egg": 400,
    "sausage": 400,
    "sardine": 1900,
    "chicken_1000": 1000,
    "chicken_1500": 1500,
    "chicken_3000": 3000,
    "fried_fish": 1500,

    # Beverages
    "water": 300,
    "soft_drink": 600,
    "malt": 800,
    "1ltr_drink": 2500,
    "ice": 250,

    # Custard items
    "custard": 300,
    "sugar": 50,
    "milk": 400,
}


def get_worker_payout(service_charge: int) -> int:
    """Calculates the worker's payout based on the service charge."""
    if 200 <= service_charge <= 300:
        return 150
    elif 400 <= service_charge <= 500:
        return 200
    elif 600 <= service_charge <= 700:
        return 250
    elif 800 <= service_charge <= 900:
        return 300
    elif 900 <= service_charge <= 1000:
        return 350
    return 0 # Default payout if no range matches


def format_date(iso_date_str):
    """Formats an ISO date string to 'Www, DDth Mmm, YYYY at hh:mmam/pm' format."""
    if not iso_date_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(iso_date_str)
        day = dt.day
        if 4 <= day <= 20 or 24 <= day <= 30:
            suffix = "th"
        else:
            suffix = ["st", "nd", "rd"][day % 10 - 1]
        
        formatted_date = dt.strftime(f"%a, {day}{suffix} %b, %Y at %I:%M%p").lower()
        return formatted_date
    except (ValueError, TypeError):
        return iso_date_str


async def get_order_summary_for_worker(order: dict, for_admin=False) -> str:
    """Generates a detailed order summary for workers and admins."""
    summary = f"<b>Customer Name:</b> {order.get('first_name', 'N/A')}\n"
    summary += f"<b>Customer Username:</b> @{order.get('username', 'N/A')}\n"
    
    try:
        delivery_info = json.loads(order.get('delivery_info', '{}'))
    except json.JSONDecodeError:
        delivery_info = {}
    summary += f"<b>Room Number:</b> {delivery_info.get('hall_and_room_number', 'N/A')}\n\n"
    
    summary += "<b>Items Ordered:</b>\n"
    try:
        items = json.loads(order.get('items', '[]'))
    except json.JSONDecodeError:
        items = []
    for item in items:
        item_name = item.get('name', 'N/A').replace('_', ' ').title()
        summary += f"- {item_name} (x{item.get('quantity', 0)}) = ₦{item.get('total_price', 0)}\n"
        
    if order.get('notes'):
        summary += f"\n<b>Additional Notes:</b> {order.get('notes')}\n"
        
    try:
        service_charge = int(order.get('service_charge', 0))
    except (ValueError, TypeError):
        service_charge = 0
    worker_payout = get_worker_payout(service_charge)
    
    if order.get('food_type') == 'Cafe Order':
        if for_admin:
            summary += f"\n<b>Service Charge:</b> ₦{service_charge}\n"
        summary += f"<b>Worker Payout:</b> ₦{worker_payout}\n"
    elif for_admin: # For Kitchen Orders, only admin sees service charge
        summary += f"\n<b>Service Charge:</b> ₦{service_charge}\n"

    return summary


async def get_order_summary_for_customer(order: dict) -> str:
    """Generates a detailed order summary for the customer, excluding worker payout."""
    summary = f"<b>Order for:</b> {order.get('first_name', 'N/A')} (@{order.get('username', 'N/A')})\n\n"
    summary += "<b>Full Order Summary:</b>\n\n"
    
    summary += "<b>Items Ordered:</b>\n"
    items_str = order.get('items', '[]')
    try:
        items = json.loads(items_str)
    except json.JSONDecodeError:
        items = []
    for item in items:
        item_name = item.get('name', 'N/A').replace('_', ' ').title()
        summary += f"- {item_name} (x{item.get('quantity', 0)}) = ₦{item.get('total_price', 0)}\n"
        
    if order.get('notes'):
        summary += f"\n<b>Additional Notes:</b> {order.get('notes')}\n"
        
    delivery_info_str = order.get('delivery_info', '{}')
    try:
        delivery_info = json.loads(delivery_info_str)
    except json.JSONDecodeError:
        delivery_info = {}
    summary += f"\n<b>Room:</b> {delivery_info.get('hall_and_room_number', 'N/A')}\n"
        
    total = order.get('total', 0)
    summary += f"<b>Total: ₦{total}</b>"
    
    return summary


async def send_or_edit_message(update: Update, text: str, reply_markup=None, parse_mode: str = None):
    """
    Sends a new message or edits an existing one, depending on the update type.
    """
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Your Telegram Bot Token & Admin ID
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# States
(
    MAIN_MENU,
    KITCHEN_MENU,
    INDOMIE_MIXINGS,
    INDOMIE_TOPPINGS,
    INDOMIE_VEGETABLES_QUANTITY,
    INDOMIE_SUYA_AMOUNT,
    CUSTARD_QUANTITY,
    CUSTARD_SOURCE,
    CUSTARD_ADDITIONS,
    CUSTARD_SUGAR_QUANTITY,
    CUSTARD_MILK_QUANTITY,
    ADMIN_PASSWORD,
    ADMIN_MENU,
    ORDER_SUMMARY,
    CAFE_ORDER,
    WORKER_NAME,
    WORKER_REG_NO,
    WORKER_MATRIC_NO,
    WORKER_PHONE,
    WORKER_HISTORY,
    GET_ROOM_NUMBER,
    GET_DELIVERY_TIME,
    GET_PAYMENT_SCREENSHOT,
    INDOMIE_BEVERAGES,
    CUSTOMER_FEEDBACK,
    INDOMIE_FLAVOR,
    INDOMIE_SIZE,
    INDOMIE_QUANTITY,
    INDOMIE_NOTES,
    INDOMIE_SARDINE_QUANTITY,
    INDOMIE_EGG_QUANTITY,
    INDOMIE_SAUSAGE_QUANTITY,
    INDOMIE_CHICKEN_1000_QUANTITY,
    INDOMIE_CHICKEN_1500_QUANTITY,
    INDOMIE_CHICKEN_3000_QUANTITY,
    INDOMIE_FRIED_FISH_QUANTITY,
    INDOMIE_MALT_QUANTITY,
    INDOMIE_COKE_QUANTITY,
    INDOMIE_JUICE_QUANTITY,
    INDOMIE_WATER_QUANTITY,
    ASK_BEVERAGE,
    GET_EXTRA_NOTES,
    ADMIN_CHECKIN_MENU,
    ADMIN_CUSTOM_MESSAGE_PROMPT,
    ADMIN_VIEW_ORDER_DETAIL,
    INDOMIE_ICE_QUANTITY,
    GET_DELIVERY_ISSUE,
    WORKER_GENDER,
    WORKER_BANK_NAME,
    WORKER_ACCOUNT_NUMBER,
    WORKER_ACCOUNT_NAME,
    INDOMIE_SOURCE,
) = range(52)


async def start(update: Update, context: CallbackContext) -> int:
    """Displays the main menu and logs the user."""
    user = update.effective_user
    add_or_update_user(user.id, user.username, user.first_name)

    keyboard = [
        [InlineKeyboardButton("🧑‍🍳 From Our Kitchen", callback_data="kitchen_menu")],
        [InlineKeyboardButton("☕ From Café", callback_data="cafe_menu")],
        [InlineKeyboardButton("👀 View My Orders", callback_data="view_orders")],
        [InlineKeyboardButton("🤔 FAQ's", callback_data="faq")],
        [InlineKeyboardButton("🚀 Share Bot", callback_data="share_bot")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = "Welcome to Willis Kitchen 🍽️\nWhere would you like to order from?"

    if update.callback_query:
        await send_or_edit_message(update, welcome_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)

    return MAIN_MENU


async def faq_handler(update: Update, context: CallbackContext) -> int:
    """Displays the FAQ message."""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_or_edit_message(update, FAQ_MESSAGE, reply_markup=reply_markup)
    return MAIN_MENU


async def kitchen_menu(update: Update, context: CallbackContext) -> int:
    """Displays the food options."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🍜 Indomie", callback_data="indomie")],
        [InlineKeyboardButton("☕ Custard", callback_data="custard")],
        [InlineKeyboardButton("🍝 Spaghetti", callback_data="spaghetti")],
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_or_edit_message(
        update, "Please choose a food option from our kitchen:", reply_markup=reply_markup
    )
    return KITCHEN_MENU


async def cafe_menu(update: Update, context: CallbackContext) -> int:
    """Initializes the Cafe order."""
    query = update.callback_query
    await query.answer()
    context.user_data["order"] = {
        "food": "Cafe Order",
        "items": [],
        "source": "cafe",
    }
    await send_or_edit_message(
        update,
        "Please send each item you want to order in the format: `Item, Quantity, Total Price`.\n\n"
        "Example: `Meat Pie, 2, 1600`\n\n"
        "Send `/done` when you have added all your items."
    )
    return CAFE_ORDER


async def cafe_order(update: Update, context: CallbackContext) -> int:
    """Parses a single cafe item and adds it to the items list."""
    order_text = update.message.text
    try:
        parts = order_text.split(",")
        item_name = parts[0].strip()
        quantity = int(parts[1].strip())
        total_price = int("".join(filter(str.isdigit, parts[2])))
        unit_price = total_price / quantity if quantity > 0 else 0
    except (ValueError, IndexError, ZeroDivisionError):
        await update.message.reply_text("Invalid format. Please use 'Item, Quantity, Total Price'.")
        return CAFE_ORDER

    order = context.user_data["order"]
    items = order.get("items", [])
    items.append({
        "name": item_name,
        "type": "cafe_item",
        "unit_price": unit_price,
        "quantity": quantity,
        "total_price": total_price,
    })

    await update.message.reply_text(f"Added: {item_name}. Add another item or send /done.")
    return CAFE_ORDER


async def cafe_order_done(update: Update, context: CallbackContext) -> int:
    """Finalizes the cafe order and calculates totals."""
    order = context.user_data["order"]
    items = order.get("items", [])

    if not items:
        await update.message.reply_text("You haven't added any items yet.")
        return CAFE_ORDER

    return await ask_for_extra_notes(update, context)


# Hostel keywords for gender-based delivery logic
MALE_HOSTEL_KEYWORDS = ["daniel", "peter", "joseph", "paul", "john"]
FEMALE_HOSTEL_KEYWORDS = ["esther", "mary", "lydia", "dorcas", "deborah"]

async def notify_workers(context: CallbackContext, order_id: int):
    """Notifies relevant workers of a new Cafe order based on gender and location."""
    order = get_order_by_id(order_id)
    if not order or order.get('food_type') != 'Cafe Order':
        return

    try:
        delivery_info = json.loads(order.get('delivery_info', '{}'))
        location = delivery_info.get('hall_and_room_number', '').lower()
    except (json.JSONDecodeError, AttributeError):
        location = ""

    target_gender = None
    if any(keyword in location for keyword in MALE_HOSTEL_KEYWORDS):
        target_gender = "male"
    elif any(keyword in location for keyword in FEMALE_HOSTEL_KEYWORDS):
        target_gender = "female"

    if not target_gender:
        return

    all_workers = get_all_workers()
    eligible_workers = [w for w in all_workers if w.get('gender') == target_gender]
    
    summary = await get_order_summary_for_worker(order)
    keyboard = [[InlineKeyboardButton("✅ Review Order", callback_data=f"review_{order_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    for worker in eligible_workers:
        worker_id = worker.get('user_id')
        if worker_id:
            try:
                await context.bot.send_message(chat_id=worker_id, text=summary, reply_markup=reply_markup, parse_mode='HTML')
            except Exception as e:
                logger.error(f"Failed to send message to worker {worker_id}: {e}")


async def notify_admin_of_new_kitchen_order(context: CallbackContext, order_id: int):
    """Notifies the admin of a new Kitchen Order."""
    order = get_order_by_id(order_id)
    
    if not order or order.get('food_type') not in ["Indomie", "Custard"]:
        return
        
    summary = await get_order_summary_for_worker(order, for_admin=True)
    message = f"🍜 New Kitchen Order:\n\n{summary}"
    
    keyboard = [[InlineKeyboardButton("✅ Review Order", callback_data=f"review_{order_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=message, reply_markup=reply_markup, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Failed to send new kitchen order notification to admin: {e}")


async def notify_admin_of_accepted_order(context: CallbackContext, order_id: int, worker_id: int):
    """Notifies the admin when any order has been accepted."""
    order = get_order_by_id(order_id)
    worker = next((w for w in get_all_workers(approved_only=False) if w.get('user_id') == worker_id), None)
    
    if not order or not worker:
        return
        
    worker_name = worker.get('name', 'N/A')
    food_type = order.get('food_type', 'N/A')
    
    message = (
        f"👍 Order Accepted:\n"
        f"Order ID: {order_id}\n"
        f"Type: {food_type}\n"
        f"Accepted by: {worker_name} (@{worker.get('username', 'N/A')})"
    )
    
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=message)
    except Exception as e:
        logger.error(f"Failed to send accepted order notification to admin: {e}")


async def work_with_us_command(update: Update, context: CallbackContext) -> int:
    """Starts the worker application process via command."""
    await update.message.reply_text("Please enter your full name:")
    return WORKER_NAME


async def worker_name(update: Update, context: CallbackContext) -> int:
    context.user_data["worker_application"] = {"name": update.message.text}
    await update.message.reply_text("Please enter your registration number:")
    return WORKER_REG_NO


async def worker_reg_no(update: Update, context: CallbackContext) -> int:
    context.user_data["worker_application"]["reg_no"] = update.message.text
    await update.message.reply_text("Please enter your matric number:")
    return WORKER_MATRIC_NO


async def worker_matric_no(update: Update, context: CallbackContext) -> int:
    context.user_data["worker_application"]["matric_no"] = update.message.text
    await update.message.reply_text("Please enter your phone number:")
    return WORKER_PHONE


async def worker_phone(update: Update, context: CallbackContext) -> int:
    context.user_data["worker_application"]["phone"] = update.message.text
    keyboard = [
        [InlineKeyboardButton("Male", callback_data="gender_male")],
        [InlineKeyboardButton("Female", callback_data="gender_female")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Please select your gender:", reply_markup=reply_markup)
    return WORKER_GENDER


async def worker_gender(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    gender = query.data.split("_")[-1]
    context.user_data["worker_application"]["gender"] = gender
    await send_or_edit_message(update, "Please enter your Bank Name:")
    return WORKER_BANK_NAME

async def worker_bank_name(update: Update, context: CallbackContext) -> int:
    context.user_data["worker_application"]["bank_name"] = update.message.text
    await update.message.reply_text("Please enter your Account Number:")
    return WORKER_ACCOUNT_NUMBER

async def worker_account_number(update: Update, context: CallbackContext) -> int:
    context.user_data["worker_application"]["account_number"] = update.message.text
    await update.message.reply_text("Please enter your Account Name:")
    return WORKER_ACCOUNT_NAME

async def worker_account_name(update: Update, context: CallbackContext) -> int:
    """Saves the worker application and notifies the admin."""
    context.user_data["worker_application"]["account_name"] = update.message.text
    
    application_data = context.user_data["worker_application"]
    user = update.effective_user

    add_worker(
        user_id=user.id,
        name=application_data.get('name'),
        reg_no=application_data.get('reg_no'),
        matric_no=application_data.get('matric_no'),
        phone=application_data.get('phone'),
        gender=application_data.get('gender'),
        bank_name=application_data.get('bank_name'),
        account_number=application_data.get('account_number'),
        account_name=application_data.get('account_name'),
        status='pending'
    )

    admin_message = (
        f"🧑‍🍳 New Worker Application:\n"
        f"Name: {application_data.get('name')}\n"
        f"User: @{user.username}\n"
        f"Phone: {application_data.get('phone')}\n"
        f"Gender: {application_data.get('gender', '').title()}\n"
        f"Bank: {application_data.get('bank_name')} - {application_data.get('account_number')}\n\n"
        "You can approve or reject this from the /admin panel."
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message)

    await update.message.reply_text(
        "✅ Thank you for applying to become a Willis Kitchen worker.\n"
        "Your application is pending review."
    )
    return ConversationHandler.END


async def share_command(update: Update, context: CallbackContext) -> None:
    bot_link = f"https://t.me/{context.bot.username}"
    share_text = quote(SHARE_MESSAGE)
    share_url_telegram = f"https://t.me/share/url?url={bot_link}&text={share_text}"
    share_url_whatsapp = f"https://api.whatsapp.com/send?text={share_text} {bot_link}"
    keyboard = [
        [InlineKeyboardButton("Share on Telegram 🚀", url=share_url_telegram)],
        [InlineKeyboardButton("Share on WhatsApp 🟢", url=share_url_whatsapp)],
        [InlineKeyboardButton("Copy Message 📋", callback_data="copy_share_message")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await send_or_edit_message(update, SHARE_MESSAGE, reply_markup=reply_markup)
    else:
        await update.message.reply_text(SHARE_MESSAGE, reply_markup=reply_markup)


async def copy_share_message_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Copied ✅", show_alert=True)


async def back_to_kitchen_menu(update: Update, context: CallbackContext) -> int:
    return await kitchen_menu(update, context)


async def ask_for_hall_and_room_number(update: Update, context: CallbackContext) -> int:
    prompt = "Please enter your hall and room number (e.g., Peter Hall B204):"
    if update.callback_query:
        await send_or_edit_message(update, prompt)
    else:
        await update.message.reply_text(prompt)
    return GET_ROOM_NUMBER


async def get_hall_and_room_number(update: Update, context: CallbackContext) -> int:
    hall_and_room_number = update.message.text
    if not hall_and_room_number:
        await update.message.reply_text("Hall and room number cannot be empty. Please try again.")
        return GET_ROOM_NUMBER
    context.user_data["order"]["hall_and_room_number"] = hall_and_room_number
    await update.message.reply_text("What time would you like your order to be delivered?")
    return GET_DELIVERY_TIME


async def get_delivery_time(update: Update, context: CallbackContext) -> int:
    context.user_data["order"]["delivery_time"] = update.message.text
    return await show_order_summary(update, context)


async def get_extra_notes(update: Update, context: CallbackContext) -> int:
    if update.message and update.message.text and update.message.text.lower() == '/skip':
        context.user_data["order"]["notes"] = None
    elif update.message and update.message.text:
        context.user_data["order"]["notes"] = update.message.text
    else:
        context.user_data["order"]["notes"] = None
    return await ask_for_hall_and_room_number(update, context)


async def ask_for_extra_notes(update: Update, context: CallbackContext) -> int:
    message = "Would you like to add any extra notes for the chef or delivery person? (Type /skip if none)"
    if update.callback_query:
        await send_or_edit_message(update, message)
    else:
        await update.message.reply_text(message)
    return GET_EXTRA_NOTES


async def working_history(update: Update, context: CallbackContext) -> int:
    """Displays the worker history menu."""
    user_id = update.effective_user.id
    if not is_worker(user_id):
        await update.message.reply_text("You are not an approved worker.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("📦 Orders Taken", callback_data="view_taken_orders")],
        [InlineKeyboardButton("✅ Orders Accepted", callback_data="view_accepted_orders")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Your Worker History:", reply_markup=reply_markup)
    return WORKER_HISTORY


async def view_worker_orders(update: Update, context: CallbackContext) -> int:
    """Displays the worker's orders based on the selected status."""
    query = update.callback_query
    await query.answer()
    status = query.data.split("_")[1]
    worker_id = update.effective_user.id
    orders = get_worker_orders(worker_id, status)
    if not orders:
        await send_or_edit_message(update, f"You have no {status} orders.")
        return WORKER_HISTORY
    message = f"📦 Your {status.capitalize()} Orders:\n"
    for order in orders:
        food_type = order.get('food_type', 'N/A')
        total = order.get('total', 0)
        order_date = format_date(order.get('order_date', 'N/A'))
        message += f"📅 {order_date} - {food_type} - ₦{total}\n"
    await send_or_edit_message(update, message)
    return WORKER_HISTORY


async def worker_accept_order(update: Update, context: CallbackContext) -> None:
    """Handles a worker or admin accepting an order."""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[-1])
    worker_id = update.effective_user.id
    order = get_order_by_id(order_id)

    if not order or order.get('status') != 'pending':
        await send_or_edit_message(update, "This order has already been taken or is no longer available.")
        return

    update_order_status(order_id, 'taken', worker_id)

    # Notify admin if a worker accepted it
    if worker_id != ADMIN_ID:
        await notify_admin_of_accepted_order(context, order_id, worker_id)

    # --- Worker/Admin Flow ---
    # 1. Remove buttons from original message
    await query.edit_message_reply_markup(reply_markup=None)
    # 2. Send confirmation message
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"✅ You have accepted order #{order_id}."
    )
    # 3. Send new message with details and action buttons
    worker_summary = await get_order_summary_for_worker(order, for_admin=(worker_id == ADMIN_ID))
    worker_keyboard = [
        [InlineKeyboardButton("✅ Order Delivered", callback_data=f"worker_delivered_{order_id}")],
        [InlineKeyboardButton("❌ Not Delivered", callback_data=f"worker_not_delivered_{order_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(worker_keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=worker_summary,
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

    # --- User Flow ---
    user_id = order.get('user_id')
    if user_id:
        try:
            # 1. Send acceptance notification
            await context.bot.send_message(chat_id=user_id, text="Your order has been accepted 🎉")
            # 2. Send new message with summary and action buttons
            user_summary = await get_order_summary_for_customer(order)
            user_keyboard = [
                [InlineKeyboardButton("✅ Order Delivered", callback_data=f"user_delivered_{order_id}")],
                [InlineKeyboardButton("❌ Not Delivered", callback_data=f"user_not_delivered_{order_id}")],
            ]
            user_reply_markup = InlineKeyboardMarkup(user_keyboard)
            await context.bot.send_message(
                chat_id=user_id,
                text=user_summary,
                reply_markup=user_reply_markup,
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Failed to send order acceptance notification to user {user_id}: {e}")


async def decline_order(update: Update, context: CallbackContext) -> int:
    """Handles an admin declining an order."""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[-1])
    update_order_status(order_id, 'rejected')

    await query.edit_message_text(f"You have rejected order #{order_id}.")

    # Notify user
    order = get_order_by_id(order_id)
    if order and order.get('user_id'):
        user_id = order.get('user_id')
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Unfortunately, your order #{order_id} has been declined by the admin."
            )
        except Exception as e:
            logger.error(f"Failed to send order decline notification to user {user_id}: {e}")

    return ADMIN_MENU


async def worker_delivered_order(update: Update, context: CallbackContext) -> None:
    """Handles a worker marking an order as delivered."""
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[-1])
    worker_id = update.effective_user.id
    order = get_order_by_id(order_id)

    if order:
        try:
            service_charge = int(order.get('service_charge', 0))
        except (ValueError, TypeError):
            service_charge = 0
        payout = get_worker_payout(service_charge)
        if payout > 0:
            update_worker_payout(worker_id, order_id, payout)

    update_order_status(order_id, 'completed')

    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="You have marked this order as delivered.")


async def worker_not_delivered_order(update: Update, context: CallbackContext) -> None:
    """Handles a worker marking an order as not delivered."""
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[-1])
    update_order_status(order_id, 'issue_reported')

    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="You have marked this order as not delivered. The admin will be notified.")


async def user_delivered_order(update: Update, context: CallbackContext) -> None:
    """Handles a user marking an order as delivered."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Thank you! Your order has been completed. We hope to serve you again!")


async def user_not_delivered_order(update: Update, context: CallbackContext) -> int:
    """Asks the user to explain the delivery issue."""
    query = update.callback_query
    await query.answer()
    
    order_id = int(query.data.split("_")[-1])
    context.user_data["issue_order_id"] = order_id
    
    await query.edit_message_reply_markup(reply_markup=None)
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Please describe the issue (e.g., mixed-up order, incomplete, not delivered).")
    return GET_DELIVERY_ISSUE


async def save_delivery_issue(update: Update, context: CallbackContext) -> int:
    """Saves the delivery issue and ends the conversation."""
    order_id = context.user_data.get("issue_order_id")
    issue_text = update.message.text

    if order_id:
        update_order_status(order_id, 'issue_reported', delivery_issue=issue_text)

    await update.message.reply_text("Thank you. Your issue has been noted and is currently being looked into. We’ll get back to you shortly. 🙏")
    return ConversationHandler.END


async def indomie_start(update: Update, context: CallbackContext) -> int:
    """Asks if the user is providing their own Indomie."""
    query = update.callback_query
    await query.answer()
    context.user_data["order"] = {
        "food": "Indomie",
        "items": [],
        "selected_mixings": [],
        "selected_toppings": [],
        "selected_beverages": [],
    }
    keyboard = [
        [InlineKeyboardButton("Use my own", callback_data="indomie_source_own")],
        [InlineKeyboardButton("Use kitchen's", callback_data="indomie_source_kitchen")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_or_edit_message(update, "Are you using your own Indomie or the kitchen’s?", reply_markup=reply_markup)
    return INDOMIE_SOURCE

async def indomie_flavor(update: Update, context: CallbackContext) -> int:
    """Stores the flavor and asks for the size."""
    query = update.callback_query
    await query.answer()
    flavor = query.data.split("_")[-1]
    context.user_data["order"]["flavor"] = flavor

    if flavor == "chicken":
        keyboard = [
            [InlineKeyboardButton("Small (₦400)", callback_data="size_small_400")],
            [InlineKeyboardButton("Super Pack (₦500)", callback_data="size_super_500")],
        ]
    else:  # Onion and Chicken
        keyboard = [
            [InlineKeyboardButton("Small (₦450)", callback_data="size_small_450")],
            [InlineKeyboardButton("Super Pack (₦600)", callback_data="size_super_600")],
        ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_or_edit_message(update, "Please choose a size:", reply_markup=reply_markup)
    return INDOMIE_SIZE

async def indomie_source(update: Update, context: CallbackContext) -> int:
    """Handles the source of the Indomie and proceeds accordingly."""
    query = update.callback_query
    await query.answer()
    source = query.data.split("_")[-1]

    if source == 'own':
        context.user_data["order"]["source"] = "own"
        await send_or_edit_message(update, "How many packs of Indomie would you like to prepare?")
        return INDOMIE_QUANTITY
    else:
        context.user_data["order"]["source"] = "kitchen"
        keyboard = [
            [InlineKeyboardButton("Chicken Flavour", callback_data="flavor_chicken")],
            [InlineKeyboardButton("Onion and Chicken", callback_data="flavor_onion_chicken")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await send_or_edit_message(update, "Please choose a flavor:", reply_markup=reply_markup)
        return INDOMIE_FLAVOR

async def indomie_size(update: Update, context: CallbackContext) -> int:
    """Stores the size and base price, then proceeds to ask for quantity."""
    query = update.callback_query
    await query.answer()
    size, price_str = query.data.split("_")[1:]
    price = int(price_str)
    context.user_data["order"]["size"] = size

    flavor = context.user_data["order"]["flavor"]
    item_name = f"Indomie ({flavor.replace('_', ' ').title()}, {size.title()})"

    items = context.user_data["order"].get("items", [])
    items = [item for item in items if item.get("type") != "base"]

    items.append({
        "name": item_name,
        "type": "base",
        "unit_price": price,
        "quantity": 1,
        "total_price": price
    })
    context.user_data["order"]["items"] = items

    await send_or_edit_message(update, "How many packs of Indomie would you like to prepare?")
    return INDOMIE_QUANTITY


async def indomie_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of Indomie and proceeds to the mixings menu."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text("Please enter a valid number greater than 0.")
        return INDOMIE_QUANTITY

    order = context.user_data["order"]
    items = order.get("items", [])

    if order.get("source") == "own":
        items = [item for item in items if item.get("type") != "base"]
        items.append({
            "name": "Indomie (Customer's Own)",
            "type": "base",
            "unit_price": 0,
            "quantity": quantity,
            "total_price": 0
        })
        order["items"] = items
    else:
        for item in items:
            if item.get("type") == "base":
                item["quantity"] = quantity
                item["total_price"] = item["unit_price"] * quantity
                break

    return await indomie_mixings_menu(update, context)


async def indomie_mixings_menu(update: Update, context: CallbackContext) -> int:
    """Displays the mixings menu."""
    keyboard = indomie_mixings_keyboard()
    message_text = "Please select your mixings:"
    if update.callback_query:
        await send_or_edit_message(update, message_text, reply_markup=keyboard)
    else:
        await update.message.reply_text(message_text, reply_markup=keyboard)
    return INDOMIE_MIXINGS

async def indomie_mixings(update: Update, context: CallbackContext) -> int:
    """Handles mixing selections."""
    query = update.callback_query
    await query.answer()
    selection = query.data.split("_", 1)[-1] 

    order = context.user_data["order"]
    items = order.get("items", [])
    selected_mixings = order.get("selected_mixings", [])

    if selection == "done":
        return await ask_for_mixing_quantities(update, context)

    if selection == "none":
        order["selected_mixings"] = []
        order["items"] = [item for item in items if item.get("type") not in ["mixing", "spice"]]
        return await ask_for_mixing_quantities(update, context)

    item_name = selection 

    if "spice" in item_name:
        existing_item = next((item for item in items if item["name"] == item_name), None)
        if existing_item:
            items.remove(existing_item)
        else:
            price = PRICES.get(item_name, 0)
            items.append({"name": item_name, "type": "spice", "unit_price": price, "quantity": 1, "total_price": price})
    else:
        if item_name in selected_mixings:
            selected_mixings.remove(item_name)
        else:
            selected_mixings.append(item_name)

    display_items = [item['name'].replace('_', ' ').title() for item in items if item['type'] == 'spice']
    display_items.extend([mixing.replace('_', ' ').title() for mixing in selected_mixings])
    selected_text = ", ".join(display_items)

    await send_or_edit_message(
        update,
        f"Selected mixings: {selected_text}\n\nPlease select your mixings:",
        reply_markup=indomie_mixings_keyboard(),
    )
    return INDOMIE_MIXINGS


def indomie_mixings_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Pepper Spice (₦200)", callback_data="mixing_pepper_spice"),
            InlineKeyboardButton("Crayfish Spice (₦200)", callback_data="mixing_crayfish_spice"),
        ],
        [
            InlineKeyboardButton("Vegetables (₦800)", callback_data="mixing_vegetables"),
            InlineKeyboardButton("Suya (price-based)", callback_data="mixing_suya"),
        ],
        [
            InlineKeyboardButton("Sardine (₦1900)", callback_data="mixing_sardine"),
        ],
        [InlineKeyboardButton("None", callback_data="mixing_none")],
        [InlineKeyboardButton("Done ✅", callback_data="mixing_done")],
    ])


async def ask_for_mixing_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of each selected mixing, one by one."""
    selected_mixings = context.user_data["order"].get("selected_mixings", [])
    items = context.user_data["order"].get("items", [])
    item_names_in_order = [item['name'] for item in items]
    next_mixing_to_ask = next((mixing for mixing in selected_mixings if mixing not in item_names_in_order), None)

    if next_mixing_to_ask:
        message_text, next_state = "", -1
        if next_mixing_to_ask == "vegetables":
            message_text, next_state = "How many servings of vegetables would you like?", INDOMIE_VEGETABLES_QUANTITY
        elif next_mixing_to_ask == "suya":
            message_text, next_state = "Enter the amount for suya (₦):", INDOMIE_SUYA_AMOUNT
        elif next_mixing_to_ask == "sardine":
            message_text, next_state = "How many servings of sardine would you like?", INDOMIE_SARDINE_QUANTITY
        
        if not message_text:
            logger.error(f"Could not determine message text for mixing: {next_mixing_to_ask}")
            message_text = f"Please provide quantity for {next_mixing_to_ask.replace('_', ' ')}:"

        await send_or_edit_message(update, message_text)
        return next_state

    return await indomie_toppings_menu(update, context)


async def indomie_toppings_menu(update: Update, context: CallbackContext) -> int:
    """Displays the toppings menu."""
    keyboard = indomie_toppings_keyboard()
    await send_or_edit_message(update, "Please select your toppings:", reply_markup=keyboard)
    return INDOMIE_TOPPINGS

async def indomie_toppings(update: Update, context: CallbackContext) -> int:
    """Handles topping selections."""
    query = update.callback_query
    await query.answer()
    selection = query.data.split("_", 1)[-1]

    order = context.user_data["order"]
    selected_toppings = order.get("selected_toppings", [])

    if selection == "done":
        return await ask_for_topping_quantities(update, context)

    if selection == "none":
        order["selected_toppings"] = []
        order["items"] = [item for item in order.get("items", []) if item.get("type") != "topping"]
        return await ask_for_topping_quantities(update, context)

    item_name = selection

    if item_name in selected_toppings:
        selected_toppings.remove(item_name)
    else:
        selected_toppings.append(item_name)

    display_text = ', '.join([t.replace('_', ' ').title() for t in selected_toppings])
    await send_or_edit_message(
        update,
        f"Selected toppings: {display_text}\n\nPlease select your toppings:",
        reply_markup=indomie_toppings_keyboard(),
    )
    return INDOMIE_TOPPINGS

def indomie_toppings_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Egg (₦400)", callback_data="topping_egg"),
            InlineKeyboardButton("Sausage (₦400)", callback_data="topping_sausage"),
        ],
        [
            InlineKeyboardButton("Chicken (₦1000)", callback_data="topping_chicken_1000"),
            InlineKeyboardButton("Chicken (₦1500)", callback_data="topping_chicken_1500"),
            InlineKeyboardButton("Chicken (₦3000)", callback_data="topping_chicken_3000"),
        ],
        [
            InlineKeyboardButton("Fried Fish (₦1500)", callback_data="topping_fried_fish"),
        ],
        [InlineKeyboardButton("None", callback_data="topping_none")],
        [InlineKeyboardButton("Done ✅", callback_data="topping_done")],
    ])

async def ask_for_topping_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of each selected topping, one by one."""
    selected_toppings = context.user_data["order"].get("selected_toppings", [])
    items = context.user_data["order"].get("items", [])
    item_names_in_order = [item['name'] for item in items]
    next_topping_to_ask = next((topping for topping in selected_toppings if topping not in item_names_in_order), None)

    if next_topping_to_ask:
        message_text, next_state = "", -1
        if next_topping_to_ask == "egg":
            message_text, next_state = "How many eggs would you like?", INDOMIE_EGG_QUANTITY
        elif next_topping_to_ask == "sausage":
            message_text, next_state = "How many sausages would you like?", INDOMIE_SAUSAGE_QUANTITY
        elif next_topping_to_ask == "chicken_1000":
            message_text, next_state = "How many pieces of chicken (₦1000) would you like?", INDOMIE_CHICKEN_1000_QUANTITY
        elif next_topping_to_ask == "chicken_1500":
            message_text, next_state = "How many pieces of chicken (₦1500) would you like?", INDOMIE_CHICKEN_1500_QUANTITY
        elif next_topping_to_ask == "chicken_3000":
            message_text, next_state = "How many pieces of chicken (₦3000) would you like?", INDOMIE_CHICKEN_3000_QUANTITY
        elif next_topping_to_ask == "fried_fish":
            message_text, next_state = "How many pieces of fried fish would you like?", INDOMIE_FRIED_FISH_QUANTITY
        
        if not message_text:
            logger.error(f"Could not determine message text for topping: {next_topping_to_ask}")
            message_text = f"Please provide quantity for {next_topping_to_ask.replace('_', ' ')}:"

        await send_or_edit_message(update, message_text)
        return next_state

    return await ask_for_beverages(update, context)


async def ask_for_beverages(update: Update, context: CallbackContext) -> int:
    """Displays the beverage selection menu."""
    keyboard = beverage_keyboard()
    message = "Would you like any drink or beverage with your order?"
    await send_or_edit_message(update, message, reply_markup=keyboard)
    return ASK_BEVERAGE


def beverage_keyboard():
    """Returns the keyboard for the beverage menu."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Water (₦300)", callback_data="bev_water"),
            InlineKeyboardButton("Soft Drink (₦600)", callback_data="bev_soft_drink"),
        ],
        [
            InlineKeyboardButton("Malt (₦800)", callback_data="bev_malt"),
            InlineKeyboardButton("1Ltr Drink (₦2500)", callback_data="bev_1ltr_drink"),
        ],
        [InlineKeyboardButton("Ice (₦250)", callback_data="bev_ice")],
        [InlineKeyboardButton("None", callback_data="bev_none")],
        [InlineKeyboardButton("Done ✅", callback_data="bev_done")],
    ])

async def ask_for_beverage_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of each selected beverage, one by one."""
    selected_beverages = context.user_data["order"].get("selected_beverages", [])
    items = context.user_data["order"].get("items", [])
    item_names_in_order = [item['name'] for item in items]
    next_beverage_to_ask = next((beverage for beverage in selected_beverages if beverage not in item_names_in_order), None)

    if next_beverage_to_ask:
        message_text, next_state = "", -1
        if next_beverage_to_ask == "water":
            message_text, next_state = "How many bottles of water would you like?", INDOMIE_WATER_QUANTITY
        elif next_beverage_to_ask == "soft_drink":
            message_text, next_state = "How many soft drinks would you like?", INDOMIE_COKE_QUANTITY
        elif next_beverage_to_ask == "malt":
            message_text, next_state = "How many malts would you like?", INDOMIE_MALT_QUANTITY
        elif next_beverage_to_ask == "1ltr_drink":
            message_text, next_state = "How many 1Ltr drinks would you like?", INDOMIE_JUICE_QUANTITY
        elif next_beverage_to_ask == "ice":
            message_text, next_state = "How many packs of ice would you like?", INDOMIE_ICE_QUANTITY

        if not message_text:
            logger.error(f"Could not determine message text for beverage: {next_beverage_to_ask}")
            message_text = f"Please provide quantity for {next_beverage_to_ask.replace('_', ' ')}:"

        await send_or_edit_message(update, message_text)
        return next_state

    return await ask_for_extra_notes(update, context)


async def get_beverage_quantity(update: Update, context: CallbackContext, beverage_name: str, next_state_constant: int) -> int:
    """Generic function to handle beverage quantity."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            await update.message.reply_text("Please enter a valid number greater than 0.")
            return next_state_constant

        order = context.user_data["order"]
        items = order.get("items", [])
        unit_price = PRICES.get(beverage_name.lower(), 0)

        items = [item for item in items if item.get("name") != beverage_name]
        items.append({
            "name": beverage_name, "type": "beverage", "unit_price": unit_price,
            "quantity": quantity, "total_price": unit_price * quantity,
        })
        order["items"] = items
        return await ask_for_beverage_quantities(update, context)
    except (ValueError, TypeError):
        await update.message.reply_text("Invalid input. Please enter a number.")
        return next_state_constant

async def get_water_quantity(update: Update, context: CallbackContext) -> int:
    return await get_beverage_quantity(update, context, "water", INDOMIE_WATER_QUANTITY)

async def get_coke_quantity(update: Update, context: CallbackContext) -> int:
    return await get_beverage_quantity(update, context, "soft_drink", INDOMIE_COKE_QUANTITY)

async def get_malt_quantity(update: Update, context: CallbackContext) -> int:
    return await get_beverage_quantity(update, context, "malt", INDOMIE_MALT_QUANTITY)

async def get_juice_quantity(update: Update, context: CallbackContext) -> int:
    return await get_beverage_quantity(update, context, "1ltr_drink", INDOMIE_JUICE_QUANTITY)

async def get_ice_quantity(update: Update, context: CallbackContext) -> int:
    return await get_beverage_quantity(update, context, "ice", INDOMIE_ICE_QUANTITY)

async def get_topping_quantity(update: Update, context: CallbackContext, topping_name: str, next_state_constant: int) -> int:
    """Generic function to handle topping quantity."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            await update.message.reply_text("Please enter a valid number greater than 0.")
            return next_state_constant

        order = context.user_data["order"]
        items = order.get("items", [])
        unit_price = PRICES.get(topping_name.lower(), 0)

        items = [item for item in items if item.get("name") != topping_name]
        items.append({
            "name": topping_name, "type": "topping", "unit_price": unit_price,
            "quantity": quantity, "total_price": unit_price * quantity,
        })
        order["items"] = items
        return await ask_for_topping_quantities(update, context)
    except (ValueError, TypeError):
        await update.message.reply_text("Invalid input. Please enter a number.")
        return next_state_constant


async def get_mixing_quantity(update: Update, context: CallbackContext, mixing_name: str, next_state_constant: int) -> int:
    """Generic function to handle mixing quantity."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            await update.message.reply_text("Please enter a valid number greater than 0.")
            return next_state_constant

        order = context.user_data["order"]
        items = order.get("items", [])
        unit_price = PRICES.get(mixing_name.lower(), 0)

        items = [item for item in items if item.get("name") != mixing_name]
        items.append({
            "name": mixing_name, "type": "mixing", "unit_price": unit_price,
            "quantity": quantity, "total_price": unit_price * quantity,
        })
        order["items"] = items
        return await ask_for_mixing_quantities(update, context)
    except (ValueError, TypeError):
        await update.message.reply_text("Invalid input. Please enter a number.")
        return next_state_constant


async def get_sardine_quantity(update: Update, context: CallbackContext) -> int:
    return await get_mixing_quantity(update, context, "sardine", INDOMIE_SARDINE_QUANTITY)


async def get_vegetables_quantity(update: Update, context: CallbackContext) -> int:
    return await get_mixing_quantity(update, context, "vegetables", INDOMIE_VEGETABLES_QUANTITY)


async def get_suya_amount(update: Update, context: CallbackContext) -> int:
    return await get_mixing_quantity(update, context, "suya", INDOMIE_SUYA_AMOUNT)


async def get_egg_quantity(update: Update, context: CallbackContext) -> int:
    return await get_topping_quantity(update, context, "egg", INDOMIE_EGG_QUANTITY)

async def get_sausage_quantity(update: Update, context: CallbackContext) -> int:
    return await get_topping_quantity(update, context, "sausage", INDOMIE_SAUSAGE_QUANTITY)

async def get_chicken_1000_quantity(update: Update, context: CallbackContext) -> int:
    return await get_topping_quantity(update, context, "chicken_1000", INDOMIE_CHICKEN_1000_QUANTITY)

async def get_chicken_1500_quantity(update: Update, context: CallbackContext) -> int:
    return await get_topping_quantity(update, context, "chicken_1500", INDOMIE_CHICKEN_1500_QUANTITY)

async def get_chicken_3000_quantity(update: Update, context: CallbackContext) -> int:
    return await get_topping_quantity(update, context, "chicken_3000", INDOMIE_CHICKEN_3000_QUANTITY)

async def get_fried_fish_quantity(update: Update, context: CallbackContext) -> int:
    return await get_topping_quantity(update, context, "fried_fish", INDOMIE_FRIED_FISH_QUANTITY)

async def handle_beverage_selection(update: Update, context: CallbackContext) -> int:
    """Handles beverage selections."""
    query = update.callback_query
    await query.answer()
    selection = query.data.split("_", 1)[-1]

    order = context.user_data["order"]
    selected_beverages = order.get("selected_beverages", [])

    if selection == "done":
        return await ask_for_beverage_quantities(update, context)

    if selection == "none":
        order["selected_beverages"] = []
        order["items"] = [item for item in order.get("items", []) if item.get("type") != "beverage"]
        return await ask_for_beverage_quantities(update, context)

    item_name = selection

    if item_name in selected_beverages:
        selected_beverages.remove(item_name)
    else:
        selected_beverages.append(item_name)
    
    display_text = ', '.join([b.replace('_', ' ').title() for b in selected_beverages])
    await send_or_edit_message(
        update,
        f"Selected beverages: {display_text}\n\nPlease select your beverages:",
        reply_markup=beverage_keyboard(),
    )
    return ASK_BEVERAGE


async def custard_start(update: Update, context: CallbackContext) -> int:
    """Starts the custard order flow."""
    query = update.callback_query
    await query.answer()
    context.user_data["order"] = {
        "food": "Custard", "items": [], "selected_additions": [],
    }
    keyboard = [
        [InlineKeyboardButton("Use my own", callback_data="custard_source_own")],
        [InlineKeyboardButton("Use kitchen's", callback_data="custard_source_kitchen")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_or_edit_message(update, "Are you using your own Custard or the kitchen’s?", reply_markup=reply_markup)
    return CUSTARD_SOURCE


async def custard_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of custard."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text("Please enter a valid number greater than 0.")
        return CUSTARD_QUANTITY

    order = context.user_data["order"]
    items = order.get("items", [])
    items = [item for item in items if item.get("type") != "base"]
    
    unit_price = 0 if order.get("source") == "own" else PRICES.get("custard", 0)
    item_name = "Custard (Customer's Own)" if order.get("source") == "own" else "Custard"

    items.append({
        "name": item_name, "type": "base", "unit_price": unit_price,
        "quantity": quantity, "total_price": unit_price * quantity,
    })
    order["items"] = items

    keyboard = custard_additions_keyboard()
    await update.message.reply_text("What would you like to add to your custard?", reply_markup=keyboard)
    return CUSTARD_ADDITIONS


async def custard_source(update: Update, context: CallbackContext) -> int:
    """Stores the source of the Custard and asks for quantity."""
    query = update.callback_query
    await query.answer()
    source = query.data.split("_")[-1]
    context.user_data["order"]["source"] = source
    
    await send_or_edit_message(update, "How many custard cups would you like to make?")
    return CUSTARD_QUANTITY


def custard_additions_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Sugar", callback_data="custard_add_sugar"),
            InlineKeyboardButton("Milk", callback_data="custard_add_milk"),
        ],
        [
            InlineKeyboardButton("None", callback_data="custard_add_none"),
            InlineKeyboardButton("Done ✅", callback_data="custard_add_done"),
        ],
    ])


async def custard_additions(update: Update, context: CallbackContext) -> int:
    """Handles the selection of custard additions."""
    query = update.callback_query
    await query.answer()
    selection = query.data.split("_", 2)[-1]

    order = context.user_data["order"]
    selected_additions = order.get("selected_additions", [])

    if selection == "done":
        return await ask_for_custard_quantities(update, context)

    if selection == "none":
        order["selected_additions"] = []
        order["items"] = [item for item in order.get("items", []) if item.get("type") != "addition"]
        return await ask_for_custard_quantities(update, context)

    item_name = selection

    if item_name in selected_additions:
        selected_additions.remove(item_name)
    else:
        selected_additions.append(item_name)
    
    display_text = ', '.join([a.replace('_', ' ').title() for a in selected_additions])
    await send_or_edit_message(
        update,
        f"Selected additions: {display_text}\n\nPlease select additions:",
        reply_markup=custard_additions_keyboard(),
    )
    return CUSTARD_ADDITIONS


async def ask_for_custard_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for quantities of selected custard additions one by one."""
    selected_additions = context.user_data["order"].get("selected_additions", [])
    items = context.user_data["order"].get("items", [])
    item_names_in_order = [item['name'] for item in items]
    next_addition_to_ask = next((add for add in selected_additions if add not in item_names_in_order), None)

    if next_addition_to_ask:
        message_text, next_state = "", -1
        if next_addition_to_ask == "sugar":
            message_text, next_state = "How many spoons of sugar would you like?", CUSTARD_SUGAR_QUANTITY
        elif next_addition_to_ask == "milk":
            message_text, next_state = "How many sachets of milk would you like?", CUSTARD_MILK_QUANTITY

        await send_or_edit_message(update, message_text)
        return next_state

    return await ask_for_extra_notes(update, context)


async def get_custard_addition_quantity(update: Update, context: CallbackContext, item_name: str, next_state: int) -> int:
    """Generic function to handle quantity for custard additions."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text("Invalid input. Please enter a valid number > 0.")
        return next_state

    order = context.user_data["order"]
    items = order.get("items", [])
    unit_price = PRICES.get(item_name, 0)

    items = [item for item in items if item.get("name") != item_name]
    items.append({
        "name": item_name, "type": "addition", "unit_price": unit_price,
        "quantity": quantity, "total_price": unit_price * quantity,
    })
    order["items"] = items
    return await ask_for_custard_quantities(update, context)


async def custard_sugar_quantity(update: Update, context: CallbackContext) -> int:
    return await get_custard_addition_quantity(update, context, "sugar", CUSTARD_SUGAR_QUANTITY)


async def custard_milk_quantity(update: Update, context: CallbackContext) -> int:
    return await get_custard_addition_quantity(update, context, "milk", CUSTARD_MILK_QUANTITY)


async def spaghetti_start(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_kitchen_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_or_edit_message(update, "Please contact customer care for more info 📞", reply_markup=reply_markup)
    return KITCHEN_MENU


async def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels the conversation and returns to the main menu."""
    if update.callback_query:
        await update.callback_query.answer()
    return await start(update, context)


async def show_order_summary(update: Update, context: CallbackContext) -> int:
    """Calculates the total price and shows the simplified order summary."""
    order = context.user_data["order"]
    items = order.get("items", [])
    subtotal = sum(item.get("total_price", 0) for item in items)

    pack_fee = PACK_FEE if order.get("food") in ["Indomie", "Custard"] else 0

    service_charge = 0
    if order.get("food") in ["Indomie", "Custard"]:
        base_item_quantity = sum(item.get('quantity', 0) for item in items if item.get("type") == "base")
        service_charge = base_item_quantity * 250
    elif order.get("food") == "Cafe Order":
        service_charge = (subtotal // 500) * 100

    total = subtotal + service_charge + pack_fee
    order["service_charge"] = service_charge
    order["total"] = total

    summary = "<b>Here is your order summary:</b>\n\n"
    for item in items:
        name = item.get("name", "Unknown Item").replace('_', ' ').title()
        quantity = item.get("quantity", 0)
        summary += f"- {name} (x{quantity})\n"

    if order.get("notes"):
        summary += f"\n<b>Notes:</b> {order['notes']}\n"

    summary += "----------------------\n"
    summary += f"<b>Total: ₦{total}</b>\n\n"
    summary += "Pay Online:\n"
    summary += "https://pay-naira.netlify.app"

    keyboard = [
        [
            InlineKeyboardButton("✅ I have paid", callback_data="proceed_to_payment"),
            InlineKeyboardButton("💵 View Bill", callback_data="view_bill"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_or_edit_message(update, summary, reply_markup=reply_markup, parse_mode='HTML')
    return ORDER_SUMMARY


async def proceed_to_payment(update: Update, context: CallbackContext) -> int:
    """Saves the order and asks for a payment screenshot."""
    query = update.callback_query
    await query.answer()
    order = context.user_data["order"]

    delivery_info = {
        "hall_and_room_number": order.get("hall_and_room_number"),
        "delivery_time": order.get("delivery_time"),
    }

    order_id = add_order(
        user_id=update.effective_user.id, username=update.effective_user.username,
        food_type=order["food"], items=order.get("items", []), total=order["total"],
        service_charge=order.get("service_charge", 0), status='pending_payment',
        delivery_info=delivery_info, notes=order.get("notes")
    )
    context.user_data["order_id"] = order_id

    await send_or_edit_message(update, "Your order has been saved. Please upload a screenshot of your payment to complete the order.")
    return GET_PAYMENT_SCREENSHOT


async def handle_payment_screenshot(update: Update, context: CallbackContext) -> int:
    """Handles the payment screenshot, finalizes the order, and notifies workers."""
    order_id = context.user_data.get("order_id")
    if not order_id:
        await update.message.reply_text("Something went wrong. Please try placing your order again.")
        return ConversationHandler.END

    order = get_order_by_id(order_id)
    if not order:
        await update.message.reply_text("Could not find the saved order. Please start again.")
        return ConversationHandler.END
        
    add_payment(
        order_id, update.message.photo[-1].file_id,
        update.effective_user.username, order.get('total', 0)
    )
    update_order_status(order_id, 'pending')

    # Send the first confirmation message
    await update.message.reply_text(
        "✅ Payment received! Your order has been placed and our workers have been notified."
    )

    # Send the second message with the order summary
    order_summary = await get_order_summary_for_customer(order)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=order_summary,
        parse_mode='HTML'
    )

    if order.get('food_type') == 'Cafe Order':
        await notify_workers(context, order_id)
    else:
        await notify_admin_of_new_kitchen_order(context, order_id)

    await update.message.reply_text(
        "You will receive a notification once your order is accepted."
    )
    return ConversationHandler.END


async def view_bill(update: Update, context: CallbackContext) -> int:
    """Shows the billing breakdown."""
    query = update.callback_query
    await query.answer()
    order = context.user_data["order"]
    bill = "📋 <b>Billing Breakdown</b>:\n"

    items = order.get("items", [])
    for item in items:
        name = item.get("name", "N/A").replace('_', ' ').title()
        quantity = item.get("quantity", 0)
        unit_price = item.get("unit_price", 0)
        item_total = item.get("total_price", 0)

        if item.get('type') == 'base' and 'indomie' in name.lower():
            bill += f"• {name} (₦{unit_price} x{quantity}) = ₦{item_total}\n"
        elif item.get('type') == 'base' or 'spice' in item.get('type', ''):
             bill += f"• {name} = ₦{item_total}\n"
        elif name.lower() == 'suya':
            bill += f"• {name} (Amount) = ₦{item_total}\n"
        else:
            bill += f"• {name} ({quantity} × ₦{unit_price}) = ₦{item_total}\n"

    pack_fee = PACK_FEE if order.get("food") in ["Indomie", "Custard"] else 0
    service_charge = order.get("service_charge", 0)
    total = order.get("total", 0)
    
    if pack_fee > 0:
        bill += f"Pack Fee: ₦{pack_fee}\n"
    bill += f"Service Charge: ₦{service_charge}\n"
    bill += "----------------------\n"
    bill += f"💰 <b>Total = ₦{total}</b>"

    keyboard = [
        [
            InlineKeyboardButton("✅ I have paid", callback_data="proceed_to_payment"),
            InlineKeyboardButton("⬅️ Back", callback_data="back_to_summary"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_or_edit_message(update, bill, reply_markup=reply_markup, parse_mode='HTML')
    return ORDER_SUMMARY


async def view_orders(update: Update, context: CallbackContext) -> int:
    """Displays the user's past orders with pagination."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    page = 0
    if "page" in query.data:
        page = int(query.data.split("_")[-1])
    orders_per_page = 5
    
    orders_data = get_user_orders(user_id)
    if not orders_data:
        await send_or_edit_message(update, "You have no orders yet. Start by placing one 🍽️")
        return MAIN_MENU

    start_index = page * orders_per_page
    end_index = start_index + orders_per_page
    paginated_orders = orders_data[start_index:end_index]

    message = "📦 <b>Your Past Orders</b> (Page {} of {}):\n\n".format(page + 1, -(-len(orders_data) // orders_per_page))
    for i, order in enumerate(paginated_orders):
        order_date = format_date(order.get('order_date', 'N/A'))
        message += f"<b>Order #{start_index + i + 1}</b> - Placed on {order_date}\n"
        try:
            items = json.loads(order.get('items', '[]'))
            for item in items:
                name = item.get("name", "Unknown Item").replace('_', ' ').title()
                quantity = item.get("quantity", 0)
                message += f"  - {name} (x{quantity})\n"
        except (json.JSONDecodeError, TypeError):
            message += "  - Error displaying order details.\n"

        total = float(order.get('total', 0))
        message += f"  <b>Total: ₦{total}</b>\n\n"

    keyboard = []
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"view_orders_page_{page - 1}"))
    if end_index < len(orders_data):
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"view_orders_page_{page + 1}"))
    
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await send_or_edit_message(update, message, reply_markup=reply_markup, parse_mode='HTML')
    return MAIN_MENU


async def admin_start(update: Update, context: CallbackContext) -> int:
    """Asks for the admin password or shows the menu if already logged in."""
    user_id = update.effective_user.id
    if user_id in context.bot_data and "login_time" in context.bot_data[user_id]:
        time_diff = datetime.now() - context.bot_data[user_id]["login_time"]
        if time_diff.total_seconds() < 600:
            return await admin_main_menu_callback(update, context)

    await update.message.reply_text("Enter the admin password:")
    return ADMIN_PASSWORD


async def admin_main_menu_callback(update: Update, context: CallbackContext) -> int:
    """Displays the main admin menu."""
    keyboard = [
        [InlineKeyboardButton("📦 Orders", callback_data="admin_orders")],
        [InlineKeyboardButton("👷‍♂️ Workers", callback_data="admin_workers")],
        [InlineKeyboardButton("💳 Payments", callback_data="admin_payments")],
        [InlineKeyboardButton("📝 Customer Feedbacks", callback_data="admin_feedback")],
        [InlineKeyboardButton("📣 Customer Check-ins", callback_data="admin_checkin")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_message = "Welcome Admin 👑 What would you like to manage today?"
    if update.callback_query:
        await send_or_edit_message(update, welcome_message, reply_markup=reply_markup)
    else:
        await update.message.reply_text(welcome_message, reply_markup=reply_markup)
    return ADMIN_MENU

async def admin_checkin_menu(update: Update, context: CallbackContext) -> int:
    """Shows the customer check-in message categories."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🌧️ Rainy", callback_data="checkin_rainy")],
        [InlineKeyboardButton("🥶 Cold", callback_data="checkin_cold")],
        [InlineKeyboardButton("☀️ Hot", callback_data="checkin_hot")],
        [InlineKeyboardButton("🗓️ Sunday", callback_data="checkin_sunday")],
        [InlineKeyboardButton("💬 Casual", callback_data="checkin_casual")],
        [InlineKeyboardButton("✍️ Custom", callback_data="checkin_custom")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_or_edit_message(update, "Select a category to send a check-in message to all users:", reply_markup=reply_markup)
    return ADMIN_CHECKIN_MENU

async def handle_checkin_broadcast(update: Update, context: CallbackContext) -> int:
    """Handles broadcasting a message from a predefined category."""
    query = update.callback_query
    await query.answer("Broadcasting...")
    category = query.data.split("_")[-1].upper()

    message_list = globals().get(category, [])
    if not message_list:
        await send_or_edit_message(update, "Error: Message category not found.")
        return ADMIN_CHECKIN_MENU

    message_to_send = random.choice(message_list)
    await broadcast_message(context, message_to_send)

    await query.message.reply_text(f"✅ Successfully broadcasted the '{category.title()}' message to all users.")
    return ADMIN_CHECKIN_MENU

async def admin_custom_message_prompt(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    await send_or_edit_message(update, "Please type the custom message you want to send to all users.")
    return ADMIN_CUSTOM_MESSAGE_PROMPT

async def handle_custom_broadcast(update: Update, context: CallbackContext) -> int:
    custom_message = update.message.text
    await broadcast_message(context, custom_message)
    await update.message.reply_text("✅ Successfully broadcasted your custom message to all users.")

    return await admin_checkin_menu(update, context)

async def broadcast_message(context: CallbackContext, message: str):
    user_ids = get_all_unique_users()
    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {user_id}: {e}")


async def admin_password(update: Update, context: CallbackContext) -> int:
    if update.message and update.message.text == "wiliwili":
        context.bot_data[update.effective_user.id] = {"login_time": datetime.now()}
        return await admin_main_menu_callback(update, context)
    else:
        await update.message.reply_text("Incorrect password.")
        return ConversationHandler.END


async def handle_worker_approval(update: Update, context: CallbackContext) -> int:
    """Handles admin's decision on a worker application."""
    query = update.callback_query
    await query.answer()
    
    action, user_id_str = query.data.split("_")
    user_id = int(user_id_str)
    
    new_status = 'approved' if action == 'approve' else 'rejected'
    update_worker_status(user_id, new_status)
    
    feedback_message = (
        f"✅ Your application to be a worker has been approved! "
        f"You will now receive notifications for available orders."
    ) if new_status == 'approved' else (
        "❌ Your application to be a worker has been rejected. "
        "Please contact the admin if you have any questions."
    )
    
    try:
        await context.bot.send_message(chat_id=user_id, text=feedback_message)
    except Exception as e:
        logger.error(f"Failed to send worker status update to user {user_id}: {e}")
        
    await query.edit_message_text(f"The application has been {new_status}.")
    return ADMIN_MENU


async def review_order(update: Update, context: CallbackContext) -> int:
    """Displays an order for an admin or worker to review."""
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[-1])
    order = get_order_by_id(order_id)

    if not order:
        await send_or_edit_message(update, "Order not found or has been taken.")
        return ADMIN_MENU

    user = update.effective_user
    is_admin_user = user.id == ADMIN_ID
    
    summary = await get_order_summary_for_worker(order, for_admin=is_admin_user)
    
    keyboard = []
    if is_admin_user:
        keyboard.append([
            InlineKeyboardButton("✅ Accept Order", callback_data=f"accept_{order_id}"),
            InlineKeyboardButton("❌ Decline Order", callback_data=f"decline_{order_id}")
        ])
    elif is_worker(user.id):
        keyboard.append([
            InlineKeyboardButton("✅ Accept Order", callback_data=f"accept_{order_id}")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await send_or_edit_message(update, summary, reply_markup=reply_markup, parse_mode='HTML')
    return ADMIN_MENU

def admin_orders_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View Active Orders", callback_data="view_active_orders")],
        [InlineKeyboardButton("View All Taken Orders", callback_data="view_taken_orders_admin")],
        [InlineKeyboardButton("View All Placed Orders", callback_data="view_all_orders_admin")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")],
    ])

async def admin_orders_menu(update: Update, context: CallbackContext) -> int:
    await send_or_edit_message(update, "📦 Order Management", reply_markup=admin_orders_menu_keyboard())
    return ADMIN_MENU

def admin_workers_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View All Workers", callback_data="view_workers_admin")],
        [InlineKeyboardButton("View Pending Applications", callback_data="view_pending_apps")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")],
    ])

async def admin_workers_menu(update: Update, context: CallbackContext) -> int:
    await send_or_edit_message(update, "👷‍♂️ Worker Management", reply_markup=admin_workers_menu_keyboard())
    return ADMIN_MENU

async def admin_payments_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    payments = get_all_payments()
    if not payments:
        await send_or_edit_message(update, "No payments found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_main_menu")]]))
        return ADMIN_MENU

    for payment in payments:
        payment_id, order_id, screenshot_file_id, username, total, timestamp = (*payment, None)[:6]
        formatted_date = format_date(timestamp)
        caption = f"Payment for Order #{order_id} from @{username} (Total: ₦{total}) on {formatted_date}"
        try:
            if screenshot_file_id:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=screenshot_file_id, caption=caption)
            else:
                await query.message.reply_text(f"No payment image for Order #{order_id}.")
        except Exception:
            await query.message.reply_text(f"Could not load payment image for Order #{order_id}.")

    await query.message.reply_text("All payments displayed.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_main_menu")]]))
    return ADMIN_MENU


async def view_active_orders_admin(update: Update, context: CallbackContext) -> int:
    orders_data = get_orders_by_status(('pending', 'pending_payment'))
    if not orders_data:
        await send_or_edit_message(update, "No active orders yet.", reply_markup=admin_orders_menu_keyboard())
        return ADMIN_MENU

    await send_or_edit_message(update, "📦 Active Orders:")
    for order in orders_data:
        message = f"ID: {order.get('order_id')}, User: @{order.get('username')}, Order: {order.get('food_type')}, Total: ₦{order.get('total')}"
        keyboard = [[InlineKeyboardButton("✅ Review Order", callback_data=f"review_{order.get('order_id')}")]]
        await update.callback_query.message.reply_text(text=message, reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU

async def view_taken_orders_admin(update: Update, context: CallbackContext) -> int:
    orders_data = get_orders_by_status('taken')
    if not orders_data:
        await send_or_edit_message(update, "No taken orders yet.", reply_markup=admin_orders_menu_keyboard())
        return ADMIN_MENU
    message = "📦 Taken Orders:\n" + "\n".join([
        f"ID: {o.get('order_id')}, User: @{o.get('username')}, Worker: {o.get('taken_by')}, Total: ₦{o.get('total')}"
        for o in orders_data
    ])
    await send_or_edit_message(update, message, reply_markup=admin_orders_menu_keyboard())
    return ADMIN_MENU

async def view_all_orders_admin(update: Update, context: CallbackContext) -> int:
    """Displays all orders to the admin with pagination."""
    query = update.callback_query
    await query.answer()
    
    page = int(query.data.split("_")[-1]) if "page" in query.data else 0
    orders_per_page = 10
    
    orders_data = get_all_orders()
    if not orders_data:
        await send_or_edit_message(update, "No placed orders yet.", reply_markup=admin_orders_menu_keyboard())
        return ADMIN_MENU

    start_index = page * orders_per_page
    paginated_orders = orders_data[start_index : start_index + orders_per_page]

    message = f"📦 <b>All Placed Orders</b> (Page {page + 1} of {-(-len(orders_data) // orders_per_page)}):\n\n"
    keyboard = []
    for order in paginated_orders:
        food_type = "[Kitchen Order]" if order.get('food_type') in ["Indomie", "Custard"] else "[Cafe Order]"
        message += f"<b>ID:</b> {order.get('order_id')} {food_type}, <b>User:</b> @{order.get('username', 'N/A')}, <b>Total:</b> ₦{order.get('total', 0)}, <b>Status:</b> {order.get('status', 'N/A')}\n"
        keyboard.append([InlineKeyboardButton(f"View Details for Order #{order.get('order_id')}", callback_data=f"admin_view_order_{order.get('order_id')}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Previous", callback_data=f"view_all_orders_admin_page_{page - 1}"))
    if (start_index + orders_per_page) < len(orders_data):
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"view_all_orders_admin_page_{page + 1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_orders")])
    
    await send_or_edit_message(update, message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return ADMIN_VIEW_ORDER_DETAIL


async def admin_view_order_details(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[-1])
    order = get_order_by_id(order_id)
    if not order:
        await send_or_edit_message(update, "Order not found.")
        return ADMIN_MENU

    food_type = "Kitchen Order" if order.get('food_type', '') in ["Indomie", "Custard"] else "Cafe Order"
    summary = f"<b>Order Details for ID: {order_id} ({food_type})</b>\n\n"
    summary += f"<b>User:</b> @{order.get('username', 'N/A')}\n"
    summary += f"<b>Status:</b> {order.get('status', 'N/A')}\n<b>Items:</b>\n"

    try:
        items = json.loads(order.get('items', '[]'))
        for item in items:
            name = item.get("name", "Unknown Item").replace('_', ' ').title()
            summary += f"  - {name} (x{item.get('quantity', 0)})\n"
    except (json.JSONDecodeError, TypeError):
        summary += "  - Error displaying items.\n"

    if order.get('notes'):
        summary += f"\n<b>Notes:</b> {order['notes']}\n"
    
    try:
        delivery_info = json.loads(order.get('delivery_info', '{}'))
        summary += f"<b>Delivery to:</b> {delivery_info.get('hall_and_room_number', 'N/A')}\n"
        summary += f"<b>Delivery time:</b> {delivery_info.get('delivery_time', 'N/A')}\n"
    except json.JSONDecodeError:
         summary += "<b>Delivery Info:</b> Error parsing details.\n"

    summary += f"----------------------\n<b>Total: ₦{order.get('total', 0)}</b>"
    
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="admin_orders")]]
    await send_or_edit_message(update, summary, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return ADMIN_MENU

async def view_workers_admin(update: Update, context: CallbackContext) -> int:
    workers_data = get_all_workers(approved_only=False)
    if not workers_data:
        await send_or_edit_message(update, "No registered workers yet.", reply_markup=admin_workers_menu_keyboard())
        return ADMIN_MENU
    message = "👷‍♂️ All Workers:\n" + "\n".join([
        f"Name: {w.get('name')}, User: @{w.get('username', 'N/A')}, Status: {w.get('status', 'N/A')}"
        for w in workers_data
    ])
    await send_or_edit_message(update, message, reply_markup=admin_workers_menu_keyboard())
    return ADMIN_MENU

async def view_pending_applications_admin(update: Update, context: CallbackContext) -> int:
    applications_data = get_workers_by_status('pending')
    if not applications_data:
        await send_or_edit_message(update, "No pending applications.", reply_markup=admin_workers_menu_keyboard())
        return ADMIN_MENU
    
    await send_or_edit_message(update, "📝 Pending Worker Applications:")
    for app in applications_data:
        user_id = app.get('user_id')
        message = f"Pending App for: {app.get('name')} (@{app.get('username')})\nPhone: {app.get('phone')}"
        keyboard = [[
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}"),
        ]]
        await update.callback_query.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_MENU


async def customer_feedback_start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("We value your feedback! Please type a short review of your experience with the bot.")
    return CUSTOMER_FEEDBACK

async def customer_feedback_save(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    add_feedback(user_id=user.id, username=user.username, name=user.full_name, feedback_text=update.message.text)
    await update.message.reply_text("Thank you for your feedback! It has been recorded.")
    return ConversationHandler.END


async def view_feedback_admin(update: Update, context: CallbackContext) -> int:
    feedback_data = get_all_feedback()
    if not feedback_data:
        await send_or_edit_message(update, "No customer feedback yet.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_main_menu")]]))
        return ADMIN_MENU
    message = "📝 Customer Feedbacks:\n\n" + "\n\n".join([
        f"👤 <b>{f.get('name')}</b> (@{f.get('username')}) on {f.get('timestamp')}:\n   - \"{f.get('feedback_text')}\""
        for f in feedback_data
    ])
    await send_or_edit_message(update, message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="admin_main_menu")]]), parse_mode='HTML')
    return ADMIN_MENU


async def main() -> None:
    """Start the bot."""
    application = Application.builder().token(TOKEN).build()

    worker_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("work", work_with_us_command)],
        states={
            WORKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_name)],
            WORKER_REG_NO: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_reg_no)],
            WORKER_MATRIC_NO: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_matric_no)],
            WORKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_phone)],
            WORKER_GENDER: [CallbackQueryHandler(worker_gender, pattern="^gender_")],
            WORKER_BANK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_bank_name)],
            WORKER_ACCOUNT_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_account_number)],
            WORKER_ACCOUNT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_account_name)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_start)],
        states={
            ADMIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_password)],
            ADMIN_MENU: [
                CallbackQueryHandler(admin_orders_menu, pattern="^admin_orders$"),
                CallbackQueryHandler(admin_workers_menu, pattern="^admin_workers$"),
                CallbackQueryHandler(admin_payments_menu, pattern="^admin_payments$"),
                CallbackQueryHandler(view_feedback_admin, pattern="^admin_feedback$"),
                CallbackQueryHandler(admin_main_menu_callback, pattern="^admin_main_menu$"),
                CallbackQueryHandler(view_active_orders_admin, pattern="^view_active_orders$"),
                CallbackQueryHandler(view_taken_orders_admin, pattern="^view_taken_orders_admin$"),
                CallbackQueryHandler(view_all_orders_admin, pattern=r"^view_all_orders_admin(_page_\d+)?$"),
                CallbackQueryHandler(view_workers_admin, pattern="^view_workers_admin$"),
                CallbackQueryHandler(view_pending_applications_admin, pattern="^view_pending_apps$"),
                CallbackQueryHandler(admin_checkin_menu, pattern="^admin_checkin$"),
                CallbackQueryHandler(handle_worker_approval, pattern="^(approve|reject)_"),
                CallbackQueryHandler(worker_accept_order, pattern="^accept_"),
                CallbackQueryHandler(decline_order, pattern="^decline_"),
            ],
            ADMIN_CHECKIN_MENU: [
                CallbackQueryHandler(handle_checkin_broadcast, pattern="^checkin_(rainy|cold|hot|sunday|casual)$"),
                CallbackQueryHandler(admin_custom_message_prompt, pattern="^checkin_custom$"),
                CallbackQueryHandler(admin_main_menu_callback, pattern="^admin_main_menu$"),
            ],
            ADMIN_VIEW_ORDER_DETAIL: [
                CallbackQueryHandler(admin_view_order_details, pattern=r"^admin_view_order_\d+$"),
            ],
            ADMIN_CUSTOM_MESSAGE_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_broadcast)
            ],
        },
        fallbacks=[CommandHandler("admin", admin_start), CommandHandler("start", start)],
    )
    
    main_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start), CallbackQueryHandler(start, pattern="^main_menu$")],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(kitchen_menu, pattern="^kitchen_menu$"),
                CallbackQueryHandler(cafe_menu, pattern="^cafe_menu$"),
                CallbackQueryHandler(view_orders, pattern=r"^view_orders(_page_\d+)?$"),
                CallbackQueryHandler(share_command, pattern="^share_bot$"),
                CallbackQueryHandler(faq_handler, pattern="^faq$"),
            ],
            KITCHEN_MENU: [
                CallbackQueryHandler(indomie_start, pattern="^indomie$"),
                CallbackQueryHandler(custard_start, pattern="^custard$"),
                CallbackQueryHandler(spaghetti_start, pattern="^spaghetti$"),
                CallbackQueryHandler(start, pattern="^main_menu$"),
            ],
            INDOMIE_SOURCE: [CallbackQueryHandler(indomie_source, pattern="^indomie_source_")],
            INDOMIE_FLAVOR: [CallbackQueryHandler(indomie_flavor, pattern="^flavor_")],
            INDOMIE_SIZE: [CallbackQueryHandler(indomie_size, pattern="^size_")],
            INDOMIE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_quantity)],
            INDOMIE_MIXINGS: [CallbackQueryHandler(indomie_mixings, pattern="^mixing_")],
            INDOMIE_TOPPINGS: [CallbackQueryHandler(indomie_toppings, pattern="^topping_")],
            INDOMIE_VEGETABLES_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_vegetables_quantity)],
            INDOMIE_SUYA_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_suya_amount)],
            INDOMIE_SARDINE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sardine_quantity)],
            INDOMIE_EGG_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_egg_quantity)],
            INDOMIE_SAUSAGE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sausage_quantity)],
            INDOMIE_CHICKEN_1000_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_chicken_1000_quantity)],
            INDOMIE_CHICKEN_1500_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_chicken_1500_quantity)],
            INDOMIE_CHICKEN_3000_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_chicken_3000_quantity)],
            INDOMIE_FRIED_FISH_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fried_fish_quantity)],
            INDOMIE_WATER_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_water_quantity)],
            INDOMIE_COKE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_coke_quantity)],
            INDOMIE_MALT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_malt_quantity)],
            INDOMIE_JUICE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_juice_quantity)],
            INDOMIE_ICE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ice_quantity)],
            CUSTARD_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custard_quantity)],
            CUSTARD_SOURCE: [CallbackQueryHandler(custard_source, pattern="^custard_source_")],
            CUSTARD_ADDITIONS: [CallbackQueryHandler(custard_additions, pattern="^custard_add_")],
            CUSTARD_SUGAR_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custard_sugar_quantity)],
            CUSTARD_MILK_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custard_milk_quantity)],
            GET_EXTRA_NOTES: [MessageHandler(filters.TEXT | filters.COMMAND, get_extra_notes)],
            ORDER_SUMMARY: [
                CallbackQueryHandler(proceed_to_payment, pattern="^proceed_to_payment$"),
                CallbackQueryHandler(view_bill, pattern="^view_bill$"),
                CallbackQueryHandler(show_order_summary, pattern="^back_to_summary$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            GET_PAYMENT_SCREENSHOT: [MessageHandler(filters.PHOTO, handle_payment_screenshot)],
            CAFE_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, cafe_order), CommandHandler("done", cafe_order_done)],
            GET_ROOM_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hall_and_room_number)],
            GET_DELIVERY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_delivery_time)],
            ASK_BEVERAGE: [CallbackQueryHandler(handle_beverage_selection, pattern="^bev_")],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    feedback_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("customer_feedback", customer_feedback_start)],
        states={CUSTOMER_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, customer_feedback_save)]},
        fallbacks=[CommandHandler("start", start)],
    )

    delivery_issue_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(user_not_delivered_order, pattern="^user_not_delivered_")],
        states={GET_DELIVERY_ISSUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_delivery_issue)]},
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(admin_conv_handler)
    application.add_handler(worker_conv_handler)
    application.add_handler(feedback_conv_handler)
    application.add_handler(delivery_issue_conv_handler)
    application.add_handler(main_conv_handler)
    
    # Top-level handlers
    application.add_handler(CommandHandler("share", share_command))
    application.add_handler(CallbackQueryHandler(review_order, pattern="^review_"))
    application.add_handler(CallbackQueryHandler(worker_accept_order, pattern="^accept_"))
    application.add_handler(CallbackQueryHandler(worker_delivered_order, pattern="^worker_delivered_"))
    application.add_handler(CallbackQueryHandler(worker_not_delivered_order, pattern="^worker_not_delivered_"))
    application.add_handler(CallbackQueryHandler(user_delivered_order, pattern="^user_delivered_"))
    application.add_handler(CallbackQueryHandler(copy_share_message_callback, pattern="^copy_share_message$"))
    
    application.add_error_handler(error_handler)

    async with application:
        webhook_url = os.getenv("WEBHOOK_URL")
        if webhook_url:
            await application.bot.set_webhook(f"{webhook_url}/{TOKEN}")
            logger.info(f"Webhook set to {webhook_url}/{TOKEN}")
        else:
            logger.warning("WEBHOOK_URL not set. Running in polling mode.")
            await application.run_polling()
            return

        async def telegram_handle(request):
            update = Update.de_json(await request.json(), application.bot)
            await application.process_update(update)
            return web.Response()

        async def health_check(_):
            return web.Response(text="OK")

        app = web.Application()
        app.router.add_post(f"/{TOKEN}", telegram_handle)
        app.router.add_get("/", health_check)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8080)))
        await site.start()
        await asyncio.Event().wait()


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.warning('Update "%s" caused error "%s"', update, context.error)

if __name__ == "__main__":
    asyncio.run(main())
