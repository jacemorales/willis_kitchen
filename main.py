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
    get_all_payments, add_feedback, get_all_feedback
)
from messages import DAILY_MESSAGES, SHARE_MESSAGE

async def safe_edit_message_text(update: Update, text: str, reply_markup=None):
    """Safely edits a message, avoiding re-sending the same content."""
    try:
        if update.callback_query.message.text != text or update.callback_query.message.reply_markup != reply_markup:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error editing message: {e}")

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
    INDOMIE_EGG_QUANTITY,
    INDOMIE_SAUSAGE_QUANTITY,
    INDOMIE_CHICKEN_QUANTITY,
    INDOMIE_FRIED_FISH_QUANTITY,
    INDOMIE_MALT_QUANTITY,
    INDOMIE_COKE_QUANTITY,
    INDOMIE_JUICE_QUANTITY,
    INDOMIE_WATER_QUANTITY,
) = range(36)


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
        await safe_edit_message_text(update, welcome_text, reply_markup=reply_markup)
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
    await safe_edit_message_text(
        update, "Please choose a food option from our kitchen:", reply_markup=reply_markup
    )
    return KITCHEN_MENU


async def cafe_menu(update: Update, context: CallbackContext) -> int:
    """Asks for the cafe order."""
    query = update.callback_query
    await query.answer()
    context.user_data['cafe_items'] = []
    await safe_edit_message_text(
        update,
        "Please send each item you want to order in the format: `Item, Quantity, Total Price`.\n\n"
        "Example: `Meat Pie, 2, 1600`\n\n"
        "Send `/done` when you have added all your items."
    )
    return CAFE_ORDER


async def cafe_order(update: Update, context: CallbackContext) -> int:
    """Parses a single cafe item and adds it to the list."""
    order_text = update.message.text
    try:
        parts = order_text.split(",")
        item_name = parts[0].strip()
        quantity = int(parts[1].strip())
        price = int("".join(filter(str.isdigit, parts[2])))
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid format. Please use 'Item, Quantity, Amount'.")
        return CAFE_ORDER

    context.user_data['cafe_items'].append({'item': item_name, 'quantity': quantity, 'price': price})

    await update.message.reply_text(f"Added: {item_name}. Add another item or send /done.")
    return CAFE_ORDER


async def cafe_order_done(update: Update, context: CallbackContext) -> int:
    """Finalizes the multi-item cafe order."""
    items = context.user_data.get('cafe_items', [])
    if not items:
        await update.message.reply_text("You haven't added any items yet.")
        return CAFE_ORDER

    total_price = sum(item['price'] for item in items)
    service_charge = ((total_price - 1) // 500 + 1) * 100
    total = total_price + service_charge

    context.user_data["order"] = {
        "food": "Cafe Order",
        "quantities": items,
        "service_charge": service_charge,
        "total": total,
        "source": "cafe",
    }

    await update.message.reply_text("Please enter your hall and room number (e.g., Peter Hall B204):")
    return GET_ROOM_NUMBER


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

    await safe_edit_message_text(update, summary, reply_markup=reply_markup)
    return ConversationHandler.END


async def notify_workers(context: CallbackContext, order_id: int):
    """Notifies all active workers of a new order."""
    workers = get_all_workers()
    order = get_order_by_id(order_id)
    if not order:
        return

    _, _, username, food_type, _, _, _, total, _, source, _, _, _, _, _ = order

    message = (
        f"📦 New Order Available:\n"
        f"From: @{username}\n"
        f"Order: {food_type}\n"
        f"Total Price: ₦{total}"
    )

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
    await safe_edit_message_text(update, "Please enter your full name:")
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
        await safe_edit_message_text(update, "Application not found.")
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
        await safe_edit_message_text(update, f"Application {application_id} approved.")
    else: # Reject
        update_worker_application_status(application_id, 'rejected')
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Your application was not approved at this time."
        )
        await safe_edit_message_text(update, f"Application {application_id} rejected.")


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
        await safe_edit_message_text(update, SHARE_MESSAGE, reply_markup=reply_markup)
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
        await safe_edit_message_text(update, prompt)
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
    """Stores the delivery time and shows the order summary."""
    context.user_data["order"]["delivery_time"] = update.message.text
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
        await safe_edit_message_text(update, f"You have no {status} orders.")
        return WORKER_HISTORY

    message = f"📦 Your {status.capitalize()} Orders:\n"
    for order in orders:
        _, _, _, food_type, _, _, _, total, order_date, _, _, _, _, _, _ = order
        message += f"📅 {order_date} - {food_type} - ₦{total}\n"

    await safe_edit_message_text(update, message)
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
        await safe_edit_message_text(update, "✅ You have successfully taken this order.")

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
        await safe_edit_message_text(update, "This order has already been taken.")


async def indomie_start(update: Update, context: CallbackContext) -> int:
    """Asks for the flavor of Indomie."""
    query = update.callback_query
    await query.answer()
    context.user_data["order"] = {
        "food": "Indomie",
        "mixings": [],
        "toppings": [],
        "quantities": {},
        "spices": [],
        "beverages": [],
    }
    keyboard = [
        [InlineKeyboardButton("Chicken Flavour", callback_data="flavor_chicken")],
        [InlineKeyboardButton("Onion and Chicken", callback_data="flavor_onion_chicken")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message_text(update, "Please choose a flavor:", reply_markup=reply_markup)
    return INDOMIE_FLAVOR

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
    await safe_edit_message_text(update, "Please choose a size:", reply_markup=reply_markup)
    return INDOMIE_SIZE

async def indomie_size(update: Update, context: CallbackContext) -> int:
    """Stores the size and price, then asks for mixings."""
    query = update.callback_query
    await query.answer()
    size, price = query.data.split("_")[1:]
    context.user_data["order"]["size"] = size
    context.user_data["order"]["quantities"]["Indomie"] = 1  # Default to 1
    context.user_data["order"]["total"] = int(price)

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
        [InlineKeyboardButton("None", callback_data="mixing_none")],
        [InlineKeyboardButton("Done ✅", callback_data="mixing_done")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = "Please select your mixings:"
    if update.callback_query:
        await safe_edit_message_text(update, message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)

    return INDOMIE_MIXINGS

async def indomie_mixings(update: Update, context: CallbackContext) -> int:
    """Handles mixing selections."""
    query = update.callback_query
    await query.answer()
    selection = query.data.split("_", 1)[1]

    if "mixings" not in context.user_data["order"]:
        context.user_data["order"]["mixings"] = []

    if selection == "done":
        return await ask_for_mixing_quantities(update, context)

    if selection == "none":
        context.user_data["order"]["mixings"] = []
        return await ask_for_mixing_quantities(update, context)

    # For spices, just add them, no quantity needed
    if "spice" in selection:
        spice_name = selection.replace("_", " ")
        if spice_name not in context.user_data["order"]["mixings"]:
            context.user_data["order"]["mixings"].append(spice_name)
        else:
            context.user_data["order"]["mixings"].remove(spice_name)
    else: # For other items
        if selection not in context.user_data["order"]["mixings"]:
            context.user_data["order"]["mixings"].append(selection)
        else:
            context.user_data["order"]["mixings"].remove(selection)

    selected_mixings = ", ".join(context.user_data["order"]["mixings"])
    await safe_edit_message_text(
        update,
        f"Selected mixings: {selected_mixings}\n\nPlease select your mixings:",
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
        [InlineKeyboardButton("None", callback_data="mixing_none")],
        [InlineKeyboardButton("Done ✅", callback_data="mixing_done")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def ask_for_mixing_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of each selected mixing, one by one."""
    mixings = context.user_data["order"].get("mixings", [])

    if "quantities" not in context.user_data["order"]:
        context.user_data["order"]["quantities"] = {}

    if "vegetables" in mixings and "vegetables" not in context.user_data["order"]["quantities"]:
        await update.callback_query.edit_message_text("How many vegetables would you like?")
        return INDOMIE_VEGETABLES_QUANTITY
    if "suya" in mixings and "suya" not in context.user_data["order"]["quantities"]:
        await update.callback_query.edit_message_text("Enter the amount for suya (₦):")
        return INDOMIE_SUYA_AMOUNT

    return await indomie_toppings_menu(update, context)


async def indomie_toppings_menu(update: Update, context: CallbackContext) -> int:
    """Displays the toppings menu."""
    keyboard = [
        [
            InlineKeyboardButton("Egg (₦400)", callback_data="topping_egg"),
            InlineKeyboardButton("Sausage (₦400)", callback_data="topping_sausage"),
        ],
        [
            InlineKeyboardButton("Chicken (₦1200-₦3400)", callback_data="topping_chicken"),
            InlineKeyboardButton("Fried Fish (₦1500)", callback_data="topping_fried_fish"),
        ],
        [InlineKeyboardButton("None", callback_data="topping_none")],
        [InlineKeyboardButton("Done ✅", callback_data="topping_done")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message_text(update, "Please select your toppings:", reply_markup=reply_markup)
    return INDOMIE_TOPPINGS

async def indomie_toppings(update: Update, context: CallbackContext) -> int:
    """Handles topping selections."""
    query = update.callback_query
    await query.answer()
    selection = query.data.split("_", 1)[1]

    if "toppings" not in context.user_data["order"]:
        context.user_data["order"]["toppings"] = []

    if selection == "done":
        return await ask_for_topping_quantities(update, context)

    if selection == "none":
        context.user_data["order"]["toppings"] = []
        return await ask_for_topping_quantities(update, context)

    if selection not in context.user_data["order"]["toppings"]:
        context.user_data["order"]["toppings"].append(selection)
    else:
        context.user_data["order"]["toppings"].remove(selection)

    selected_toppings = ", ".join(context.user_data["order"]["toppings"])
    await safe_edit_message_text(
        update,
        f"Selected toppings: {selected_toppings}\n\nPlease select your toppings:",
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
            InlineKeyboardButton("Chicken (₦1200-₦3400)", callback_data="topping_chicken"),
            InlineKeyboardButton("Fried Fish (₦1500)", callback_data="topping_fried_fish"),
        ],
        [InlineKeyboardButton("None", callback_data="topping_none")],
        [InlineKeyboardButton("Done ✅", callback_data="topping_done")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def ask_for_topping_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of each selected topping, one by one."""
    toppings = context.user_data["order"].get("toppings", [])

    if "egg" in toppings and "egg" not in context.user_data["order"]["quantities"]:
        await update.callback_query.edit_message_text("How many eggs would you like?")
        return INDOMIE_EGG_QUANTITY
    if "sausage" in toppings and "sausage" not in context.user_data["order"]["quantities"]:
        await update.callback_query.edit_message_text("How many sausages would you like?")
        return INDOMIE_SAUSAGE_QUANTITY
    if "chicken" in toppings and "chicken" not in context.user_data["order"]["quantities"]:
        await update.callback_query.edit_message_text("How many pieces of chicken would you like?")
        return INDOMIE_CHICKEN_QUANTITY
    if "fried fish" in toppings and "fried fish" not in context.user_data["order"]["quantities"]:
        await update.callback_query.edit_message_text("How many pieces of fried fish would you like?")
        return INDOMIE_FRIED_FISH_QUANTITY

    return await ask_for_beverages(update, context)


def beverage_keyboard():
    """Returns the keyboard for the beverage menu."""
    keyboard = [
        [
            InlineKeyboardButton("Water (₦300)", callback_data="bev_water"),
            InlineKeyboardButton("Soft Drink (₦600)", callback_data="bev_soft_drink"),
        ],
        [
            InlineKeyboardButton("Malt (₦800)", callback_data="bev_malt"),
            InlineKeyboardButton("1L Drink (₦2500)", callback_data="bev_1l_drink"),
        ],
        [InlineKeyboardButton("None", callback_data="bev_none")],
        [InlineKeyboardButton("Done ✅", callback_data="bev_done")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def ask_for_beverages(update: Update, context: CallbackContext) -> int:
    """Asks the user to select beverages."""
    await safe_edit_message_text(
        update, "Would you like to add any beverages?", reply_markup=beverage_keyboard()
    )
    return INDOMIE_BEVERAGES

async def handle_beverages(update: Update, context: CallbackContext) -> int:
    """Handles beverage selections."""
    query = update.callback_query
    await query.answer()
    selection = query.data.split("_", 1)[1]

    if "beverages" not in context.user_data["order"]:
        context.user_data["order"]["beverages"] = []

    if selection == "done":
        return await ask_for_beverage_quantities(update, context)

    if selection == "none":
        context.user_data["order"]["beverages"] = []
        return await ask_for_beverage_quantities(update, context)

    if selection not in context.user_data["order"]["beverages"]:
        context.user_data["order"]["beverages"].append(selection)
    else:
        context.user_data["order"]["beverages"].remove(selection)

    selected_beverages = ", ".join(context.user_data["order"]["beverages"])
    await safe_edit_message_text(
        update,
        f"Selected beverages: {selected_beverages}\n\nWould you like to add any beverages?",
        reply_markup=beverage_keyboard(),
    )
    return INDOMIE_BEVERAGES

async def ask_for_beverage_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of each selected beverage, one by one."""
    beverages = context.user_data["order"].get("beverages", [])

    if "water" in beverages and "water" not in context.user_data["order"]["quantities"]:
        await update.callback_query.edit_message_text("How many bottles of water would you like?")
        return INDOMIE_WATER_QUANTITY
    if "soft drink" in beverages and "soft drink" not in context.user_data["order"]["quantities"]:
        await update.callback_query.edit_message_text("How many soft drinks would you like?")
        return INDOMIE_COKE_QUANTITY # Reusing coke state
    if "malt" in beverages and "malt" not in context.user_data["order"]["quantities"]:
        await update.callback_query.edit_message_text("How many malts would you like?")
        return INDOMIE_MALT_QUANTITY
    if "1l drink" in beverages and "1l drink" not in context.user_data["order"]["quantities"]:
        await update.callback_query.edit_message_text("How many 1L drinks would you like?")
        return INDOMIE_JUICE_QUANTITY # Reusing juice state

    # Done with all beverage quantities
    return await ask_for_delivery_time(update, context)

async def get_beverage_quantity(update: Update, context: CallbackContext, beverage_name: str, next_state_func) -> int:
    """Generic function to handle beverage quantity."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            await update.message.reply_text("Please enter a valid number greater than 0.")
            # This needs to map back to the correct state enum
            state_map = {"water": INDOMIE_WATER_QUANTITY, "soft drink": INDOMIE_COKE_QUANTITY, "malt": INDOMIE_MALT_QUANTITY, "1l drink": INDOMIE_JUICE_QUANTITY}
            return state_map[beverage_name]

        context.user_data["order"]["quantities"][beverage_name] = quantity

        class MockQuery:
            def __init__(self, message):
                self.message = message
            async def edit_message_text(self, *args, **kwargs):
                return await self.message.reply_text(*args, **kwargs)

        return await next_state_func(MockQuery(update.message), context)

    except (ValueError, TypeError):
        await update.message.reply_text("Invalid input. Please enter a number.")
        state_map = {"water": INDOMIE_WATER_QUANTITY, "soft drink": INDOMIE_COKE_QUANTITY, "malt": INDOMIE_MALT_QUANTITY, "1l drink": INDOMIE_JUICE_QUANTITY}
        return state_map[beverage_name]

async def get_water_quantity(update: Update, context: CallbackContext) -> int:
    return await get_beverage_quantity(update, context, "water", ask_for_beverage_quantities)

async def get_coke_quantity(update: Update, context: CallbackContext) -> int: # Actually soft drink
    return await get_beverage_quantity(update, context, "soft drink", ask_for_beverage_quantities)

async def get_malt_quantity(update: Update, context: CallbackContext) -> int:
    return await get_beverage_quantity(update, context, "malt", ask_for_beverage_quantities)

async def get_juice_quantity(update: Update, context: CallbackContext) -> int: # Actually 1L drink
    return await get_beverage_quantity(update, context, "1l drink", ask_for_beverage_quantities)

async def get_topping_quantity(update: Update, context: CallbackContext, topping_name: str, next_state_func) -> int:
    """Generic function to handle topping quantity."""
    try:
        quantity = int(update.message.text)
        if quantity <= 0:
            await update.message.reply_text("Please enter a valid number greater than 0.")
            return getattr(ConversationHandler, f"INDOMIE_{topping_name.upper()}_QUANTITY")

        context.user_data["order"]["quantities"][topping_name] = quantity

        # After getting quantity, we re-call ask_for_topping_quantities to see if there's another topping
        query = update.callback_query
        # A bit of a hack: we need a query object to call the next function, but we are in a message handler
        # We can simulate one by creating a dummy object with the necessary attributes.
        class MockQuery:
            def __init__(self, message):
                self.message = message
            async def edit_message_text(self, *args, **kwargs):
                return await self.message.reply_text(*args, **kwargs)

        return await next_state_func(MockQuery(update.message), context)

    except (ValueError, TypeError):
        await update.message.reply_text("Invalid input. Please enter a number.")
        return getattr(ConversationHandler, f"INDOMIE_{topping_name.upper()}_QUANTITY")

async def get_egg_quantity(update: Update, context: CallbackContext) -> int:
    return await get_topping_quantity(update, context, "egg", ask_for_topping_quantities)

async def get_sausage_quantity(update: Update, context: CallbackContext) -> int:
    return await get_topping_quantity(update, context, "sausage", ask_for_topping_quantities)

async def get_chicken_quantity(update: Update, context: CallbackContext) -> int:
    return await get_topping_quantity(update, context, "chicken", ask_for_topping_quantities)

async def get_fried_fish_quantity(update: Update, context: CallbackContext) -> int:
    return await get_topping_quantity(update, context, "fried fish", ask_for_topping_quantities)

async def ask_for_delivery_time(update: Update, context: CallbackContext) -> int:
    """Asks for the delivery time."""
    await safe_edit_message_text(update, "When would you like your order delivered?")
    return GET_DELIVERY_TIME

async def handle_delivery_time(update: Update, context: CallbackContext) -> int:
    """Stores the delivery time and asks for extra notes."""
    context.user_data["order"]["delivery_time"] = update.message.text
    await update.message.reply_text("Would you like to add any extra notes for the chef or delivery person? (Type 'no' if none)")
    return INDOMIE_NOTES

async def handle_extra_notes(update: Update, context: CallbackContext) -> int:
    """Stores the extra notes and shows the order summary."""
    notes = update.message.text
    context.user_data["order"]["notes"] = notes if notes.lower() != 'no' else None
    return await show_order_summary(update, context)


async def ask_for_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for quantities of selected items."""
    order = context.user_data["order"]

    # Mixings
    if "vegetables" in order["mixings"] and "Vegetables" not in order["quantities"]:
        if update.callback_query:
            await safe_edit_message_text(update, "How many vegetables would you like?")
        else:
            await update.message.reply_text("How many vegetables would you like?")
        return INDOMIE_VEGETABLES_QUANTITY

    if "sardine" in order["mixings"] and "Sardine" not in order["quantities"]:
        if update.callback_query:
            await safe_edit_message_text(update, "How many sardines would you like?")
        else:
            await update.message.reply_text("How many sardines would you like?")
        return INDOMIE_SARDINE_QUANTITY

    if "suya" in order["mixings"] and "Suya" not in order["quantities"]:
        if update.callback_query:
            await safe_edit_message_text(update, "Enter the amount for suya (₦):")
        else:
            await update.message.reply_text("Enter the amount for suya (₦):")
        return INDOMIE_SUYA_AMOUNT

    return await ask_for_topping_quantities(update, context)


async def indomie_vegetables_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of vegetables."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Vegetables"] = quantity
    return await ask_for_quantities(update, context)


async def indomie_egg_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of eggs."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Egg"] = quantity
    return await ask_for_topping_quantities(update, context)


async def indomie_sausage_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of sausages."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Sausage"] = quantity
    return await ask_for_topping_quantities(update, context)


async def ask_for_topping_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for quantities of selected toppings."""
    order = context.user_data["order"]

    if "egg" in order["toppings"] and "Egg" not in order["quantities"]:
        if update.callback_query:
            await safe_edit_message_text(update, "How many eggs would you like?")
        else:
            await update.message.reply_text("How many eggs would you like?")
        return INDOMIE_EGG_QUANTITY

    if "sausage" in order["toppings"] and "Sausage" not in order["quantities"]:
        if update.callback_query:
            await safe_edit_message_text(update, "How many sausages would you like?")
        else:
            await update.message.reply_text("How many sausages would you like?")
        return INDOMIE_SAUSAGE_QUANTITY

    if update.callback_query:
        return await ask_for_hall_and_room_number(update, context)
    else:
        await update.message.reply_text("Please enter your hall and room number (e.g., Peter Hall B204):")
        return GET_ROOM_NUMBER


async def indomie_suya_amount(update: Update, context: CallbackContext) -> int:
    """Stores the amount for suya and proceeds to ask for topping quantities."""
    amount = int(update.message.text)
    context.user_data["order"]["quantities"]["Suya"] = amount
    return await ask_for_quantities(update, context)


async def custard_start(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of Custard."""
    query = update.callback_query
    await query.answer()
    context.user_data["order"] = {
        "food": "Custard",
        "additions": [],
        "quantities": {},
    }
    await safe_edit_message_text(update, "How many custard cups would you like to make?")
    return CUSTARD_QUANTITY


async def custard_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of custard and asks for additions."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Custard"] = quantity
    keyboard = [
        [
            InlineKeyboardButton("Sugar", callback_data="sugar"),
            InlineKeyboardButton("Milk", callback_data="milk"),
            InlineKeyboardButton("None", callback_data="none_additions"),
        ],
        [
            InlineKeyboardButton("Back ⬅️", callback_data="back_to_custard_quantity"),
            InlineKeyboardButton("Done ✅", callback_data="next_custard_quantities"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    keyboard = [
        [
            InlineKeyboardButton("I have my own Custard", callback_data="own_custard"),
            InlineKeyboardButton("Use the kitchen's Custard", callback_data="kitchen_custard"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Will you be providing the Custard, or should we use ours?",
        reply_markup=reply_markup,
    )
    return CUSTARD_SOURCE


async def custard_additions(update: Update, context: CallbackContext) -> int:
    """Stores the additions."""
    query = update.callback_query
    await query.answer()
    addition = query.data
    if addition == "next_custard_quantities":
        return await ask_for_custard_quantities(update, context)

    if addition == "none_additions":
        context.user_data["order"]["additions"] = []
        return await ask_for_custard_quantities(update, context)

    if addition not in context.user_data["order"]["additions"]:
        context.user_data["order"]["additions"].append(addition)
    else:
        context.user_data["order"]["additions"].remove(addition)

    # Show updated selection
    selected_additions = ", ".join(context.user_data["order"]["additions"])
    await safe_edit_message_text(
        update,
        f"Selected additions: {selected_additions}\n\n"
        "What would you like to add to your custard?",
        reply_markup=custard_additions_keyboard(),
    )
    return CUSTARD_ADDITIONS


async def custard_source(update: Update, context: CallbackContext) -> int:
    """Stores the source of the Custard and asks for additions."""
    query = update.callback_query
    await query.answer()
    source = query.data
    context.user_data["order"]["source_custard"] = source

    keyboard = custard_additions_keyboard()
    await safe_edit_message_text(
        update,
        "What would you like to add to your custard?",
        reply_markup=keyboard,
    )
    return CUSTARD_ADDITIONS


def custard_additions_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("Sugar", callback_data="sugar"),
            InlineKeyboardButton("Milk", callback_data="milk"),
            InlineKeyboardButton("None", callback_data="none_additions"),
        ],
        [
            InlineKeyboardButton("Back ⬅️", callback_data="back_to_custard_quantity"),
            InlineKeyboardButton("Done ✅", callback_data="next_custard_quantities"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def ask_for_custard_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for quantities of selected items."""
    order = context.user_data["order"]

    if "sugar" in order["additions"] and "Sugar" not in order["quantities"]:
        if update.callback_query:
            await safe_edit_message_text(update, "How many spoons of sugar would you like?")
        else:
            await update.message.reply_text("How many spoons of sugar would you like?")
        return CUSTARD_SUGAR_QUANTITY

    if "milk" in order["additions"] and "Milk" not in order["quantities"]:
        if update.callback_query:
            await safe_edit_message_text(update, "How many sachets of milk would you like?")
        else:
            await update.message.reply_text("How many sachets of milk would you like?")
        return CUSTARD_MILK_QUANTITY

    if update.callback_query:
        return await ask_for_hall_and_room_number(update, context)
    else:
        await update.message.reply_text("Please enter your hall and room number (e.g., Peter Hall B204):")
        return GET_ROOM_NUMBER


async def custard_sugar_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of sugar."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Sugar"] = quantity
    return await ask_for_custard_quantities(update, context)


async def custard_milk_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of milk."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Milk"] = quantity
    return await ask_for_custard_quantities(update, context)


async def spaghetti_start(update: Update, context: CallbackContext) -> int:
    """Handles the Spaghetti option."""
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_kitchen_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await safe_edit_message_text(
        update, "Please contact customer care for more info 📞", reply_markup=reply_markup
    )
    return KITCHEN_MENU


async def cancel(update: Update, context: CallbackContext) -> int:
    """Cancels the conversation and returns to the main menu."""
    query = update.callback_query
    await query.answer()
    return await start(update, context)


async def show_order_summary(update: Update, context: CallbackContext) -> int:
    """Calculates the total price and shows the order summary."""
    order = context.user_data["order"]
    total = 0
    summary = f"{update.effective_user.first_name} (@{update.effective_user.username})\n"
    summary += "Here is your order:\n"

    pricing = {
        "Indomie": 300,
        "Egg": 400,
        "Sausage": 400,
        "Vegetables": 800,
        "Suya": 1,  # Price per Naira
        "Custard": 300,
        "Sugar": 50,
        "Milk": 400,
        "pepper spice": 200,
        "crayfish spice": 200,
        "chicken": 1200, # Base price, can be updated
        "fried fish": 1500,
        "water": 300,
        "soft drink": 600,
        "malt": 800,
        "1l drink": 2500,
    }

    if order.get("source") == "cafe":
        items = order["quantities"]
        for item in items:
            summary += f"{item['item']} ({item['quantity']}) - ₦{item['price']}\n"
        summary += f"Service Charge - ₦{order['service_charge']}\n"
        total = order['total']
    else:
        for item, quantity in order["quantities"].items():
            if item in ["Indomie", "Custard"]:
                summary += f"{item} x{quantity}\n"
            elif item != "item" and item != "price":
                summary += f"{item} ({quantity})\n"

        # Calculate total without showing individual prices
        total = order.get("total", 0)
        for item, quantity in order.get("quantities", {}).items():
            if item not in ["Indomie", "Custard"]:
                total += pricing.get(item, 0) * quantity

        for mixin in order.get("mixings", []):
            if "spice" in mixin:
                total += pricing.get(mixin, 0)

        for topping in order.get("toppings", []):
            total += pricing.get(topping, 0)

        for beverage in order.get("beverages", []):
            total += pricing.get(beverage, 0)


    order["service_charge"] = 250
    total += order["service_charge"]
    order["total"] = total

    summary += "----------------------\n"
    summary += f"Service Charge: ₦250\n"
    summary += f"Total: ₦{total}\n\n"
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

    if update.callback_query:
        await safe_edit_message_text(update, summary, reply_markup=reply_markup)
    else:
        await update.message.reply_text(summary, reply_markup=reply_markup)

    return ORDER_SUMMARY


async def proceed_to_payment(update: Update, context: CallbackContext) -> int:
    """Saves the order with a 'pending_payment' status and asks for a screenshot."""
    query = update.callback_query
    await query.answer()
    order = context.user_data["order"]
    order_id = add_order(
        user_id=update.effective_user.id,
        username=update.effective_user.username,
        food_type=order["food"],
        mixings=order.get("mixings"),
        toppings=order.get("toppings"),
        quantities=order["quantities"],
        total=order["total"],
        hall_and_room_number=order.get("hall_and_room_number"),
        delivery_time=order.get("delivery_time"),
        status='pending_payment'  # New status
    )
    context.user_data["order_id"] = order_id

    await safe_edit_message_text(
        update, "Your order has been saved. Please upload a screenshot of your payment to complete the order."
    )
    return GET_PAYMENT_SCREENSHOT


async def handle_payment_screenshot(update: Update, context: CallbackContext) -> int:
    """Handles the payment screenshot, finalizes the order, and notifies workers."""
    order_id = context.user_data.get("order_id")
    if not order_id:
        await update.message.reply_text("Something went wrong. Please try placing your order again.")
        return ConversationHandler.END

    screenshot_file_id = update.message.photo[-1].file_id
    add_payment(order_id, screenshot_file_id)
    update_order_status(order_id, 'pending')

    # Notify workers
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
        mixings=order.get("mixings"),
        toppings=order.get("toppings"),
        quantities=order["quantities"],
        total=order["total"],
        hall_and_room_number=order.get("hall_and_room_number"),
        delivery_time=order.get("delivery_time"),
    )

    # Notify workers
    await notify_workers(context, order_id)

    summary = "✅ Your order has been successfully placed!\n\n"
    summary += "Here’s your order summary:\n"
    for item, quantity in order["quantities"].items():
        summary += f"• {item} x{quantity}\n"
    summary += f"Total: ₦{order['total']}\n\n"
    summary += f"Delivery to: {order['hall_and_room_number']}\n"
    summary += f"Delivery time: {order['delivery_time']}\n\n"
    summary += "Thank you for ordering from Willis Kitchen!"

    keyboard = [[InlineKeyboardButton("⬅️ Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await safe_edit_message_text(update, summary, reply_markup=reply_markup)
    return ConversationHandler.END


async def view_bill(update: Update, context: CallbackContext) -> int:
    """Shows the billing breakdown."""
    query = update.callback_query
    await query.answer()
    order = context.user_data["order"]
    bill = "📋 Billing Breakdown:\n"
    total = 0

    pricing = {
        "Indomie": 300,
        "Egg": 400,
        "Sausage": 400,
        "Vegetables": 800,
        "Suya": 1,
        "Custard": 300,
        "Sugar": 50,
        "Milk": 400,
        "pepper spice": 200,
        "crayfish spice": 200,
        "chicken": 1200,
        "fried fish": 1500,
        "water": 300,
        "soft drink": 600,
        "malt": 800,
        "1l drink": 2500,
    }

    if order.get("source") == "cafe":
        items = order["quantities"]
        for item in items:
            bill += f"{item['item']} ({item['quantity']}) - ₦{item['price']}\n"
        bill += f"Service Charge - ₦{order['service_charge']}\n"
        total = order['total']
    else:
        # Calculate total for kitchen orders
        total = order.get("total", 0)
        bill += f"{order['food']} ({order['size']}): ₦{total}\n"

        for item, quantity in order.get("quantities", {}).items():
            if item not in ["Indomie", "Custard"]:
                price = pricing.get(item, 0) * quantity
                bill += f"{item.capitalize()} x{quantity}: ₦{price}\n"
                total += price

        for mixin in order.get("mixings", []):
            if "spice" in mixin:
                price = pricing.get(mixin, 0)
                bill += f"{mixin.capitalize()}: ₦{price}\n"
                total += price

        for topping in order.get("toppings", []):
            price = pricing.get(topping, 0)
            bill += f"{topping.capitalize()}: ₦{price}\n"
            total += price

        for beverage in order.get("beverages", []):
            price = pricing.get(beverage, 0)
            bill += f"{beverage.capitalize()}: ₦{price}\n"
            total += price


    bill += "----------------------\n"
    bill += f"Service Charge: ₦250\n"
    total += 250
    bill += f"💰 Total = ₦{total}"

    keyboard = [
        [
            InlineKeyboardButton("✅ Place Order", callback_data="confirm_order"),
            InlineKeyboardButton("⬅️ Back", callback_data="back_to_summary"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await safe_edit_message_text(update, bill, reply_markup=reply_markup)
    return ORDER_SUMMARY


async def view_orders(update: Update, context: CallbackContext) -> int:
    """Displays the user's past orders."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    orders = get_user_orders(user_id)

    if not orders:
        await safe_edit_message_text(update, "You have no orders yet. Start by placing one 🍽️")
        return MAIN_MENU

    message = "📦 Your Orders:\n"
    total_spent = 0
    for i, order in enumerate(orders):
        _, _, _, food_type, _, _, quantities, total, order_date, _, _, _, _, _, _ = order
        quantities = json.loads(quantities)

        if food_type in ['Indomie', 'Custard']:
            details = []
            if food_type in quantities:
                details.append(f"{food_type} ({quantities[food_type]})")

            for item, quantity in quantities.items():
                if item == food_type:
                    continue
                if item == "Suya":
                    details.append(f"Suya ₦{quantity}")
                # All other items get braces
                elif item not in ['item', 'quantity', 'price']:
                    details.append(f"{item} ({quantity})")

            details_str = ", ".join(details)
            message += f"{i+1}️⃣ {details_str} - ₦{total} on {order_date}\n"
        else: # Cafe order
            message += f"{i+1}️⃣ {food_type} - ₦{total} on {order_date}\n"
        total_spent += total

    message += "-------------------\n"
    message += f"Total Spent: ₦{total_spent}"

    await safe_edit_message_text(update, message)
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
    await safe_edit_message_text(update, "📦 Order Management", reply_markup=admin_orders_menu_keyboard())
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
    await safe_edit_message_text(update, "👷‍♂️ Worker Management", reply_markup=admin_workers_menu_keyboard())
    return ADMIN_MENU

async def admin_payments_menu(update: Update, context: CallbackContext) -> int:
    """Displays the payment management menu for admins."""
    query = update.callback_query
    await query.answer()
    payments = get_all_payments()
    if not payments:
        await safe_edit_message_text(update, "No payments found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")]]))
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
    orders = get_orders_by_status('pending')
    if not orders:
        await safe_edit_message_text(update, "No active orders yet.", reply_markup=admin_orders_menu_keyboard())
        return ADMIN_MENU

    await safe_edit_message_text(update, "📦 Active Orders:")
    for order in orders:
        order_id, _, username, food_type, _, _, _, total, _, _, _, _, _, _, _ = order
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
    orders = get_orders_by_status('taken')
    if not orders:
        await safe_edit_message_text(update, "No taken orders yet.", reply_markup=admin_orders_menu_keyboard())
        return ADMIN_MENU

    message = "📦 Taken Orders:\n"
    for order in orders:
        order_id, _, username, food_type, _, _, _, total, _, _, _, worker_id, _, _, _ = order
        message += f"ID: {order_id}, User: @{username}, Worker: {worker_id}, Total: ₦{total}\n"
    await safe_edit_message_text(update, message, reply_markup=admin_orders_menu_keyboard())
    return ADMIN_MENU

async def view_all_orders_admin(update: Update, context: CallbackContext) -> int:
    """Displays all orders to the admin."""
    query = update.callback_query
    await query.answer()
    orders = get_all_orders()
    if not orders:
        await safe_edit_message_text(update, "No completed orders yet.", reply_markup=admin_orders_menu_keyboard())
        return ADMIN_MENU

    message = "📦 All Orders:\n"
    for order in orders:
        order_id, _, username, _, _, _, _, total, _, _, status, _, _, _, _ = order
        message += f"ID: {order_id}, User: @{username}, Total: ₦{total}, Status: {status}\n"
    await safe_edit_message_text(update, message, reply_markup=admin_orders_menu_keyboard())
    return ADMIN_MENU

async def view_workers_admin(update: Update, context: CallbackContext) -> int:
    """Displays all approved workers."""
    query = update.callback_query
    await query.answer()
    workers = get_all_workers(active_only=False) # A new function to get all workers
    if not workers:
        await safe_edit_message_text(update, "No registered workers yet.", reply_markup=admin_workers_menu_keyboard())
        return ADMIN_MENU

    message = "👷‍♂️ Approved Workers:\n"
    for worker in workers:
        message += f"Name: {worker[2]}, User ID: {worker[1]}\n"
    await safe_edit_message_text(update, message, reply_markup=admin_workers_menu_keyboard())
    return ADMIN_MENU

async def view_active_applications_admin(update: Update, context: CallbackContext) -> int:
    """Displays pending worker applications."""
    query = update.callback_query
    await query.answer()
    applications = get_worker_applications(status='pending')
    if not applications:
        await safe_edit_message_text(update, "No active applications.", reply_markup=admin_workers_menu_keyboard())
        return ADMIN_MENU

    for app in applications:
        app_id, _, username, name, _, _, phone, _, _ = app
        message = f"App ID: {app_id}, Name: {name}, User: @{username}, Phone: {phone}"
        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{app_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{app_id}"),
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
        await safe_edit_message_text(update, "Order not found.")
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

    await safe_edit_message_text(update, f"Order #{order_id} has been {new_status}.")


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
    applications = get_worker_applications()
    if not applications:
        await safe_edit_message_text(update, "No applications found.", reply_markup=admin_workers_menu_keyboard())
        return ADMIN_MENU

    message = "📋 All Applications:\n"
    for app in applications:
        app_id, _, username, name, _, _, _, status, _ = app
        message += f"ID: {app_id}, Name: {name}, User: @{username}, Status: {status}\n"
    await safe_edit_message_text(update, message, reply_markup=admin_workers_menu_keyboard())
    return ADMIN_MENU


async def view_feedback_admin(update: Update, context: CallbackContext) -> int:
    """Displays all customer feedback to the admin."""
    query = update.callback_query
    await query.answer()
    feedback_list = get_all_feedback()
    if not feedback_list:
        await safe_edit_message_text(update, "No customer feedback yet.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")]]))
        return ADMIN_MENU

    message = "📝 Customer Feedbacks:\n\n"
    for feedback in feedback_list:
        _, _, username, name, feedback_text, timestamp = feedback
        message += f"👤 **{name}** (@{username}) on {timestamp.strftime('%Y-%m-%d %H:%M')}:\n"
        message += f"   - \"{feedback_text}\"\n\n"

    await safe_edit_message_text(update, message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_main_menu")]]))
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
            INDOMIE_FLAVOR: [CallbackQueryHandler(indomie_flavor, pattern="^flavor_")],
            INDOMIE_SIZE: [CallbackQueryHandler(indomie_size, pattern="^size_")],
            INDOMIE_MIXINGS: [CallbackQueryHandler(indomie_mixings, pattern="^mixing_")],
            INDOMIE_TOPPINGS: [CallbackQueryHandler(indomie_toppings, pattern="^topping_")],
            INDOMIE_BEVERAGES: [CallbackQueryHandler(handle_beverages, pattern="^bev_")],
            INDOMIE_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_extra_notes)],
            GET_DELIVERY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_delivery_time)],
            INDOMIE_VEGETABLES_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_vegetables_quantity)],
            INDOMIE_SUYA_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_suya_amount)],
            INDOMIE_EGG_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_egg_quantity)],
            INDOMIE_SAUSAGE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_sausage_quantity)],
            INDOMIE_CHICKEN_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_chicken_quantity)],
            INDOMIE_FRIED_FISH_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_fried_fish_quantity)],
            INDOMIE_WATER_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_water_quantity)],
            INDOMIE_COKE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_coke_quantity)],
            INDOMIE_MALT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_malt_quantity)],
            INDOMIE_JUICE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_juice_quantity)],
            CUSTARD_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custard_quantity)],
            CUSTARD_SOURCE: [CallbackQueryHandler(custard_source, pattern="^(own_custard|kitchen_custard)$")],
            CUSTARD_ADDITIONS: [
                CallbackQueryHandler(custard_additions, pattern="^(sugar|milk|none_additions|next_custard_quantities)$"),
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
                CallbackQueryHandler(admin_password, pattern="^admin_main_menu$"),
                CallbackQueryHandler(view_active_orders_admin, pattern="^view_active_orders$"),
                CallbackQueryHandler(view_taken_orders_admin, pattern="^view_taken_orders_admin$"),
                CallbackQueryHandler(view_all_orders_admin, pattern="^view_all_orders_admin$"),
                CallbackQueryHandler(view_workers_admin, pattern="^view_workers_admin$"),
                CallbackQueryHandler(view_active_applications_admin, pattern="^view_active_apps$"),
                CallbackQueryHandler(view_all_applications_admin, pattern="^view_all_apps$"),
            ],
        },
        fallbacks=[],
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
