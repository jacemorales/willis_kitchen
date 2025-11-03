import logging
import json
from datetime import datetime
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
from database import init_db, add_order, get_user_orders, get_todays_orders, get_all_orders

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Your Telegram Bot Token
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"

# States
(
    MAIN_MENU,
    PLACE_ORDER,
    INDOMIE_QUANTITY,
    INDOMIE_MIXINGS,
    INDOMIE_TOPPINGS,
    INDOMIE_EGG_QUANTITY,
    INDOMIE_SAUSAGE_QUANTITY,
    INDOMIE_SUYA_AMOUNT,
    CUSTARD_QUANTITY,
    CUSTARD_ADDITIONS,
    CUSTARD_SUGAR_QUANTITY,
    CUSTARD_MILK_QUANTITY,
    ADMIN_PASSWORD,
    ADMIN_MENU,
    ORDER_SUMMARY,
) = range(15)


async def start(update: Update, context: CallbackContext) -> int:
    """Displays the main menu."""
    keyboard = [
        [InlineKeyboardButton("🧾 Place Order", callback_data="place_order")],
        [InlineKeyboardButton("👀 View My Orders", callback_data="view_orders")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(
            "Welcome to Willis Kitchen 🍽️\n"
            "Please choose an option below:",
            reply_markup=reply_markup,
        )
    else:
        await update.callback_query.message.reply_text(
            "Welcome to Willis Kitchen 🍽️\n"
            "Please choose an option below:",
            reply_markup=reply_markup,
        )
    return MAIN_MENU


async def place_order(update: Update, context: CallbackContext) -> int:
    """Displays the food options."""
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🍜 Indomie", callback_data="indomie")],
        [InlineKeyboardButton("☕ Custard", callback_data="custard")],
        [InlineKeyboardButton("🍝 Spaghetti", callback_data="spaghetti")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "Please choose a food option:", reply_markup=reply_markup
    )
    return PLACE_ORDER


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
            InlineKeyboardButton("None", callback_data="none_mixings"),
        ],
        [
            InlineKeyboardButton("Next ➡️", callback_data="next_toppings"),
            InlineKeyboardButton("Cancel ❌", callback_data="cancel"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "What mixings would you like the Indomie to be cooked with?",
        reply_markup=reply_markup,
    )
    return INDOMIE_MIXINGS


async def indomie_mixings(update: Update, context: CallbackContext) -> int:
    """Stores the mixings."""
    query = update.callback_query
    await query.answer()
    mixing = query.data
    if mixing == "next_toppings":
        return await indomie_toppings_menu(update, context)

    if mixing != "none_mixings" and mixing not in context.user_data["order"]["mixings"]:
        context.user_data["order"]["mixings"].append(mixing)
    elif mixing in context.user_data["order"]["mixings"]:
        context.user_data["order"]["mixings"].remove(mixing)

    # Show updated selection
    selected_mixings = ", ".join(context.user_data["order"]["mixings"])
    await query.edit_message_text(
        f"Selected mixings: {selected_mixings}\n\n"
        "What mixings would you like the Indomie to be cooked with?",
        reply_markup=indomie_mixings_keyboard(),
    )
    return INDOMIE_MIXINGS


def indomie_mixings_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("Vegetables", callback_data="vegetables"),
            InlineKeyboardButton("Suya", callback_data="suya"),
            InlineKeyboardButton("None", callback_data="none_mixings"),
        ],
        [
            InlineKeyboardButton("Next ➡️", callback_data="next_toppings"),
            InlineKeyboardButton("Cancel ❌", callback_data="cancel"),
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
            InlineKeyboardButton("Next ➡️", callback_data="next_quantities"),
            InlineKeyboardButton("Cancel ❌", callback_data="cancel"),
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

    if (
        topping != "none_toppings"
        and topping not in context.user_data["order"]["toppings"]
    ):
        context.user_data["order"]["toppings"].append(topping)
    elif topping in context.user_data["order"]["toppings"]:
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
            InlineKeyboardButton("Cancel ❌", callback_data="cancel"),
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
    elif "suya" in order["mixings"]:
        await update.callback_query.edit_message_text("Enter the amount for suya (₦):")
        return INDOMIE_SUYA_AMOUNT
    else:
        return await show_order_summary(update, context)


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
        return await show_order_summary(update, context)


async def indomie_sausage_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of sausages."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Sausage"] = quantity
    order = context.user_data["order"]
    if "suya" in order["mixings"]:
        await update.message.reply_text("Enter the amount for suya (₦):")
        return INDOMIE_SUYA_AMOUNT
    else:
        return await show_order_summary(update, context)


async def indomie_suya_amount(update: Update, context: CallbackContext) -> int:
    """Stores the amount for suya."""
    amount = int(update.message.text)
    context.user_data["order"]["quantities"]["Suya"] = amount
    return await show_order_summary(update, context)


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
            InlineKeyboardButton("Next ➡️", callback_data="next_custard_quantities"),
            InlineKeyboardButton("Cancel ❌", callback_data="cancel"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "What would you like to add to your custard?",
        reply_markup=reply_markup,
    )
    return CUSTARD_ADDITIONS


async def custard_additions(update: Update, context: CallbackContext) -> int:
    """Stores the additions."""
    query = update.callback_query
    await query.answer()
    addition = query.data
    if addition == "next_custard_quantities":
        return await ask_for_custard_quantities(update, context)

    if (
        addition != "none_additions"
        and addition not in context.user_data["order"]["additions"]
    ):
        context.user_data["order"]["additions"].append(addition)
    elif addition in context.user_data["order"]["additions"]:
        context.user_data["order"]["additions"].remove(addition)

    # Show updated selection
    selected_additions = ", ".join(context.user_data["order"]["additions"])
    await query.edit_message_text(
        f"Selected additions: {selected_additions}\n\n"
        "What would you like to add to your custard?",
        reply_markup=custard_additions_keyboard(),
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
            InlineKeyboardButton("Cancel ❌", callback_data="cancel"),
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
        return await show_order_summary(update, context)


async def custard_sugar_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of sugar."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Sugar"] = quantity
    order = context.user_data["order"]
    if "milk" in order["additions"]:
        await update.message.reply_text("How many sachets of milk would you like?")
        return CUSTARD_MILK_QUANTITY
    else:
        return await show_order_summary(update, context)


async def custard_milk_quantity(update: Update, context: CallbackContext) -> int:
    """Stores the quantity of milk."""
    quantity = int(update.message.text)
    context.user_data["order"]["quantities"]["Milk"] = quantity
    return await show_order_summary(update, context)


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
        "Suya": 1,  # Price per Naira
        "Custard": 200,
        "Sugar": 50,
        "Milk": 400,
    }

    for item, quantity in order["quantities"].items():
        price = pricing[item] * quantity
        total += price
        summary += f"{item} ({quantity})\n"


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
    add_order(
        user_id=update.effective_user.id,
        username=update.effective_user.username,
        food_type=order["food"],
        mixings=order.get("mixings"),
        toppings=order.get("toppings"),
        quantities=order["quantities"],
        total=order["total"],
    )
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
        "Suya": 1,
        "Custard": 200,
        "Sugar": 50,
        "Milk": 400,
    }

    for item, quantity in order["quantities"].items():
        price = pricing[item] * quantity
        total += price
        bill += f"{item} ({quantity} × ₦{pricing[item]}) = ₦{price}\n"


    bill += "----------------------\n"
    bill += f"💰 Total = ₦{total}"

    await query.edit_message_text(bill)
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
        order_id, _, _, food_type, _, _, quantities, total, order_date = order
        quantities = json.loads(quantities)
        food_item = list(quantities.keys())[0]
        message += f"{i+1}️⃣ {food_type} ({food_item}: {quantities[food_item]}) - ₦{total} on {order_date}\n"
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
        _, user_id, username, food_type, _, _, quantities, total, order_date = order
        quantities = json.loads(quantities)
        food_item = list(quantities.keys())[0]
        message += f"👤 {username} ({user_id}) - {food_type} ({food_item}: {quantities[food_item]}) - ₦{total} at {order_date}\n"

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
        _, user_id, username, food_type, _, _, quantities, total, order_date = order
        quantities = json.loads(quantities)
        food_item = list(quantities.keys())[0]
        message += f"📅 {order_date} - 👤 {username} ({user_id}) - {food_type} ({food_item}: {quantities[food_item]}) - ₦{total}\n"

    await query.edit_message_text(message)
    return ADMIN_MENU


def main() -> None:
    """Start the bot."""
    # Initialize the database
    init_db()

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(place_order, pattern="^place_order$"),
                CallbackQueryHandler(view_orders, pattern="^view_orders$"),
            ],
            PLACE_ORDER: [
                CallbackQueryHandler(indomie_start, pattern="^indomie$"),
                CallbackQueryHandler(custard_start, pattern="^custard$"),
                CallbackQueryHandler(spaghetti_start, pattern="^spaghetti$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            INDOMIE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_quantity)],
            INDOMIE_MIXINGS: [
                CallbackQueryHandler(indomie_mixings, pattern="^(vegetables|suya|none_mixings)$"),
                CallbackQueryHandler(indomie_toppings, pattern="^next_toppings$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            INDOMIE_TOPPINGS: [
                CallbackQueryHandler(indomie_toppings, pattern="^(egg|sausage|none_toppings)$"),
                CallbackQueryHandler(show_order_summary, pattern="^next_quantities$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            INDOMIE_EGG_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_egg_quantity)],
            INDOMIE_SAUSAGE_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_sausage_quantity)],
            INDOMIE_SUYA_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, indomie_suya_amount)],
            CUSTARD_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custard_quantity)],
            CUSTARD_ADDITIONS: [
                CallbackQueryHandler(custard_additions, pattern="^(sugar|milk|none_additions)$"),
                CallbackQueryHandler(show_order_summary, pattern="^next_custard_quantities$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
            CUSTARD_SUGAR_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custard_sugar_quantity)],
            CUSTARD_MILK_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, custard_milk_quantity)],
            ORDER_SUMMARY: [
                CallbackQueryHandler(confirm_order, pattern="^confirm_order$"),
                CallbackQueryHandler(view_bill, pattern="^view_bill$"),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
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

    application.add_handler(conv_handler)
    application.add_handler(admin_conv_handler)

    # Start the Bot
    application.run_polling()


if __name__ == "__main__":
    main()
