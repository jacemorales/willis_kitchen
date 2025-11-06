import logging
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import random
import asyncio
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
)
from database import (
    init_db, add_order, get_user_orders, get_todays_orders, get_all_orders,
    add_worker, get_all_workers, is_worker, update_order_status,
    get_worker_orders, get_order_by_id, get_all_unique_users
)
from messages import DAILY_MESSAGES, SHARE_MESSAGE

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
    INDOMIE_QUANTITY,
    INDOMIE_MIXINGS,
    INDOMIE_TOPPINGS,
    INDOMIE_EGG_QUANTITY,
    INDOMIE_SAUSAGE_QUANTITY,
    INDOMIE_SUYA_AMOUNT,
    INDOMIE_SARDINE_QUANTITY,
    INDOMIE_SOURCE,
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
) = range(26)


async def start(update: Update, context: CallbackContext) -> int:
    """Displays the main menu."""
    keyboard = [
        [InlineKeyboardButton("🧑‍🍳 From Our Kitchen", callback_data="kitchen_menu")],
        [InlineKeyboardButton("☕ From Café", callback_data="cafe_menu")],
        [InlineKeyboardButton("💼 Work With Us", callback_data="work_with_us")],
        [InlineKeyboardButton("👀 View My Orders", callback_data="view_orders")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    welcome_text = "Welcome to Willis Kitchen 🍽️\nWhere would you like to order from?"
    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(welcome_text, reply_markup=reply_markup)
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
    await query.edit_message_text(
        "Please choose a food option from our kitchen:", reply_markup=reply_markup
    )
    return KITCHEN_MENU


async def cafe_menu(update: Update, context: CallbackContext) -> int:
    """Asks for the cafe order."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "Please include the item, quantity, and total amount to be spent on the item.\n\n"
        "Example: Meat Pie, 2, 1600"
    )
    return CAFE_ORDER


async def cafe_order(update: Update, context: CallbackContext) -> int:
    """Parses the cafe order, calculates the total, and asks for room number."""
    order_text = update.message.text
    try:
        parts = order_text.split(",")
        item = parts[0].strip()
        quantity = int(parts[1].strip())
        price = int("".join(filter(str.isdigit, parts[2])))
    except (ValueError, IndexError):
        await update.message.reply_text("Invalid format. Please use 'Item, Quantity, Amount'.")
        return CAFE_ORDER

    service_charge = ((price - 1) // 500 + 1) * 100
    total = price + service_charge

    context.user_data["order"] = {
        "food": item,
        "quantities": {"item": item, "quantity": quantity, "price": price},
        "service_charge": service_charge,
        "total": total,
        "source": "cafe",
    }

    # Ask for room number
    await update.message.reply_text("Please enter your room number for delivery:")
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

    await query.edit_message_text("Your café order has been placed successfully! 🎉")
    return await start(update, context)


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
    await query.edit_message_text("Please enter your full name:")
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
    """Stores the worker's phone number, sends the application to the admin, and notifies the user."""
    context.user_data["worker_application"]["phone"] = update.message.text

    application_data = context.user_data["worker_application"]
    user = update.effective_user

    # Notify admin
    admin_message = (
        f"🧑‍🍳 New Waiter Application:\n"
        f"Name: {application_data['name']}\n"
        f"Reg No: {application_data['reg_no']}\n"
        f"Matric No: {application_data['matric_no']}\n"
        f"Phone: {application_data['phone']}\n\n"
        f"Approve this worker?"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user.id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user.id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message, reply_markup=reply_markup)

    # Notify user
    await update.message.reply_text(
        "✅ Thank you for applying to become a Willis Kitchen worker.\n"
        "Your request is being processed."
    )

    context.bot_data[f"worker_application_{user.id}"] = application_data
    return ConversationHandler.END


async def handle_worker_approval(update: Update, context: CallbackContext) -> None:
    """Handles the admin's decision on a worker application."""
    query = update.callback_query
    await query.answer()

    action, user_id_str = query.data.split("_")
    user_id = int(user_id_str)

    application_data = context.bot_data.get(f"worker_application_{user_id}")

    if not application_data:
        await query.edit_message_text("Could not find application data. It might have expired.")
        return

    if action == "approve":
        add_worker(
            user_id=user_id,
            name=application_data["name"],
            reg_no=application_data["reg_no"],
            matric_no=application_data["matric_no"],
            phone=application_data["phone"],
        )
        await context.bot.send_message(
            chat_id=user_id,
            text="🎉 Congratulations! You’ve been approved as a Willis Kitchen worker. You can now start receiving orders."
        )
        await query.edit_message_text("Worker approved.")
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Your application was not approved at this time. Please try again later."
        )
        await query.edit_message_text("Worker rejected.")

    # Clean up the application data
    del context.bot_data[f"worker_application_{user_id}"]


async def share_command(update: Update, context: CallbackContext) -> None:
    """Sends the share message with share and copy buttons."""
    share_url = f"https://t.me/share/url?url={SHARE_MESSAGE}"
    keyboard = [
        [
            InlineKeyboardButton("Share 🚀", url=share_url),
            InlineKeyboardButton("Copy 📋", callback_data="copy_share_message"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(SHARE_MESSAGE, reply_markup=reply_markup)


async def copy_share_message_callback(update: Update, context: CallbackContext) -> None:
    """Sends the share message in a pre-formatted text block for easy copying."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(f"```\n{SHARE_MESSAGE}\n```", parse_mode="MarkdownV2")


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
    if update.callback_query:
        await update.callback_query.edit_message_text("Please enter your Hall and Room Number for delivery:")
    else:
        await update.message.reply_text("Please enter your Hall and Room Number for delivery:")
    return GET_ROOM_NUMBER


async def get_hall_and_room_number(update: Update, context: CallbackContext) -> int:
    """Stores the hall and room number and asks for the delivery time."""
    context.user_data["order"]["hall_and_room_number"] = update.message.text
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
        await query.edit_message_text(f"You have no {status} orders.")
        return WORKER_HISTORY

    message = f"📦 Your {status.capitalize()} Orders:\n"
    for order in orders:
        _, _, _, food_type, _, _, _, total, order_date, _, _, _, _, _, _ = order
        message += f"📅 {order_date} - {food_type} - ₦{total}\n"

    await query.edit_message_text(message)
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
        await query.edit_message_text("✅ You have successfully taken this order.")

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
        await query.edit_message_text("This order has already been taken.")


async def indomie_start(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of Indomie."""
    query = update.callback_query
    await query.answer()
    context.user_data["order"] = {
        "food": "Indomie",
        "mixings": [],
        "toppings": [],
        "quantities": {},
    }
    await query.edit_message_text("How many Indomie would you like to cook?")
    return INDOMIE_QUANTITY


async def indomie_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of Indomie and asks for mixings."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Indomie"] = quantity
    keyboard = [
        [
            InlineKeyboardButton("Vegetables", callback_data="vegetables"),
            InlineKeyboardButton("Suya", callback_data="suya"),
            InlineKeyboardButton("Sardine", callback_data="sardine"),
        ],
        [
            InlineKeyboardButton("None", callback_data="none_mixings"),
        ],
        [
            InlineKeyboardButton("Back ⬅️", callback_data="back_to_kitchen_menu"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    keyboard = [
        [
            InlineKeyboardButton("I have my own Indomie", callback_data="own_indomie"),
            InlineKeyboardButton("Use the kitchen's Indomie", callback_data="kitchen_indomie"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Will you be providing the Indomie, or should we use ours?",
        reply_markup=reply_markup,
    )
    return INDOMIE_SOURCE


async def indomie_mixings(update: Update, context: CallbackContext) -> int:
    """Stores the mixings."""
    query = update.callback_query
    await query.answer()
    mixing = query.data
    if mixing == "next_toppings":
        return await indomie_toppings_menu(update, context)

    if mixing == "none_mixings":
        context.user_data["order"]["mixings"] = []
        return await indomie_toppings_menu(update, context)

    if mixing not in context.user_data["order"]["mixings"]:
        context.user_data["order"]["mixings"].append(mixing)
    else:
        context.user_data["order"]["mixings"].remove(mixing)

    # Show updated selection
    selected_mixings = ", ".join(context.user_data["order"]["mixings"])
    await query.edit_message_text(
        f"Selected mixings: {selected_mixings}\n\n"
        "What mixings would you like the Indomie to be cooked with?",
        reply_markup=indomie_mixings_keyboard(),
    )
    return INDOMIE_MIXINGS


async def indomie_source(update: Update, context: CallbackContext) -> int:
    """Stores the source of the Indomie and asks for mixings."""
    query = update.callback_query
    await query.answer()
    source = query.data
    context.user_data["order"]["source_indomie"] = source

    keyboard = indomie_mixings_keyboard()
    await query.edit_message_text(
        "What mixings would you like the Indomie to be cooked with?",
        reply_markup=keyboard,
    )
    return INDOMIE_MIXINGS


def indomie_mixings_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("Vegetables", callback_data="vegetables"),
            InlineKeyboardButton("Suya", callback_data="suya"),
            InlineKeyboardButton("Sardine", callback_data="sardine"),
        ],
        [
            InlineKeyboardButton("None", callback_data="none_mixings"),
        ],
        [
            InlineKeyboardButton("Next ➡️", callback_data="next_toppings"),
            InlineKeyboardButton("Done ✅", callback_data="next_toppings"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def indomie_toppings_menu(update: Update, context: CallbackContext) -> int:
    """Displays the toppings menu."""
    keyboard = [
        [
            InlineKeyboardButton("Egg", callback_data="egg"),
            InlineKeyboardButton("Sausage", callback_data="sausage"),
            InlineKeyboardButton("None", callback_data="none_toppings"),
        ],
        [
            InlineKeyboardButton("Back ⬅️", callback_data="back_to_mixings"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(
        "What toppings would you like to add?", reply_markup=reply_markup
    )
    return INDOMIE_TOPPINGS


async def indomie_toppings(update: Update, context: CallbackContext) -> int:
    """Stores the toppings."""
    query = update.callback_query
    await query.answer()
    topping = query.data
    if topping == "next_quantities":
        return await ask_for_quantities(update, context)

    if topping == "none_toppings":
        context.user_data["order"]["toppings"] = []
        return await ask_for_quantities(update, context)

    if topping not in context.user_data["order"]["toppings"]:
        context.user_data["order"]["toppings"].append(topping)
    else:
        context.user_data["order"]["toppings"].remove(topping)

    # Show updated selection
    selected_toppings = ", ".join(context.user_data["order"]["toppings"])
    await query.edit_message_text(
        f"Selected toppings: {selected_toppings}\n\n"
        "What toppings would you like to add?",
        reply_markup=indomie_toppings_keyboard(),
    )
    return INDOMIE_TOPPINGS


def indomie_toppings_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("Egg", callback_data="egg"),
            InlineKeyboardButton("Sausage", callback_data="sausage"),
            InlineKeyboardButton("None", callback_data="none_toppings"),
        ],
        [
            InlineKeyboardButton("Next ➡️", callback_data="next_quantities"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def ask_for_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for quantities of selected items."""
    order = context.user_data["order"]
    if "egg" in order["toppings"]:
        await update.callback_query.edit_message_text("How many eggs would you like?")
        return INDOMIE_EGG_QUANTITY
    elif "sausage" in order["toppings"]:
        await update.callback_query.edit_message_text("How many sausages would you like?")
        return INDOMIE_SAUSAGE_QUANTITY
    elif "sardine" in order["mixings"]:
        await update.callback_query.edit_message_text("How many sardines would you like?")
        return INDOMIE_SARDINE_QUANTITY
    elif "suya" in order["mixings"]:
        await update.callback_query.edit_message_text("Enter the amount for suya (₦):")
        return INDOMIE_SUYA_AMOUNT
    else:
        return await ask_for_room_number(update, context)


async def indomie_egg_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of eggs."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Egg"] = quantity
    order = context.user_data["order"]
    if "sausage" in order["toppings"]:
        await update.message.reply_text("How many sausages would you like?")
        return INDOMIE_SAUSAGE_QUANTITY
    elif "suya" in order["mixings"]:
        await update.message.reply_text("Enter the amount for suya (₦):")
        return INDOMIE_SUYA_AMOUNT
    else:
        await update.message.reply_text("Please enter your room number for delivery:")
        return GET_ROOM_NUMBER


async def indomie_sausage_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of sausages."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Sausage"] = quantity
    order = context.user_data["order"]
    if "suya" in order["mixings"]:
        await update.message.reply_text("Enter the amount for suya (₦):")
        return INDOMIE_SUYA_AMOUNT
    else:
        await update.message.reply_text("Please enter your room number for delivery:")
        return GET_ROOM_NUMBER


async def indomie_sardine_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of sardines."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Sardine"] = quantity
    order = context.user_data["order"]
    if "suya" in order["mixings"]:
        await update.message.reply_text("Enter the amount for suya (₦):")
        return INDOMIE_SUYA_AMOUNT
    else:
        await update.message.reply_text("Please enter your Hall and Room Number for delivery:")
        return GET_ROOM_NUMBER


async def indomie_suya_amount(update: Update, context: CallbackContext) -> int:
    """Stores the amount for suya."""
    amount = int(update.message.text)
    context.user_data["order"]["quantities"]["Suya"] = amount
    await update.message.reply_text("Please enter your room number for delivery:")
    return GET_ROOM_NUMBER


async def custard_start(update: Update, context: CallbackContext) -> int:
    """Asks for the quantity of Custard."""
    query = update.callback_query
    await query.answer()
    context.user_data["order"] = {
        "food": "Custard",
        "additions": [],
        "quantities": {},
    }
    await query.edit_message_text("How many custard cups would you like to make?")
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
    await query.edit_message_text(
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
    await query.edit_message_text(
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
            InlineKeyboardButton("Next ➡️", callback_data="next_custard_quantities"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def ask_for_custard_quantities(update: Update, context: CallbackContext) -> int:
    """Asks for quantities of selected items."""
    order = context.user_data["order"]
    if "sugar" in order["additions"]:
        await update.callback_query.edit_message_text("How many spoons of sugar would you like?")
        return CUSTARD_SUGAR_QUANTITY
    elif "milk" in order["additions"]:
        await update.callback_query.edit_message_text("How many sachets of milk would you like?")
        return CUSTARD_MILK_QUANTITY
    else:
        return await ask_for_room_number(update, context)


async def custard_sugar_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of sugar."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Sugar"] = quantity
    order = context.user_data["order"]
    if "milk" in order["additions"]:
        await update.message.reply_text("How many sachets of milk would you like?")
        return CUSTARD_MILK_QUANTITY
    else:
        await update.message.reply_text("Please enter your room number for delivery:")
        return GET_ROOM_NUMBER


async def custard_milk_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of milk."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Milk"] = quantity
    await update.message.reply_text("Please enter your room number for delivery:")
    return GET_ROOM_NUMBER


async def spaghetti_start(update: Update, context: CallbackContext) -> int:
    """Handles the Spaghetti option."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Please contact customer care for more info 📞")
    # Return to the main menu
    return await start(update, context)


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
        "Vegetables": 900,
        "Sardine": 2000,
        "Suya": 1,  # Price per Naira
        "Custard": 200,
        "Sugar": 50,
        "Milk": 400,
    }

    if order.get("source") == "cafe":
        quantities = order["quantities"]
        price = quantities["price"]
        total = price + order["service_charge"]
        summary += f"{quantities['item']} ({quantities['quantity']}) - ₦{price}\n"
        summary += f"Service Charge - ₦{order['service_charge']}\n"
    else:
        for item, quantity in order["quantities"].items():
            if (item == "Indomie" and order.get("source_indomie") == "own_indomie") or \
               (item == "Custard" and order.get("source_custard") == "own_custard"):
                price = 0
            elif item == "Suya":
                price = quantity
                summary += f"Suya (₦{quantity})\n"
            else:
                price = pricing.get(item, 0) * quantity
                summary += f"{item} ({quantity})\n"
            total += price


    order["total"] = total
    summary += "----------------------\n"
    summary += f"Total: ₦{total}\n\n"
    summary += "Pay Online:\n"
    summary += "https://pay-naira.netlify.app"

    keyboard = [
        [
            InlineKeyboardButton("✅ Place Order", callback_data="confirm_order"),
            InlineKeyboardButton("💵 View Bill", callback_data="view_bill"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(summary, reply_markup=reply_markup)
    else:
        await update.message.reply_text(summary, reply_markup=reply_markup)

    return ORDER_SUMMARY


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

    await query.edit_message_text("Your order has been placed successfully! 🎉")
    return await start(update, context)


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
        "Vegetables": 900,
        "Sardine": 2000,
        "Suya": 1,
        "Custard": 200,
        "Sugar": 50,
        "Milk": 400,
    }

    if order.get("source") == "cafe":
        quantities = order["quantities"]
        price = quantities["price"]
        total = price + order["service_charge"]
        bill += f"{quantities['item']} ({quantities['quantity']}) - ₦{price}\n"
        bill += f"Service Charge - ₦{order['service_charge']}\n"
    else:
        for item, quantity in order["quantities"].items():
            if (item == "Indomie" and order.get("source_indomie") == "own_indomie") or \
               (item == "Custard" and order.get("source_custard") == "own_custard"):
                price = 0
                bill += f"{item} ({quantity} × ₦0) = ₦0\n"
            elif item == "Suya":
                price = quantity
                bill += f"Suya (₦{quantity})\n"
            else:
                price = pricing[item] * quantity
                bill += f"{item} ({quantity} × ₦{pricing[item]}) = ₦{price}\n"
            total += price


    bill += "----------------------\n"
    bill += f"💰 Total = ₦{total}"

    keyboard = [
        [
            InlineKeyboardButton("✅ Place Order", callback_data="confirm_order"),
            InlineKeyboardButton("⬅️ Back", callback_data="back_to_summary"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(bill, reply_markup=reply_markup)
    return ORDER_SUMMARY


async def view_orders(update: Update, context: CallbackContext) -> int:
    """Displays the user's past orders."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    orders = get_user_orders(user_id)

    if not orders:
        await query.edit_message_text("You have no orders yet. Start by placing one 🍽️")
        return MAIN_MENU

    message = "📦 Your Orders:\n"
    total_spent = 0
    for i, order in enumerate(orders):
        _, _, _, food_type, _, _, quantities, total, order_date, _, _, _, _, _, _ = order
        quantities = json.loads(quantities)

        if food_type == 'Indomie' or food_type == 'Custard':
            food_item = list(quantities.keys())[0]
            message += f"{i+1}️⃣ {food_type} ({food_item}: {quantities[food_item]}) - ₦{total} on {order_date}\n"
        else: # Cafe order
            message += f"{i+1}️⃣ {food_type} - ₦{total} on {order_date}\n"
        total_spent += total

    message += "-------------------\n"
    message += f"Total Spent: ₦{total_spent}"

    await query.edit_message_text(message)
    return MAIN_MENU


async def admin_start(update: Update, context: CallbackContext) -> int:
    """Asks for the admin password."""
    await update.message.reply_text("Enter the admin password:")
    return ADMIN_PASSWORD


async def admin_password(update: Update, context: CallbackContext) -> int:
    """Checks the admin password and shows the admin menu."""
    password = update.message.text
    if password == "wiliwili":
        keyboard = [
            [InlineKeyboardButton("View Today's Orders", callback_data="view_today")],
            [InlineKeyboardButton("View All Orders", callback_data="view_all")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Admin Menu:", reply_markup=reply_markup)
        return ADMIN_MENU
    else:
        await update.message.reply_text("Incorrect password.")
        return ConversationHandler.END


async def view_today_orders(update: Update, context: CallbackContext) -> int:
    """Displays today's orders."""
    query = update.callback_query
    await query.answer()
    orders = get_todays_orders()
    if not orders:
        await query.edit_message_text("No orders today.")
        return ADMIN_MENU

    message = "📅 Today's Orders:\n"
    for order in orders:
        _, user_id, username, food_type, _, _, quantities, total, order_date, _, _, _, _, _, _ = order
        quantities = json.loads(quantities)

        if food_type == 'Indomie' or food_type == 'Custard':
            food_item = list(quantities.keys())[0]
            message += f"👤 {username} ({user_id}) - {food_type} ({food_item}: {quantities[food_item]}) - ₦{total} at {order_date}\n"
        else: # Cafe order
            message += f"👤 {username} ({user_id}) - {food_type} - ₦{total} at {order_date}\n"

    await query.edit_message_text(message)
    return ADMIN_MENU


async def view_all_orders(update: Update, context: CallbackContext) -> int:
    """Displays all orders."""
    query = update.callback_query
    await query.answer()
    orders = get_all_orders()
    if not orders:
        await query.edit_message_text("No orders found.")
        return ADMIN_MENU

    message = "📦 All Orders (sorted by date):\n"
    for order in orders:
        _, user_id, username, food_type, _, _, quantities, total, order_date, _, _, _, _, _, _ = order
        quantities = json.loads(quantities)

        if food_type == 'Indomie' or food_type == 'Custard':
            food_item = list(quantities.keys())[0]
            message += f"📅 {order_date} - 👤 {username} ({user_id}) - {food_type} ({food_item}: {quantities[food_item]}) - ₦{total}\n"
        else: # Cafe order
            message += f"📅 {order_date} - 👤 {username} ({user_id}) - {food_type} - ₦{total}\n"

    await query.edit_message_text(message)
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


def main() -> None:
    """Start the bot."""
    # Initialize the database
    init_db()

    application = Application.builder().token(TOKEN).build()

    main_conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("work", work_with_us_command),
            CommandHandler("working", working_history),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(kitchen_menu, pattern="^kitchen_menu$"),
                CallbackQueryHandler(cafe_menu, pattern="^cafe_menu$"),
                CallbackQueryHandler(work_with_us, pattern="^work_with_us$"),
                CallbackQueryHandler(view_orders, pattern="^view_orders$"),
            ],
            KITCHEN_MENU: [
                CallbackQueryHandler(indomie_start, pattern="^indomie$"),
                CallbackQueryHandler(custard_start, pattern="^custard$"),
                CallbackQueryHandler(spaghetti_start, pattern="^spaghetti$"),
                CallbackQueryHandler(start, pattern="^main_menu$"),
            ],
            INDOMIE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_quantity)],
            INDOMIE_MIXINGS: [
                CallbackQueryHandler(indomie_mixings, pattern="^(vegetables|suya|sardine|none_mixings|next_toppings)$"),
                CallbackQueryHandler(back_to_kitchen_menu, pattern="^back_to_kitchen_menu$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            INDOMIE_TOPPINGS: [
                CallbackQueryHandler(indomie_toppings, pattern="^(egg|sausage|none_toppings|next_quantities)$"),
                CallbackQueryHandler(back_to_mixings, pattern="^back_to_mixings$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            INDOMIE_EGG_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_egg_quantity)],
            INDOMIE_SAUSAGE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_sausage_quantity)],
            INDOMIE_SARDINE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_sardine_quantity)],
            INDOMIE_SUYA_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_suya_amount)],
            INDOMIE_SOURCE: [CallbackQueryHandler(indomie_source, pattern="^(own_indomie|kitchen_indomie)$")],
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
                CallbackQueryHandler(confirm_order, pattern="^confirm_order$"),
                CallbackQueryHandler(view_bill, pattern="^view_bill$"),
                CallbackQueryHandler(show_order_summary, pattern="^back_to_summary$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
                CallbackQueryHandler(confirm_cafe_order, pattern="^confirm_cafe_order$"),
            ],
            CAFE_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, cafe_order)],
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

    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_start)],
        states={
            ADMIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_password)],
            ADMIN_MENU: [
                CallbackQueryHandler(view_today_orders, pattern="^view_today$"),
                CallbackQueryHandler(view_all_orders, pattern="^view_all$"),
            ],
        },
        fallbacks=[],
    )

    application.add_handler(main_conv_handler)
    application.add_handler(admin_conv_handler)
    application.add_handler(CommandHandler("share", share_command))
    application.add_handler(CallbackQueryHandler(handle_worker_approval, pattern="^(approve|reject)_"))
    application.add_handler(CallbackQueryHandler(take_order, pattern="^take_"))
    application.add_handler(CallbackQueryHandler(copy_share_message_callback, pattern="^copy_share_message$"))

    # Scheduler for daily messages
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_messages, 'interval', days=1, args=[application.bot])
    loop = asyncio.get_event_loop()
    scheduler.configure(event_loop=loop)
    scheduler.start()

    # Start the Bot
    application.run_polling()


if __name__ == "__main__":
    # Keep-alive server for Render
    class KeepAliveHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Bot is running fine!")

    def run_server():
        port = int(os.environ.get("PORT", 8080))
        server_address = ('', port)
        httpd = HTTPServer(server_address, KeepAliveHandler)
        httpd.serve_forever()

    threading.Thread(target=run_server).start()

    main()
