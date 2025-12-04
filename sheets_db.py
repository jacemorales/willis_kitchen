import gspread
import json
import sys
from datetime import datetime
import time
from gspread_client import get_sheets_client
from utils import format_date

# It's recommended to store the spreadsheet name in an environment variable
# for flexibility, but for this task, we will hardcode it.
SPREADSHEET_NAME = "WillisKitchenBot_DB"

# Initialize client and open the spreadsheet
client = get_sheets_client()
if client is None:
    print("Failed to connect to Google Sheets. Please check your credentials.")
    sys.exit(1)

spreadsheet = client.open(SPREADSHEET_NAME)

# Get individual worksheets
users_sheet = spreadsheet.worksheet("Users")
orders_sheet = spreadsheet.worksheet("Orders")
workers_sheet = spreadsheet.worksheet("Workers")
feedback_sheet = spreadsheet.worksheet("Feedback")
payments_sheet = spreadsheet.worksheet("Payments")

def add_or_update_user(user_id, username, first_name):
    """Adds a new user or updates the last_login if they already exist."""
    try:
        cell = users_sheet.find(str(user_id), in_column=1)
        # User exists, update last_login
        now = format_date()
        users_sheet.update_cell(cell.row, 4, now)
    except AttributeError:
        # User does not exist, add new row
        now = format_date()
        new_row = [user_id, username, first_name, now]
        users_sheet.append_row(new_row)

def get_all_unique_users():
    """Retrieves all unique user IDs from the Users sheet."""
    # Column 1 is 'user_id'
    user_ids = users_sheet.col_values(1)[1:] # Skip header
    return [int(uid) for uid in user_ids if uid.isdigit()]

def add_order(user_id, username, food_type, items, total, service_charge, status='pending', delivery_info=None, notes=None, spaghetti_quantity=None):
    """Adds a new order to the Orders sheet."""
    order_id = int(time.time() * 1000)
    order_date = format_date()
    
    items_str = json.dumps(items)
    delivery_info_str = json.dumps(delivery_info if delivery_info else {})

    # The new column 'spaghetti_quantity' will be column 14
    new_row = [
        order_id, user_id, username, food_type, items_str, total,
        service_charge, order_date, status, delivery_info_str, notes,
        "", "", spaghetti_quantity if spaghetti_quantity else ""
    ]
    orders_sheet.append_row(new_row)
    add_or_update_user(user_id, username, "")
    return order_id

def get_user_orders(user_id):
    """Retrieves all orders for a specific user."""
    all_orders = orders_sheet.get_all_records()
    user_orders = [order for order in all_orders if order.get('user_id') == user_id]
    return user_orders

def get_all_orders():
    """Retrieves all orders from the database, sorted by date."""
    return orders_sheet.get_all_records()

def get_orders_by_status(status):
    """Retrieves all orders with a specific status or statuses."""
    all_orders = orders_sheet.get_all_records()
    statuses = status if isinstance(status, tuple) else (status,)
    return [order for order in all_orders if order.get('status') in statuses]

def get_order_by_id(order_id):
    """Retrieves an order by its ID."""
    try:
        cell = orders_sheet.find(str(order_id), in_column=1)
        row_values = orders_sheet.row_values(cell.row)
        headers = orders_sheet.row_values(1)
        return dict(zip(headers, row_values))
    except AttributeError:
        return None

def update_order_status(order_id, status, worker_id=None, delivery_issue=None):
    """Updates the status, taken_by, and delivery_issue fields of an order."""
    try:
        cell = orders_sheet.find(str(order_id), in_column=1)
        # Column 9 is 'status'
        orders_sheet.update_cell(cell.row, 9, status)
        if worker_id:
            # Column 12 is 'taken_by'
            orders_sheet.update_cell(cell.row, 12, worker_id)
        if delivery_issue:
            # Column 13 is 'delivery_issue'
            orders_sheet.update_cell(cell.row, 13, delivery_issue)
    except AttributeError:
        print(f"Error: Order ID {order_id} not found.")

def add_worker(user_id, name, reg_no, matric_no, phone, gender, bank_name=None, account_number=None, account_name=None, status='pending'):
    """Adds a new worker application to the Workers sheet with a 'pending' status."""
    new_row = [
        user_id, name, reg_no, matric_no, phone, status, gender,
        bank_name, account_number, account_name,
        json.dumps([]),  # Payout (empty array)
        0  # Total Payout
    ]
    workers_sheet.append_row(new_row)

def get_workers_by_status(status):
    """Retrieves workers from the sheet, filtering by status."""
    all_workers = workers_sheet.get_all_records()
    statuses = status if isinstance(status, tuple) else (status,)
    return [worker for worker in all_workers if worker.get('status') in statuses]

def update_worker_status(user_id, new_status):
    """Updates the status of a worker."""
    try:
        cell = workers_sheet.find(str(user_id), in_column=1)
        # Column 6 is 'status'
        workers_sheet.update_cell(cell.row, 6, new_status)
    except AttributeError:
        print(f"Error: Worker with User ID {user_id} not found.")

def update_worker_payout(worker_id, order_id, payout_amount):
    """Adds a payout record to a worker's profile and updates the total."""
    try:
        cell = workers_sheet.find(str(worker_id), in_column=1)
        
        # Get current payout list (column 11)
        payouts_str = workers_sheet.cell(cell.row, 11).value
        payouts = json.loads(payouts_str) if payouts_str else []
        
        # Add new payout record
        payouts.append({"order_id": order_id, "payout": payout_amount})
        workers_sheet.update_cell(cell.row, 11, json.dumps(payouts))
        
        # Update total payout (column 12)
        total_payout = sum(p['payout'] for p in payouts)
        workers_sheet.update_cell(cell.row, 12, total_payout)
        
    except (AttributeError, gspread.exceptions.CellNotFound):
        print(f"Error: Worker ID {worker_id} not found.")
    except json.JSONDecodeError:
        print(f"Error: Could not parse payout data for worker {worker_id}.")

def get_all_workers(approved_only=True):
    """Retrieves all workers, defaulting to only approved ones."""
    all_workers = workers_sheet.get_all_records()
    if approved_only:
        return [w for w in all_workers if w.get('status') == 'approved']
    return all_workers

def is_worker(user_id):
    """Checks if a user is an approved worker."""
    all_workers = get_all_workers(approved_only=True)
    return any(worker.get('user_id') == user_id for worker in all_workers)

def get_worker_orders(worker_id, status):
    """Retrievis orders taken by a worker with a specific status."""
    all_orders = orders_sheet.get_all_records()
    return [
        order for order in all_orders 
        if order.get('taken_by') == worker_id and order.get('status') == status
    ]
    
def add_feedback(user_id, username, name, feedback_text):
    """Adds customer feedback."""
    feedback_id = int(time.time() * 1000)
    timestamp = format_date()
    new_row = [feedback_id, user_id, username, name, feedback_text, timestamp]
    feedback_sheet.append_row(new_row)

def get_all_feedback():
    """Retrieves all customer feedback."""
    return feedback_sheet.get_all_records()

def add_payment(order_id, screenshot_file_id, username, total):
    """Adds a payment record."""
    payment_id = int(time.time() * 1000)
    timestamp = format_date()
    new_row = [payment_id, order_id, screenshot_file_id, username, total, timestamp]
    payments_sheet.append_row(new_row)

def get_all_payments():
    """Retrieves all payment records."""
    return payments_sheet.get_all_records()
