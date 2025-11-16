import logging
import json
import os
from datetime import datetime
import random
import asyncio
import json
import logging
import os
from urllib.parse import quote

from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
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
from database import (
    init_db, add_order, get_user_orders, get_todays_orders, get_all_orders,
    add_worker, get_all_workers, is_worker, update_order_status,
    get_worker_orders, get_order_by_id, get_all_unique_users,
    add_worker_application, get_worker_applications, update_worker_application_status,
    get_all_payments, add_feedback, get_all_feedback, get_orders_by_status
)
from messages import DAILY_MESSAGES, SHARE_MESSAGE

# Centralized price list for all items
PRICES = {
    # Indomie base prices
    "small_chicken": 350,
    "super_chicken": 450,
    "small_onion_chicken": 400,
    "super_onion_chicken": 500,

    # Mixings & Toppings
    "pepper_spice": 200,
    "crayfish_spice": 200,
    "vegetables": 800,
    "suya": 1,  # Special case: price is the quantity
    "egg": 400,
    "sausage": 400,
    "sardine": 1200,
    "chicken_1000": 1000,
    "chicken_1500": 1500,
    "chicken_3000": 3000,
    "fried_fish": 1500,

    # Beverages
    "water": 300,
    "soft_drink": 600,
    "malt": 800,
    "1ltr_drink": 2500,

    # Custard items
    "custard": 300,
    "sugar": 50,
    "milk": 400,
}


async def safe_edit_message(update: Update, text: str, reply_markup=None, parse_mode: str = None):
    """Safely edits a message if possible, otherwise sends a new one."""
    try:
        if update.callback_query:
            # If the message content or markup is different, edit the message
            if update.callback_query.message.text != text or update.callback_query.message.reply_markup != reply_markup:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
            else:
                # If the content is the same, just answer the callback query to remove the "loading" state
                await update.callback_query.answer()
        elif update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Error in safe_edit_message: {e}")

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
    INDOMIE_SOURCE,
    INDOMIE_QUANTITY,
    INDOMIE_KITCHEN_QUANTITY,
) = range(44)


async def start(update: Update, context: CallbackContext) -> int:
    """Displays the main menu."""
    keyboard = [
        [InlineKeyboardButton("🧑‍🍳 From Our Kitchen", callback_data="kitchen_menu")],
        [InlineKeyboardButton("☕ From Café", callback_data="cafe_menu")],
        [InlineKeyboardButton("👀 View My Orders", callback_data="view_orders")],
        [InlineKeyboardButton("🚀 Share Bot", callback_data="share_bot")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = "Welcome to Willis Kitchen 🍽️\nWhere would you like to order from?"
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    else:
        await safe_edit_message(update, welcome_text, reply_markup=reply_markup)
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
    await safe_edit_message(
        update, "Please choose a food option from our kitchen:", reply_markup=reply_markup
    )
    return KITCHEN_MENU


async def cafe_menu(update: Update, context: CallbackContext) -> int:
    """Initializes the Cafe order with the new data structure."""
    query = update.callback_query
    await query.answer()
    context.user_data["order"] = {
        "food": "Cafe Order",
        "items": [],
        "source": "cafe",
    }
    await safe_edit_message(
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

    # The `show_order_summary` function will calculate the total price and service charge from the `items` list.
    return await ask_for_hall_and_room_number(update, context)


async def confirm_cafe_order(update: Update, context: CallbackContext) -> int:
    """Saves the cafe order to the database."""
    query = update.callback_query
    await query.answer()
    order = context.user_data["order"]
    order_id = add_order(
        user_id=update.effective_user.id,
        username=update.effective_user.username,
        food_type=order["food"],
        mixings=None,
        toppings=None,
        quantities=order["quantities"],
        total=order["total"],
        source="cafe",
        hall_and_room_number=order["hall_and_room_number"],
        delivery_time=order["delivery_time"],
        service_charge=order["service_charge"],
    )

    # Notify workers
    await notify_workers(context, order_id)

    summary = "✅ Your order has been successfully placed!\n\n"
    summary += "Here’s your order summary:\n"
    summary += f"• {order['food']} x{order['quantities']['quantity']}\n"
    summary += f"Amount: ₦{order['quantities']['price']}\n"
    summary += f"Service Charge: ₦{order['service_charge']}\n"
    summary += f"Total: ₦{order['total']}\n\n"
    summary += f"Delivery to: {order['hall_and_room_number']}\n"
    summary += f"Delivery time: {order['delivery_time']}\n\n"
    summary += "Thank you for ordering from Willis Kitchen!"

    keyboard = [[InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await safe_edit_message(update, summary, reply_markup=reply_markup)
    return ConversationHandler.END


async def notify_workers(context: CallbackContext, order_id: int):
    """Notifies all active workers of a new order."""
    workers = get_all_workers()
    order = get_order_by_id(order_id)
    if not order:
        return

    _, _, username, food_type, _, _, _, total, _, source, _, _, _, _, _ = order

    notes = order[17]
    message = (
        f"📦 New Order Available:\n"
        f"From: @{username}\n"
        f"Order: {food_type}\n"
        f"Total Price: ₦{total}\n"
    )
    if notes:
        message += f"Notes: {notes}\n"

    keyboard = [[InlineKeyboardButton("✅ Take This Order", callback_data=f"take_{order_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    for worker_id in workers:
        try:
            await context.bot.send_message(chat_id=worker_id, text=message, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Failed to send message to worker {worker_id}: {e}")


async def work_with_us(update: Update, context: CallbackContext) -> int:
    """Starts the worker application process."""
    query = update.callback_query
    await query.answer()
    await safe_edit_message(update, "Please enter your full name:")
    return WORKER_NAME


async def work_with_us_command(update: Update, context: CallbackContext) -> int:
    """Starts the worker application process via command."""
    await update.message.reply_text("Please enter your full name:")
    return WORKER_NAME


async def worker_name(update: Update, context: CallbackContext) -> int:
    """Stores the worker's name and asks for their registration number."""
    context.user_data["worker_application"] = {"name": update.message.text}
    await update.message.reply_text("Please enter your registration number:")
    return WORKER_REG_NO


async def worker_reg_no(update: Update, context: CallbackContext) -> int:
    """Stores the worker's registration number and asks for their matric number."""
    context.user_data["worker_application"]["reg_no"] = update.message.text
    await update.message.reply_text("Please enter your matric number:")
    return WORKER_MATRIC_NO


async def worker_matric_no(update: Update, context: CallbackContext) -> int:
    """Stores the worker's matric number and asks for their phone number."""
    context.user_data["worker_application"]["matric_no"] = update.message.text
    await update.message.reply_text("Please enter your phone number:")
    return WORKER_PHONE


async def worker_phone(update: Update, context: CallbackContext) -> int:
    """Stores the worker's phone number, saves the application, and notifies the admin."""
    context.user_data["worker_application"]["phone"] = update.message.text

    application_data = context.user_data["worker_application"]
    user = update.effective_user

    # Save application to the database
    add_worker_application(
        user_id=user.id,
        username=user.username,
        name=application_data['name'],
        reg_no=application_data['reg_no'],
        matric_no=application_data['matric_no'],
        phone=application_data['phone']
    )

    # Notify admin
    admin_message = (
        f"🧑‍🍳 New Waiter Application:\n"
        f"Name: {application_data['name']}\n"
        f"User: @{user.username}\n"
        f"Phone: {application_data['phone']}\n\n"
        "You can approve or reject this from the /admin panel."
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message)

    # Notify user
    await update.message.reply_text(
        "✅ Thank you for applying to become a Willis Kitchen worker.\n"
        "Your request is being processed."
    )

    return ConversationHandler.END


async def handle_worker_approval(update: Update, context: CallbackContext) -> None:
    """Handles the admin's decision on a worker application from the admin panel."""
    query = update.callback_query
    await query.answer()

    action, app_id_str = query.data.split("_")
    application_id = int(app_id_str)

    # Retrieve application from DB
    apps = get_worker_applications()
    application_data = next((app for app in apps if app[0] == application_id), None)

    if not application_data:
        await safe_edit_message(update, "Application not found.")
        return

    user_id = application_data[1]

    if action == "approve":
        update_worker_application_status(application_id, 'approved')
        add_worker(
            user_id=user_id,
            name=application_data[3],
            reg_no=application_data[4],
            matric_no=application_data[5],
            phone=application_data[6],
        )
        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 Congratulations! You’ve been approved as a Willis Kitchen worker."
        )
        await safe_edit_message(update, f"Application {application_id} approved.")
    else: # Reject
        update_worker_application_status(application_id, 'rejected')
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Your application was not approved at this time."
        )
        await safe_edit_message(update, f"Application {application_id} rejected.")


async def share_command(update: Update, context: CallbackContext) -> None:
    """Sends the share message with share and copy buttons."""
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
        await safe_edit_message(update, SHARE_MESSAGE, reply_markup=reply_markup)
    else:
        await update.message.reply_text(SHARE_MESSAGE, reply_markup=reply_markup)


async def copy_share_message_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answers the callback query with a confirmation."""
    query = update.callback_query
    await query.answer("Copied ✅", show_alert=True)


async def back_to_kitchen_menu(update: Update, context: CallbackContext) -> int:
    """Returns to the kitchen menu."""
    return await kitchen_menu(update, context)


async def back_to_mixings(update: Update, context: CallbackContext) -> int:
    """Returns to the mixings menu."""
    return await indomie_mixings(update, context)


async def back_to_custard_quantity(update: Update, context: CallbackContext) -> int:
    """Returns to the custard quantity prompt."""
    return await custard_start(update, context)


async def ask_for_hall_and_room_number(update: Update, context: CallbackContext) -> int:
    """Asks for the user's hall and room number."""
    prompt = "Please enter your hall and room number (e.g., Peter Hall B204):"
    if update.callback_query:
        await safe_edit_message(update, prompt)
    else:
        await update.message.reply_text(prompt)
    return GET_ROOM_NUMBER


async def get_hall_and_room_number(update: Update, context: CallbackContext) -> int:
    """Stores the hall and room number and asks for the delivery time."""
    hall_and_room_number = update.message.text
    if not hall_and_room_number:
        await update.message.reply_text("Hall and room number cannot be empty. Please try again.")
        return GET_ROOM_NUMBER
    context.user_data["order"]["hall_and_room_number"] = hall_and_room_number
    await update.message.reply_text("What time would you like your order to be delivered?")
    return GET_DELIVERY_TIME


async def get_delivery_time(update: Update, context: CallbackContext) -> int:
    """Stores the delivery time and asks for extra notes."""
    context.user_data["order"]["delivery_time"] = update.message.text
    return await ask_for_extra_notes(update, context)


async def get_extra_notes(update: Update, context: CallbackContext) -> int:
    """Stores the extra notes and then proceeds to the order summary."""
    if update.message.text and update.message.text.lower() != '/skip':
        context.user_data["order"]["notes"] = update.message.text
    else:
        context.user_data["order"]["notes"] = None

    return await show_order_summary(update, context)


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
        await safe_edit_message(update, f"You have no {status} orders.")
        return WORKER_HISTORY

    message = f"📦 Your {status.capitalize()} Orders:\n"
    for order in orders:
        _, _, _, food_type, _, _, _, total, order_date, _, _, _, _, _, _ = order
        message += f"📅 {order_date} - {food_type} - ₦{total}\n"

    await safe_edit_message(update, message)
    return WORKER_HISTORY


async def take_order(update: Update, context: CallbackContext) -> None:
    """Handles a worker taking an order."""
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split("_")[1])
    worker_id = update.effective_user.id

    order = get_order_by_id(order_id)
    if order and order[10] == 'pending':
        update_order_status(order_id, 'taken', worker_id)
        await safe_edit_message(update, "✅ You have successfully taken this order.")

        # Notify other workers
        workers = get_all_workers()
        for other_worker_id in workers:
            if other_worker_id != worker_id:
                try:
                    await context.bot.send_message(
                        chat_id=other_worker_id,
                        text="⚠️ Order has been taken by another worker. Watch out for the next order."
                    )
                except Exception as e:
                    logger.error(f"Failed to send 'order taken' message to worker {other_worker_id}: {e}")
    else:
        await safe_edit_message(update, "This order has already been taken.")


async def indomie_start(update: Update, context: CallbackContext) -> int:
    """Initializes the Indomie order and asks for the source."""
    query = update.callback_query
    await query.answer()
    context.user_data["order"] = {
        "food": "Indomie",
        "items": [],
        "selected_mixings": [],
        "selected_toppings": [],
        "selected_beverages": [],
        "source": "",
    }
    keyboard = [
        [InlineKeyboardButton("I have my own Indomie", callback_data="indomie_source_own")],
        [InlineKeyboardButton("Use the kitchen's Indomie", callback_data="indomie_source_kitchen")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(update, "Will you be providing the Indomie, or should we use ours?", reply_markup=reply_markup)
    return INDOMIE_SOURCE


async def indomie_source(update: Update, context: CallbackContext) -> int:
    """Stores the source of the Indomie and proceeds accordingly."""
    query = update.callback_query
    await query.answer()
    source = query.data.split("_")[-1]  # 'own' or 'kitchen'
    context.user_data["order"]["source"] = source

    if source == 'own':
        # If user provides their own, set the base price to 0 and ask for quantity.
        context.user_data["order"]["items"].append({
            "name": "Indomie (Own)",
            "type": "base",
            "unit_price": 0,
            "quantity": 1, # Will be updated later
            "total_price": 0
        })
        await safe_edit_message(update, "How many packs of Indomie are you providing?")
        return INDOMIE_QUANTITY
    else: # kitchen
        # Proceed to flavor selection
        keyboard = [
            [InlineKeyboardButton("Chicken Flavour", callback_data="flavor_chicken")],
            [InlineKeyboardButton("Onion and Chicken", callback_data="flavor_onion_chicken")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await safe_edit_message(update, "Please choose a flavor:", reply_markup=reply_markup)
        return INDOMIE_FLAVOR


async def indomie_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of user's own Indomie and proceeds to mixings."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text("Please enter a valid number greater than 0.")
        return INDOMIE_QUANTITY

    order = context.user_data["order"]
    # There should only be one base item at this point
    for item in order.get("items", []):
        if item.get("type") == "base":
            item["quantity"] = quantity
            break

    # Skip flavor and size, go to mixings
    return await indomie_mixings_menu(update, context)


async def indomie_flavor(update: Update, context: CallbackContext) -> int:
    """Stores the flavor and asks for the size."""
    query = update.callback_query
    await query.answer()
    flavor = query.data.split("_")[1]
    context.user_data["order"]["flavor"] = flavor

    if flavor == "chicken":
        keyboard = [
            [InlineKeyboardButton("Small (₦350)", callback_data="size_small_350")],
            [InlineKeyboardButton("Super Pack (₦450)", callback_data="size_super_450")],
        ]
    else:  # Onion and Chicken
        keyboard = [
            [InlineKeyboardButton("Small (₦400)", callback_data="size_small_400")],
            [InlineKeyboardButton("Super Pack (₦500)", callback_data="size_super_500")],
        ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(update, "Please choose a size:", reply_markup=reply_markup)
    return INDOMIE_SIZE

async def indomie_size(update: Update, context: CallbackContext) -> int:
    """Stores the size and base price, then proceeds to the mixings menu."""
    query = update.callback_query
    await query.answer()
    size, price_str = query.data.split("_")[1:]
    price = int(price_str)
    context.user_data["order"]["size"] = size

    flavor = context.user_data["order"]["flavor"]
    item_name = f"Indomie ({flavor.replace('_', ' ').title()}, {size.title()})"

    # The 'items' list will now hold all order components.
    # We start by adding the base Indomie item.
    items = context.user_data["order"].get("items", [])
    # Remove any previously added base item to prevent duplicates if user goes back.
    items = [item for item in items if item.get("type") != "base"]

    # Get the quantity, which is 1 if the kitchen is providing it.
    quantity = 1

    items.append({
        "name": item_name,
        "type": "base",
        "unit_price": price,
        "quantity": quantity,
        "total_price": price * quantity
    })
    context.user_data["order"]["items"] = items

    await safe_edit_message(update, "How many packs of Indomie would you like?")
    return INDOMIE_KITCHEN_QUANTITY


async def indomie_kitchen_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of kitchen's Indomie and proceeds to mixings."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text("Please enter a valid number greater than 0.")
        return INDOMIE_KITCHEN_QUANTITY

    order = context.user_data["order"]
    # Find the base item and update its quantity and total price
    for item in order.get("items", []):
        if item.get("type") == "base":
            item["quantity"] = quantity
            item["total_price"] = item["unit_price"] * quantity
            break

    return await indomie_mixings_menu(update, context)


async def indomie_mixings_menu(update: Update, context: CallbackContext) -> int:
    """Displays the mixings menu."""
    keyboard = [
        [
            InlineKeyboardButton("Pepper Spice (₦200)", callback_data="mixing_pepper_spice"),
            InlineKeyboardButton("Crayfish Spice (₦200)", callback_data="mixing_crayfish_spice"),
        ],
        [
            InlineKeyboardButton("Vegetables (₦800)", callback_data="mixing_vegetables"),
            InlineKeyboardButton("Suya (price-based)", callback_data="mixing_suya"),
        ],
        [
            InlineKeyboardButton("Sardine (₦1200)", callback_data="mixing_sardine"),
        ],
        [InlineKeyboardButton("None", callback_data="mixing_none")],
        [InlineKeyboardButton("Done ✅", callback_data="mixing_done")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = "Please select your mixings:"
    if update.callback_query:
        await safe_edit_message(update, message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)

    return INDOMIE_MIXINGS

async def indomie_mixings(update: Update, context: CallbackContext) -> int:
    """Handles mixing selections using the new data structure."""
    query = update.callback_query
    await query.answer()
    selection = query.data.split("_", 1)[1]  # e.g., "pepper_spice", "vegetables", "done"

    order = context.user_data["order"]
    items = order.get("items", [])
    selected_mixings = order.get("selected_mixings", [])

    if selection == "done":
        return await ask_for_mixing_quantities(update, context)

    if selection == "none":
        # Clear all previously selected mixings and spices
        order["selected_mixings"] = []
        order["items"] = [item for item in items if item.get("type") not in ["mixing", "spice"]]
        return await ask_for_mixing_quantities(update, context)

    item_name = selection

    if "spice" in item_name:
        # Spices have no quantity, add/remove directly from items list
        existing_item = next((item for item in items if item["name"] == item_name), None)
        if existing_item:
            items.remove(existing_item)
        else:
            price = PRICES.get(item_name, 0)
            items.append({"name": item_name, "type": "spice", "unit_price": price, "quantity": 1, "total_price": price})
    else:
        # For other mixings, add/remove from a temporary selection list
        if item_name in selected_mixings:
            selected_mixings.remove(item_name)
        else:
            selected_mixings.append(item_name)

    # Display what's been selected so far
    display_items = [item['name'].title() for item in items if item['type'] == 'spice']
    display_items.extend([mixing.title() for mixing in selected_mixings])
    selected_text = ", ".join(display_items)

    await safe_edit_message(
        update,
        f"Selected mixings: {selected_text}\n\nPlease select your mixings:",
        reply_markup=indomie_mixings_keyboard(),
    )
    return INDOMIE_MIXINGS


def indomie_mixings_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("Pepper Spice (₦200)", callback_data="mixing_pepper_spice"),
            InlineKeyboardButton("Crayfish Spice (₦200)", callback_data="mixing_crayfish_spice"),
        ],
        [
            InlineKeyboardButton("Vegetables (₦800)", callback_data="mixing_vegetables"),
            InlineKeyboardButton("Suya (price-based)", callback_data="mixing_suya"),
        ],
        [
            InlineKeyboardButton("Sardine (₦1200)", callback_data="mixing_sardine"),
        ],
        [InlineKeyboardButton("None", callback_data="mixing_none")],
        [InlineKeyboardButton("Done ✅", callback_data="mixing_done")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def ask_for_mixing_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of each selected mixing, one by one."""
    selected_mixings = context.user_data["order"].get("selected_mixings", [])

    # Find the first mixing that doesn't have a corresponding item in the items list yet
    items = context.user_data["order"].get("items", [])
    item_names_in_order = [item['name'] for item in items]

    next_mixing_to_ask = next((mixing for mixing in selected_mixings if mixing not in item_names_in_order), None)

    if next_mixing_to_ask:
        message_text = ""
        next_state = -1
        if next_mixing_to_ask == "vegetables":
            message_text = "How many servings of vegetables would you like?"
            next_state = INDOMIE_VEGETABLES_QUANTITY
        elif next_mixing_to_ask == "suya":
            message_text = "Enter the amount for suya (₦):"
            next_state = INDOMIE_SUYA_AMOUNT
        elif next_mixing_to_ask == "sardine":
            message_text = "How many servings of sardine would you like?"
            next_state = INDOMIE_SARDINE_QUANTITY

        if update.callback_query:
            await update.callback_query.edit_message_text(message_text)
        else:
            await update.message.reply_text(message_text)
        return next_state

    # If all mixing quantities are gathered, move to toppings
    return await indomie_toppings_menu(update, context)


async def indomie_toppings_menu(update: Update, context: CallbackContext) -> int:
    """Displays the toppings menu."""
    keyboard = [
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
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(update, "Please select your toppings:", reply_markup=reply_markup)
    return INDOMIE_TOPPINGS

async def indomie_toppings(update: Update, context: CallbackContext) -> int:
    """Handles topping selections using the new data structure."""
    query = update.callback_query
    await query.answer()
    selection = query.data.split("_", 1)[1]

    order = context.user_data["order"]
    selected_toppings = order.get("selected_toppings", [])

    if selection == "done":
        return await ask_for_topping_quantities(update, context)

    if selection == "none":
        order["selected_toppings"] = []
        # Remove any items of type 'topping' that might have been added
        order["items"] = [item for item in order.get("items", []) if item.get("type") != "topping"]
        return await ask_for_topping_quantities(update, context)

    item_name = selection

    if item_name in selected_toppings:
        selected_toppings.remove(item_name)
    else:
        selected_toppings.append(item_name)

    await safe_edit_message(
        update,
        f"Selected toppings: {', '.join(selected_toppings).title()}\n\nPlease select your toppings:",
        reply_markup=indomie_toppings_keyboard(),
    )
    return INDOMIE_TOPPINGS

def indomie_toppings_keyboard():
    keyboard = [
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
    ]
    return InlineKeyboardMarkup(keyboard)

async def ask_for_topping_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of each selected topping, one by one."""
    selected_toppings = context.user_data["order"].get("selected_toppings", [])

    items = context.user_data["order"].get("items", [])
    item_names_in_order = [item['name'] for item in items]

    next_topping_to_ask = next((topping for topping in selected_toppings if topping not in item_names_in_order), None)

    if next_topping_to_ask:
        message_text = ""
        next_state = -1
        if next_topping_to_ask == "egg":
            message_text = "How many eggs would you like?"
            next_state = INDOMIE_EGG_QUANTITY
        elif next_topping_to_ask == "sausage":
            message_text = "How many sausages would you like?"
            next_state = INDOMIE_SAUSAGE_QUANTITY
        elif next_topping_to_ask == "chicken_1000":
            message_text = "How many pieces of chicken (₦1000) would you like?"
            next_state = INDOMIE_CHICKEN_1000_QUANTITY
        elif next_topping_to_ask == "chicken_1500":
            message_text = "How many pieces of chicken (₦1500) would you like?"
            next_state = INDOMIE_CHICKEN_1500_QUANTITY
        elif next_topping_to_ask == "chicken_3000":
            message_text = "How many pieces of chicken (₦3000) would you like?"
            next_state = INDOMIE_CHICKEN_3000_QUANTITY
        elif next_topping_to_ask == "fried_fish":
            message_text = "How many pieces of fried fish would you like?"
            next_state = INDOMIE_FRIED_FISH_QUANTITY

        if update.callback_query:
            await update.callback_query.edit_message_text(message_text)
        else:
            await update.message.reply_text(message_text)
        return next_state

    # If all topping quantities are gathered, move to beverages
    return await ask_for_beverages(update, context)


async def ask_for_beverages(update: Update, context: CallbackContext) -> int:
    """Displays the beverage selection menu."""
    keyboard = beverage_keyboard()
    message = "Would you like any drink or beverage with your order?"
    if update.callback_query:
        await safe_edit_message(update, message, reply_markup=keyboard)
    else:
        await update.message.reply_text(message, reply_markup=keyboard)
    return ASK_BEVERAGE


def beverage_keyboard():
    """Returns the keyboard for the beverage menu."""
    keyboard = [
        [
            InlineKeyboardButton("Water (₦300)", callback_data="bev_water"),
            InlineKeyboardButton("Soft Drink (₦600)", callback_data="bev_soft_drink"),
        ],
        [
            InlineKeyboardButton("Malt (₦800)", callback_data="bev_malt"),
            InlineKeyboardButton("1Ltr Drink (₦2500)", callback_data="bev_1ltr_drink"),
        ],
        [InlineKeyboardButton("None", callback_data="bev_none")],
        [InlineKeyboardButton("Done ✅", callback_data="bev_done")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def ask_for_beverage_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of each selected beverage, one by one."""
    selected_beverages = context.user_data["order"].get("selected_beverages", [])

    items = context.user_data["order"].get("items", [])
    item_names_in_order = [item['name'] for item in items]

    next_beverage_to_ask = next((beverage for beverage in selected_beverages if beverage not in item_names_in_order), None)

    if next_beverage_to_ask:
        message_text = ""
        next_state = -1
        if next_beverage_to_ask == "water":
            message_text = "How many bottles of water would you like?"
            next_state = INDOMIE_WATER_QUANTITY
        elif next_beverage_to_ask == "soft_drink":
            message_text = "How many soft drinks would you like?"
            next_state = INDOMIE_COKE_QUANTITY
        elif next_beverage_to_ask == "malt":
            message_text = "How many malts would you like?"
            next_state = INDOMIE_MALT_QUANTITY
        elif next_beverage_to_ask == "1ltr_drink":
            message_text = "How many 1Ltr drinks would you like?"
            next_state = INDOMIE_JUICE_QUANTITY

        if update.callback_query:
            await update.callback_query.edit_message_text(message_text)
        else:
            await update.message.reply_text(message_text)
        return next_state

    return await ask_for_hall_and_room_number(update, context)


async def ask_for_extra_notes(update: Update, context: CallbackContext) -> int:
    """Asks the user for extra notes."""
    message = "Would you like to add any extra notes for the chef or delivery person? (Type /skip if none)"
    
    # We need to handle both callback query and message updates
    if update.callback_query:
        await safe_edit_message(update, message)
    else:
        # This case happens when the user just entered a quantity
        await update.message.reply_text(message)
        
    return GET_EXTRA_NOTES


async def get_beverage_quantity(update: Update, context: CallbackContext, beverage_name: str, next_state_constant: int) -> int:
    """Generic function to handle beverage quantity with the new data structure."""
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
            "name": beverage_name,
            "type": "beverage",
            "unit_price": unit_price,
            "quantity": quantity,
            "total_price": unit_price * quantity,
        })
        order["items"] = items

        return await ask_for_beverage_quantities(update, context)

    except (ValueError, TypeError):
        await update.message.reply_text("Invalid input. Please enter a number.")
        return next_state_constant

async def get_water_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of water and shows the order summary."""
    return await get_beverage_quantity(update, context, "water", INDOMIE_WATER_QUANTITY)

async def get_coke_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of soft drinks and shows the order summary."""
    return await get_beverage_quantity(update, context, "soft_drink", INDOMIE_COKE_QUANTITY)

async def get_malt_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of malt and shows the order summary."""
    return await get_beverage_quantity(update, context, "malt", INDOMIE_MALT_QUANTITY)

async def get_juice_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of juice and shows the order summary."""
    return await get_beverage_quantity(update, context, "1ltr_drink", INDOMIE_JUICE_QUANTITY)

async def get_topping_quantity(update: Update, context: CallbackContext, topping_name: str, next_state_constant: int) -> int:
    """Generic function to handle topping quantity with the new data structure."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            await update.message.reply_text("Please enter a valid number greater than 0.")
            return next_state_constant

        # Add the topping as a new item in the order['items'] list
        order = context.user_data["order"]
        items = order.get("items", [])
        unit_price = PRICES.get(topping_name.lower(), 0)

        # Remove existing item if user is re-entering quantity
        items = [item for item in items if item.get("name") != topping_name]

        items.append({
            "name": topping_name,
            "type": "topping",
            "unit_price": unit_price,
            "quantity": quantity,
            "total_price": unit_price * quantity,
        })
        order["items"] = items

        # After getting quantity, we re-call ask_for_topping_quantities to see if there's another topping.
        return await ask_for_topping_quantities(update, context)

    except (ValueError, TypeError):
        await update.message.reply_text("Invalid input. Please enter a number.")
        return next_state_constant


async def get_mixing_quantity(update: Update, context: CallbackContext, mixing_name: str, next_state_constant: int) -> int:
    """Generic function to handle mixing quantity with the new data structure."""
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
            "name": mixing_name,
            "type": "mixing",
            "unit_price": unit_price,
            "quantity": quantity,
            "total_price": unit_price * quantity,
        })
        order["items"] = items

        return await ask_for_mixing_quantities(update, context)

    except (ValueError, TypeError):
        await update.message.reply_text("Invalid input. Please enter a number.")
        return next_state_constant


async def get_sardine_quantity(update: Update, context: CallbackContext) -> int:
    return await get_mixing_quantity(update, context, "sardine", INDOMIE_SARDINE_QUANTITY)


async def get_vegetable_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of vegetables."""
    return await get_mixing_quantity(update, context, "vegetables", INDOMIE_VEGETABLES_QUANTITY)


async def get_suya_amount(update: Update, context: CallbackContext) -> int:
    """Stores the amount of suya."""
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

async def ask_for_delivery_time(update: Update, context: CallbackContext) -> int:
    """Asks for the delivery time."""
    await safe_edit_message(update, "When would you like your order delivered?")
    return GET_DELIVERY_TIME

async def handle_beverage_selection(update: Update, context: CallbackContext) -> int:
    """Handles beverage selections using the new data structure."""
    query = update.callback_query
    await query.answer()
    selection = query.data.split("_", 1)[1]

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

    await safe_edit_message(
        update,
        f"Selected beverages: {', '.join(selected_beverages).title()}\n\nPlease select your beverages:",
        reply_markup=beverage_keyboard(),
    )
    return ASK_BEVERAGE


async def custard_start(update: Update, context: CallbackContext) -> int:
    """Initializes the Custard order and asks for its source."""
    query = update.callback_query
    await query.answer()
    context.user_data["order"] = {
        "food": "Custard",
        "items": [],
        "selected_additions": [],
    }
    keyboard = [
        [
            InlineKeyboardButton("I have my own Custard", callback_data="custard_source_own"),
            InlineKeyboardButton("Use the kitchen's Custard", callback_data="custard_source_kitchen"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        update,
        "Will you be providing the Custard, or should we use ours?",
        reply_markup=reply_markup,
    )
    return CUSTARD_SOURCE


async def custard_source(update: Update, context: CallbackContext) -> int:
    """Stores the source of the Custard and asks for the quantity."""
    query = update.callback_query
    await query.answer()
    source = query.data.split("_")[-1]  # 'own' or 'kitchen'

    unit_price = PRICES.get("custard", 0)
    if source == 'own':
        unit_price = 0

    # Add the base custard item here, but with quantity 1 for now.
    # The quantity will be updated in the next step.
    context.user_data["order"]["items"].append({
        "name": "Custard",
        "type": "base",
        "unit_price": unit_price,
        "quantity": 1, # Placeholder
        "total_price": 0 # Placeholder
    })

    await safe_edit_message(update, "How many custard cups would you like to make?")
    return CUSTARD_QUANTITY


async def custard_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of custard and asks for additions."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text("Please enter a valid number greater than 0.")
        return CUSTARD_QUANTITY

    order = context.user_data["order"]
    # Find the base item and update its quantity and total price
    for item in order.get("items", []):
        if item.get("type") == "base":
            item["quantity"] = quantity
            item["total_price"] = item["unit_price"] * quantity
            break

    keyboard = custard_additions_keyboard()
    await update.message.reply_text(
        "What would you like to add to your custard?",
        reply_markup=keyboard,
    )
    return CUSTARD_ADDITIONS


def custard_additions_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("Sugar", callback_data="custard_add_sugar"),
            InlineKeyboardButton("Milk", callback_data="custard_add_milk"),
        ],
        [
            InlineKeyboardButton("None", callback_data="custard_add_none"),
            InlineKeyboardButton("Done ✅", callback_data="custard_add_done"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def custard_additions(update: Update, context: CallbackContext) -> int:
    """Handles the selection of custard additions."""
    query = update.callback_query
    await query.answer()
    selection = query.data.split("_", 2)[2]

    order = context.user_data["order"]
    selected_additions = order.get("selected_additions", [])

    if selection == "done":
        return await ask_for_custard_quantities(update, context)

    if selection == "none":
        order["selected_additions"] = []
        # Remove any items of type 'addition' that might have been added
        order["items"] = [item for item in order.get("items", []) if item.get("type") != "addition"]
        return await ask_for_custard_quantities(update, context)

    item_name = selection

    if item_name in selected_additions:
        selected_additions.remove(item_name)
    else:
        selected_additions.append(item_name)

    await safe_edit_message(
        update,
        f"Selected additions: {', '.join(selected_additions).title()}\n\nPlease select additions:",
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
        message_text = ""
        next_state = -1
        if next_addition_to_ask == "sugar":
            message_text = "How many spoons of sugar would you like?"
            next_state = CUSTARD_SUGAR_QUANTITY
        elif next_addition_to_ask == "milk":
            message_text = "How many sachets of milk would you like?"
            next_state = CUSTARD_MILK_QUANTITY

        if update.callback_query:
            await update.callback_query.edit_message_text(message_text)
        else:
            await update.message.reply_text(message_text)
        return next_state

    # If all quantities are gathered, move to the next step
    return await ask_for_hall_and_room_number(update, context)


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

    # Remove existing item if user is re-entering quantity
    items = [item for item in items if item.get("name") != item_name]

    items.append({
        "name": item_name,
        "type": "addition",
        "unit_price": unit_price,
        "quantity": quantity,
        "total_price": unit_price * quantity,
    })
    order["items"] = items

    return await ask_for_custard_quantities(update, context)


async def custard_sugar_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of sugar."""
    return await get_custard_addition_quantity(update, context, "sugar", CUSTARD_SUGAR_QUANTITY)


async def custard_milk_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of milk."""
    return await get_custard_addition_quantity(update, context, "milk", CUSTARD_MILK_QUANTITY)


async def spaghetti_start(update: Update, context: CallbackContext) -> int:
    """Handles the Spaghetti option."""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_kitchen_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(
        update, "Please contact customer care for more info 📞", reply_markup=reply_markup
    )
    return KITCHEN_MENU


async def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels the conversation and returns to the main menu."""
    query = update.callback_query
    await query.answer()
    return await start(update, context)


async def show_order_summary(update: Update, context: CallbackContext) -> int:
    """Calculates the total price and shows the order summary using the new data structure."""
    order = context.user_data["order"]
    summary = f"{update.effective_user.first_name} (@{update.effective_user.username})\n"
    summary += "Here is your order:\n\n"

    items = order.get("items", [])
    total = sum(item.get("total_price", 0) for item in items)

    # Calculate service charge: ₦250 per Indomie or Custard item, based on quantity
    service_charge = 0
    for item in items:
        if item.get("type") == "base":
            name = item.get("name", "").lower()
            if "indomie" in name or "custard" in name:
                service_charge += item.get("quantity", 0) * 250
    total += service_charge
    order["service_charge"] = service_charge
    order["total"] = total

    # Build summary text from items
    for item in items:
        name = item.get("name", "Unknown Item").title()
        quantity = item.get("quantity", 0)
        summary += f"• {name} (x{quantity})\n"
        
    summary += f"Service Charge: ₦{service_charge}\n"

    # Add notes to the summary if they exist
    if order.get("notes"):
        summary += f"<b>Notes:</b> {order['notes']}\n"

    summary += "----------------------\n"
    summary += f"<b>Total: ₦{total}</b>\n\n"
    summary += "Pay Online:\n"
    summary += "https://pay-naira.netlify.app\n"
    summary += "<i>open link in browser</i>"

    keyboard = [
        [
            InlineKeyboardButton("✅ I have paid", callback_data="proceed_to_payment"),
            InlineKeyboardButton("💵 View Bill", callback_data="view_bill"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await safe_edit_message(update, summary, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(summary, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

    return ORDER_SUMMARY


async def proceed_to_payment(update: Update, context: CallbackContext) -> int:
    """Saves the order with a 'pending_payment' status and asks for a screenshot."""
    query = update.callback_query
    await query.answer()
    order = context.user_data["order"]

    # The 'quantities' field in the database will now store the list of item dicts.
    order_id = add_order(
        user_id=update.effective_user.id,
        username=update.effective_user.username,
        food_type=order["food"],
        mixings=json.dumps(order.get("selected_mixings", [])),
        toppings=json.dumps(order.get("selected_toppings", [])),
        quantities=json.dumps(order.get("items", [])),  # Storing the detailed items list
        total=order["total"],
        hall_and_room_number=order.get("hall_and_room_number"),
        delivery_time=order.get("delivery_time"),
        status='pending_payment'
    )
    context.user_data["order_id"] = order_id

    await safe_edit_message(
        update, "Your order has been saved. Please upload a screenshot of your payment to complete the order."
    )
    return GET_PAYMENT_SCREENSHOT


async def handle_payment_screenshot(update: Update, context: CallbackContext) -> int:
    """Handles the payment screenshot, finalizes the order, and notifies workers."""
    order_id = context.user_data.get("order_id")
    if not order_id:
        await update.message.reply_text("Something went wrong. Please try placing your order again.")
        return ConversationHandler.END

    # Assuming add_payment function exists and works as intended
    # add_payment(order_id, update.message.photo[-1].file_id)
    update_order_status(order_id, 'pending')

    await notify_workers(context, order_id)

    await update.message.reply_text(
        "✅ Payment received! Your order has been placed and our workers have been notified.\n"
        "You will receive a notification once your order is accepted."
    )
    return ConversationHandler.END


async def confirm_order(update: Update, context: CallbackContext) -> int:
    """Saves the order to the database."""
    query = update.callback_query
    await query.answer()
    order = context.user_data["order"]

    order_id = add_order(
        user_id=update.effective_user.id,
        username=update.effective_user.username,
        food_type=order["food"],
        mixings=json.dumps(order.get("selected_mixings", [])),
        toppings=json.dumps(order.get("selected_toppings", [])),
        quantities=json.dumps(order.get("items", [])),
        total=order["total"],
        hall_and_room_number=order.get("hall_and_room_number"),
        delivery_time=order.get("delivery_time"),
    )

    await notify_workers(context, order_id)

    summary = "✅ Your order has been successfully placed!\n\n"
    summary += "Here’s your order summary:\n"
    for item in order.get("items", []):
        summary += f"• {item['name']} x{item['quantity']}\n"
    if order.get("notes"):
        summary += f"\n**Notes:** {order['notes']}\n"
    summary += f"Total: ₦{order['total']}\n\n"
    summary += f"Delivery to: {order['hall_and_room_number']}\n"
    summary += f"Delivery time: {order['delivery_time']}\n\n"
    summary += "Thank you for ordering from Willis Kitchen!"

    keyboard = [[InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await safe_edit_message(update, summary, reply_markup=reply_markup)
    return ConversationHandler.END


async def view_bill(update: Update, context: CallbackContext) -> int:
    """Shows the billing breakdown using the new data structure."""
    query = update.callback_query
    await query.answer()
    order = context.user_data["order"]
    bill = "📋 **Billing Breakdown**:\n"

    items = order.get("items", [])
    subtotal = 0

    # Iterate through each item and add its details to the bill
    for item in items:
        name = item.get("name", "N/A").title()
        quantity = item.get("quantity", 0)
        unit_price = item.get("unit_price", 0)
        item_total = item.get("total_price", 0)

        if item.get('type') == 'base' or 'spice' in item.get('type', ''):
             bill += f"• {name} = ₦{item_total}\n"
        elif name.lower() == 'suya':
            bill += f"• {name} (Amount) = ₦{item_total}\n"
        else:
            bill += f"• {name} ({quantity} × ₦{unit_price}) = ₦{item_total}\n"
        subtotal += item_total

    # Recalculate service charge for the bill view
    service_charge = 0
    for item in items:
        if item.get("type") == "base":
            name = item.get("name", "").lower()
            if "indomie" in name or "custard" in name:
                service_charge += item.get("quantity", 0) * 250
    total = subtotal + service_charge

    bill += f"Service Charge: ₦{service_charge}\n"
    bill += "----------------------\n"
    bill += f"💰 <b>Total = ₦{total}</b>"

    # Ensure the order total is up-to-date
    context.user_data["order"]["total"] = total

    keyboard = [
        [
            InlineKeyboardButton("✅ I have paid", callback_data="proceed_to_payment"),
            InlineKeyboardButton("⬅️ Back", callback_data="back_to_summary"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await safe_edit_message(update, bill, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    return ORDER_SUMMARY


async def view_orders(update: Update, context: CallbackContext) -> int:
    """Displays the user's past orders from the new data structure."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    orders_data = get_user_orders(user_id)

    if not orders_data:
        await safe_edit_message(update, "You have no orders yet. Start by placing one 🍽️")
        return MAIN_MENU

    message = "📦 *Your Past Orders*:\n\n"
    total_spent = 0
    for i, order_tuple in enumerate(orders_data):
        order = {
            "id": order_tuple[0], "user_id": order_tuple[1], "username": order_tuple[2],
            "food_type": order_tuple[3], "mixings": order_tuple[4], "toppings": order_tuple[5],
            "quantities": order_tuple[6], "total": order_tuple[7], "order_date": order_tuple[8],
            "source": order_tuple[9], "status": order_tuple[10], "taken_by": order_tuple[11],
            "hall_and_room_number": order_tuple[12], "delivery_time": order_tuple[13],
            "service_charge": order_tuple[14], "flavor": order_tuple[15], "size": order_tuple[16],
            "notes": order_tuple[17]
        }

        message += f"*Order #{i+1}* - Placed on {order['order_date']}\n"

        try:
            items = json.loads(order['quantities'])
            for item in items:
                name = item.get("name", "Unknown Item").title()
                quantity = item.get("quantity", 0)
                message += f"  - {name} (x{quantity})\n"
        except (json.JSONDecodeError, TypeError):
            message += "  - Error displaying order details.\n"

        message += f"  *Total: ₦{order['total']}*\n\n"
        total_spent += order['total']

    message += "-------------------\n"
    message += f"*Total Spent: ₦{total_spent}*"

    keyboard = [[InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await safe_edit_message(update, message, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    return MAIN_MENU


async def admin_start(update: Update, context: CallbackContext) -> int:
    """Asks for the admin password or shows the menu if already logged in."""
    user_id = update.effective_user.id
    if user_id in context.bot_data and "login_time" in context.bot_data[user_id]:
        time_diff = datetime.now() - context.bot_data[user_id]["login_time"]
        if time_diff.total_seconds() < 600:  # 10 minutes
            keyboard = [
                [InlineKeyboardButton("📦 Orders", callback_data="admin_orders")],
                [InlineKeyboardButton("👷‍♂️ Workers", callback_data="admin_workers")],
                [InlineKeyboardButton("💳 Payments", callback_data="admin_payments")],
                [InlineKeyboardButton("📝 Customer Feedbacks", callback_data="admin_feedback")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Welcome back, Admin! What would you like to do?", reply_markup=reply_markup)
            return ADMIN_MENU

    await update.message.reply_text("Enter the admin password:")
    return ADMIN_PASSWORD


async def admin_main_menu_callback(update: Update, context: CallbackContext) -> int:
    """Displays the main admin menu."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("📦 Orders", callback_data="admin_orders")],
        [InlineKeyboardButton("👷‍♂️ Workers", callback_data="admin_workers")],
        [InlineKeyboardButton("💳 Payments", callback_data="admin_payments")],
        [InlineKeyboardButton("📝 Customer Feedbacks", callback_data="admin_feedback")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message(update, "Welcome Admin 👑 What would you like to manage today?", reply_markup=reply_markup)
    return ADMIN_MENU


async def admin_password(update: Update, context: CallbackContext) -> int:
    """Checks the admin password and shows the new admin dashboard."""
    if update.message:
        password = update.message.text
        if password == "wiliwili":
            context.bot_data[update.effective_user.id] = {"login_time": datetime.now()}
            keyboard = [
                [InlineKeyboardButton("📦 Orders", callback_data="admin_orders")],
                [InlineKeyboardButton("👷‍♂️ Workers", callback_data="admin_workers")],
                [InlineKeyboardButton("💳 Payments", callback_data="admin_payments")],
                [InlineKeyboardButton("📝 Customer Feedbacks", callback_data="admin_feedback")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Welcome Admin 👑 What would you like to manage today?", reply_markup=reply_markup)
            return ADMIN_MENU
        else:
            await update.message.reply_text("Incorrect password.")
            return ConversationHandler.END
    return ConversationHandler.END

def admin_orders_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View Active Orders", callback_data="view_active_orders")],
        [InlineKeyboardButton("View All Taken Orders", callback_data="view_taken_orders_admin")],
        [InlineKeyboardButton("View All Placed Orders", callback_data="view_all_orders_admin")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")],
    ])

async def admin_orders_menu(update: Update, context: CallbackContext) -> int:
    """Displays the order management menu for admins."""
    query = update.callback_query
    await query.answer()
    await safe_edit_message(update, "📦 Order Management", reply_markup=admin_orders_menu_keyboard())
    return ADMIN_MENU

def admin_workers_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View Workers", callback_data="view_workers_admin")],
        [InlineKeyboardButton("View Active Applications", callback_data="view_active_apps")],
        [InlineKeyboardButton("View All Applications", callback_data="view_all_apps")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")],
    ])

async def admin_workers_menu(update: Update, context: CallbackContext) -> int:
    """Displays the worker management menu for admins."""
    query = update.callback_query
    await query.answer()
    await safe_edit_message(update, "👷‍♂️ Worker Management", reply_markup=admin_workers_menu_keyboard())
    return ADMIN_MENU

async def admin_payments_menu(update: Update, context: CallbackContext) -> int:
    """Displays the payment management menu for admins."""
    query = update.callback_query
    await query.answer()
    payments = get_all_payments()
    if not payments:
        await safe_edit_message(update, "No payments found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")]]))
        return ADMIN_MENU

    for order_id, screenshot_file_id, username, total in payments:
        caption = f"Payment for Order #{order_id} from @{username} (Total: ₦{total})"
        try:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=screenshot_file_id, caption=caption)
        except Exception as e:
            await query.message.reply_text(f"Could not load payment for Order #{order_id}. Error: {e}")

    keyboard = [[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("All payment screenshots displayed.", reply_markup=reply_markup)
    return ADMIN_MENU


async def send_daily_messages(bot):
    """Sends a daily message to all unique users."""
    user_ids = get_all_unique_users()
    message = random.choice(DAILY_MESSAGES)
    for user_id in user_ids:
        try:
            await bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            logger.error(f"Failed to send daily message to user {user_id}: {e}")

# New admin functions
async def view_active_orders_admin(update: Update, context: CallbackContext) -> int:
    """Displays active (pending) orders to the admin with action buttons."""
    query = update.callback_query
    await query.answer()
    orders_data = get_orders_by_status(('pending', 'pending_payment'))
    if not orders_data:
        await safe_edit_message(update, "No active orders yet.", reply_markup=admin_orders_menu_keyboard())
        return ADMIN_MENU

    await safe_edit_message(update, "📦 Active Orders:")
    for order_tuple in orders_data:
        order_id, _, username, food_type, _, _, _, total, _, _, _, _, _, _, _, _, _, _ = order_tuple
        message = f"ID: {order_id}, User: @{username}, Order: {food_type}, Total: ₦{total}"
        keyboard = [
            [
                InlineKeyboardButton("✅ Accept", callback_data=f"admin_accept_{order_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject_{order_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(text=message, reply_markup=reply_markup)

    return ADMIN_MENU

async def view_taken_orders_admin(update: Update, context: CallbackContext) -> int:
    """Displays all taken orders to the admin."""
    query = update.callback_query
    await query.answer()
    orders_data = get_orders_by_status('taken')
    if not orders_data:
        await safe_edit_message(update, "No taken orders yet.", reply_markup=admin_orders_menu_keyboard())
        return ADMIN_MENU

    message = "📦 Taken Orders:\n"
    for order_tuple in orders_data:
        order_id, _, username, _, _, _, _, total, _, _, _, worker_id, _, _, _, _, _, _ = order_tuple
        message += f"ID: {order_id}, User: @{username}, Worker: {worker_id}, Total: ₦{total}\n"
    await safe_edit_message(update, message, reply_markup=admin_orders_menu_keyboard())
    return ADMIN_MENU

async def view_all_orders_admin(update: Update, context: CallbackContext) -> int:
    """Displays all orders to the admin."""
    query = update.callback_query
    await query.answer()
    orders_data = get_all_orders()
    if not orders_data:
        await safe_edit_message(update, "No placed orders yet.", reply_markup=admin_orders_menu_keyboard())
        return ADMIN_MENU

    message = "📦 All Orders:\n"
    for order_tuple in orders_data:
        order_id, _, username, _, _, _, _, total, _, _, status, _, _, _, _, _, _, _ = order_tuple
        message += f"ID: {order_id}, User: @{username}, Total: ₦{total}, Status: {status}\n"
    await safe_edit_message(update, message, reply_markup=admin_orders_menu_keyboard())
    return ADMIN_MENU

async def view_workers_admin(update: Update, context: CallbackContext) -> int:
    """Displays all approved workers."""
    query = update.callback_query
    await query.answer()
    workers_data = get_all_workers(active_only=False)
    if not workers_data:
        await safe_edit_message(update, "No registered workers yet.", reply_markup=admin_workers_menu_keyboard())
        return ADMIN_MENU

    message = "👷‍♂️ Approved Workers:\n"
    for worker_tuple in workers_data:
        worker = {"id": worker_tuple[0], "user_id": worker_tuple[1], "name": worker_tuple[2]}
        message += f"Name: {worker['name']}, User ID: {worker['user_id']}\n"
    await safe_edit_message(update, message, reply_markup=admin_workers_menu_keyboard())
    return ADMIN_MENU

async def view_active_applications_admin(update: Update, context: CallbackContext) -> int:
    """Displays pending worker applications."""
    query = update.callback_query
    await query.answer()
    applications_data = get_worker_applications(status='pending')
    if not applications_data:
        await safe_edit_message(update, "No active applications.", reply_markup=admin_workers_menu_keyboard())
        return ADMIN_MENU

    for app_tuple in applications_data:
        app = {"id": app_tuple[0], "username": app_tuple[2], "name": app_tuple[3], "phone": app_tuple[6]}
        message = f"App ID: {app['id']}, Name: {app['name']}, User: @{app['username']}, Phone: {app['phone']}"
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{app['id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{app['id']}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(message, reply_markup=reply_markup)
    return ADMIN_MENU

async def handle_admin_order_action(update: Update, context: CallbackContext) -> None:
    """Handles admin decisions on active orders."""
    query = update.callback_query
    await query.answer()

    action, order_id_str = query.data.split("_", 2)[1:]
    order_id = int(order_id_str)

    order = get_order_by_id(order_id)
    if not order:
        await safe_edit_message(update, "Order not found.")
        return

    user_id = order[1]
    new_status = 'accepted' if action == 'accept' else 'rejected'

    update_order_status(order_id, new_status)

    if new_status == 'accepted':
        message = "✅ Your order has been accepted and is being prepared."
    else:
        message = "❌ Unfortunately, your order has been rejected."

    try:
        await context.bot.send_message(chat_id=user_id, text=message)
    except Exception as e:
        logger.error(f"Failed to send order status update to user {user_id}: {e}")

    await safe_edit_message(update, f"Order #{order_id} has been {new_status}.")


async def customer_feedback_start(update: Update, context: CallbackContext) -> int:
    """Asks the user for their feedback."""
    await update.message.reply_text("We value your feedback! Please type a short review of your experience with the bot.")
    return CUSTOMER_FEEDBACK

async def customer_feedback_save(update: Update, context: CallbackContext) -> int:
    """Saves the user's feedback to the database."""
    user = update.effective_user
    add_feedback(
        user_id=user.id,
        username=user.username,
        name=user.full_name,
        feedback_text=update.message.text
    )
    await update.message.reply_text("Thank you for your feedback! It has been recorded.")
    return ConversationHandler.END

async def view_all_applications_admin(update: Update, context: CallbackContext) -> int:
    """Displays all worker applications."""
    query = update.callback_query
    await query.answer()
    applications_data = get_worker_applications()
    if not applications_data:
        await safe_edit_message(update, "No applications found.", reply_markup=admin_workers_menu_keyboard())
        return ADMIN_MENU

    message = "📋 All Applications:\n"
    for app_tuple in applications_data:
        app = {"id": app_tuple[0], "username": app_tuple[2], "name": app_tuple[3], "status": app_tuple[7]}
        message += f"ID: {app['id']}, Name: {app['name']}, User: @{app['username']}, Status: {app['status']}\n"
    await safe_edit_message(update, message, reply_markup=admin_workers_menu_keyboard())
    return ADMIN_MENU


async def view_feedback_admin(update: Update, context: CallbackContext) -> int:
    """Displays all customer feedback to the admin."""
    query = update.callback_query
    await query.answer()
    feedback_data = get_all_feedback()
    if not feedback_data:
        await safe_edit_message(update, "No customer feedback yet.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")]]))
        return ADMIN_MENU

    message = "📝 Customer Feedbacks:\n\n"
    for feedback_tuple in feedback_data:
        feedback = {"username": feedback_tuple[2], "name": feedback_tuple[3], "feedback_text": feedback_tuple[4], "timestamp": feedback_tuple[5]}
        message += f"👤 **{feedback['name']}** (@{feedback['username']}) on {feedback['timestamp']}:\n"
        message += f"   - \"{feedback['feedback_text']}\"\n\n"

    await safe_edit_message(update, message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")]]))
    return ADMIN_MENU


async def main() -> None:
    """Start the bot."""
    # Initialize the database
    init_db()

    application = Application.builder().token(TOKEN).build()

    worker_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("work", work_with_us_command)],
        states={
            WORKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_name)],
            WORKER_REG_NO: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_reg_no)],
            WORKER_MATRIC_NO: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_matric_no)],
            WORKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_phone)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    main_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("working", working_history),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(kitchen_menu, pattern="^kitchen_menu$"),
                CallbackQueryHandler(cafe_menu, pattern="^cafe_menu$"),
                CallbackQueryHandler(work_with_us, pattern="^work_with_us$"),
                CallbackQueryHandler(view_orders, pattern="^view_orders$"),
                CallbackQueryHandler(share_command, pattern="^share_bot$"),
            ],
            KITCHEN_MENU: [
                CallbackQueryHandler(indomie_start, pattern="^indomie$"),
                CallbackQueryHandler(custard_start, pattern="^custard$"),
                CallbackQueryHandler(spaghetti_start, pattern="^spaghetti$"),
                CallbackQueryHandler(start, pattern="^main_menu$"),
                CallbackQueryHandler(kitchen_menu, pattern="^back_to_kitchen_menu$"),
            ],
            INDOMIE_SOURCE: [CallbackQueryHandler(indomie_source, pattern="^indomie_source_")],
            INDOMIE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_quantity)],
            INDOMIE_FLAVOR: [CallbackQueryHandler(indomie_flavor, pattern="^flavor_")],
            INDOMIE_SIZE: [CallbackQueryHandler(indomie_size, pattern="^size_")],
            INDOMIE_KITCHEN_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_kitchen_quantity)],
            INDOMIE_MIXINGS: [CallbackQueryHandler(indomie_mixings, pattern="^mixing_")],
            INDOMIE_VEGETABLES_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_vegetable_quantity)],
            INDOMIE_SUYA_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_suya_amount)],
            INDOMIE_TOPPINGS: [CallbackQueryHandler(indomie_toppings, pattern="^topping_")],
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
            CUSTARD_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custard_quantity)],
            CUSTARD_SOURCE: [CallbackQueryHandler(custard_source, pattern="^custard_source_")],
            CUSTARD_ADDITIONS: [
                CallbackQueryHandler(custard_additions, pattern="^custard_add_"),
                CallbackQueryHandler(back_to_custard_quantity, pattern="^back_to_custard_quantity$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            CUSTARD_SUGAR_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custard_sugar_quantity)],
            CUSTARD_MILK_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custard_milk_quantity)],
            ORDER_SUMMARY: [
                CallbackQueryHandler(proceed_to_payment, pattern="^proceed_to_payment$"),
                CallbackQueryHandler(view_bill, pattern="^view_bill$"),
                CallbackQueryHandler(show_order_summary, pattern="^back_to_summary$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            GET_PAYMENT_SCREENSHOT: [
                MessageHandler(filters.PHOTO, handle_payment_screenshot)
            ],
            CAFE_ORDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cafe_order),
                CommandHandler("done", cafe_order_done),
            ],
            WORKER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_name)],
            WORKER_REG_NO: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_reg_no)],
            WORKER_MATRIC_NO: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_matric_no)],
            WORKER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, worker_phone)],
            WORKER_HISTORY: [
                CallbackQueryHandler(view_worker_orders, pattern="^view_(taken|accepted)_orders$"),
            ],
            GET_ROOM_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hall_and_room_number)],
            GET_DELIVERY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_delivery_time)],
            GET_EXTRA_NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_extra_notes),
                CommandHandler("skip", get_extra_notes)
            ],
            ASK_BEVERAGE: [CallbackQueryHandler(handle_beverage_selection, pattern="^bev_")],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    feedback_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("customer_feedback", customer_feedback_start)],
        states={
            CUSTOMER_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, customer_feedback_save)],
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
                CallbackQueryHandler(view_all_orders_admin, pattern="^view_all_orders_admin$"),
                CallbackQueryHandler(view_workers_admin, pattern="^view_workers_admin$"),
                CallbackQueryHandler(view_active_applications_admin, pattern="^view_active_apps$"),
                CallbackQueryHandler(view_all_applications_admin, pattern="^view_all_apps$"),
            ],
        },
        fallbacks=[CommandHandler("admin", admin_start)],
    )
    application.add_handler(admin_conv_handler)
    application.add_handler(worker_conv_handler)
    application.add_handler(feedback_conv_handler)
    application.add_handler(main_conv_handler)
    application.add_handler(CommandHandler("share", share_command))
    application.add_handler(CallbackQueryHandler(handle_admin_order_action, pattern="^admin_(accept|reject)_"))
    application.add_handler(CallbackQueryHandler(handle_worker_approval, pattern="^(approve|reject)_"))
    application.add_handler(CallbackQueryHandler(take_order, pattern="^take_"))
    application.add_handler(CallbackQueryHandler(copy_share_message_callback, pattern="^copy_share_message$"))
    application.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))

    # Global error handler
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log Errors caused by Updates."""
        logger.warning('Update "%s" caused error "%s"', update, context.error)

    application.add_error_handler(error_handler)

    # Scheduler for daily messages
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_messages, 'interval', hours=6, args=[application.bot])

    async with application:
        webhook_url = os.getenv("WEBHOOK_URL")
        await application.bot.set_webhook(webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
        scheduler.start()
        await application.start()

        # Webhook server
        async def telegram_handle(request):
            logger.info("Received a POST request from Telegram.")
            await application.update_queue.put(Update.de_json(await request.json(), application.bot))
            return web.Response()

        async def health_check(_):
            return web.Response(text="OK")

        app = web.Application()
        app.router.add_post("/", telegram_handle)
        app.router.add_get("/", health_check)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8080)))
        await site.start()

        # Keep the server running
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
