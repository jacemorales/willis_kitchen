import gspread
import json
import sys
from datetime import datetime
import time
from gspread_client import get_sheets_client

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
worker_applications_sheet = spreadsheet.worksheet("WorkerApplications")
feedback_sheet = spreadsheet.worksheet("Feedback")
payments_sheet = spreadsheet.worksheet("Payments")

def add_or_update_user(user_id, username, first_name):
    """Adds a new user or updates the last_login if they already exist."""
    try:
        cell = users_sheet.find(str(user_id), in_column=1)
        # User exists, update last_login
        now = datetime.now().isoformat()
        users_sheet.update_cell(cell.row, 4, now)
    except AttributeError:
        # User does not exist, add new row
        now = datetime.now().isoformat()
        new_row = [user_id, username, first_name, now]
        users_sheet.append_row(new_row)

def get_all_unique_users():
    """Retrieves all unique user IDs from the Users sheet."""
    # Column 1 is 'user_id'
    user_ids = users_sheet.col_values(1)[1:] # Skip header
    return [int(uid) for uid in user_ids if uid.isdigit()]

def add_order(user_id, username, food_type, items, total, status='pending', delivery_info=None, notes=None):
    """Adds a new order to the Orders sheet."""
    order_id = int(time.time() * 1000) # milliseconds timestamp as order_id
    order_date = datetime.now().isoformat()
    
    # Ensure complex data is stored as JSON strings
    items_str = json.dumps(items)
    delivery_info_str = json.dumps(delivery_info if delivery_info else {})

    new_row = [
        order_id, user_id, username, food_type, items_str, total,
        order_date, status, delivery_info_str, notes, "" # taken_by is initially empty
    ]
    orders_sheet.append_row(new_row)
    add_or_update_user(user_id, username, "") # Log user activity
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

def update_order_status(order_id, status, worker_id=None):
    """Updates the status and taken_by field of an order."""
    try:
        cell = orders_sheet.find(str(order_id), in_column=1)
        # Column 8 is 'status', Column 11 is 'taken_by'
        orders_sheet.update_cell(cell.row, 8, status)
        if worker_id:
            orders_sheet.update_cell(cell.row, 11, worker_id)
    except AttributeError:
        print(f"Error: Order ID {order_id} not found.")

def add_worker_application(user_id, username, name, reg_no, matric_no, phone):
    """Adds a new worker application."""
    app_id = int(time.time() * 1000)
    new_row = [app_id, user_id, username, name, reg_no, matric_no, phone, 'pending']
    worker_applications_sheet.append_row(new_row)

def get_worker_applications(status=None):
    """Retrieves worker applications, optionally filtering by status."""
    all_apps = worker_applications_sheet.get_all_records()
    if status:
        return [app for app in all_apps if app.get('status') == status]
    return all_apps

def update_worker_application_status(application_id, status):
    """Updates the status of a worker application."""
    try:
        cell = worker_applications_sheet.find(str(application_id), in_column=1)
        # Column 8 is 'status'
        worker_applications_sheet.update_cell(cell.row, 8, status)
    except AttributeError:
        print(f"Error: Application ID {application_id} not found.")

def add_worker(user_id, name, reg_no, matric_no, phone):
    """Adds a new approved worker."""
    new_row = [user_id, name, reg_no, matric_no, phone, 'active']
    workers_sheet.append_row(new_row)

def get_all_workers(active_only=True):
    """Retrieves all workers."""
    all_workers = workers_sheet.get_all_records()
    if active_only:
        return [w for w in all_workers if w.get('status') == 'active']
    return all_workers

def is_worker(user_id):
    """Checks if a user is an active worker."""
    all_workers = get_all_workers(active_only=True)
    return any(worker.get('user_id') == user_id for worker in all_workers)

def get_worker_orders(worker_id, status):
    """Retrieves orders taken by a worker with a specific status."""
    all_orders = orders_sheet.get_all_records()
    return [
        order for order in all_orders 
        if order.get('taken_by') == worker_id and order.get('status') == status
    ]
    
def add_feedback(user_id, username, name, feedback_text):
    """Adds customer feedback."""
    feedback_id = int(time.time() * 1000)
    timestamp = datetime.now().isoformat()
    new_row = [feedback_id, user_id, username, name, feedback_text, timestamp]
    feedback_sheet.append_row(new_row)

def get_all_feedback():
    """Retrieves all customer feedback."""
    return feedback_sheet.get_all_records()

def add_payment(order_id, screenshot_file_id, username, total):
    """Adds a payment record."""
    payment_id = int(time.time() * 1000)
    new_row = [payment_id, order_id, screenshot_file_id, username, total]
    payments_sheet.append_row(new_row)

def get_all_payments():
    """Retrieves all payment records."""
    return payments_sheet.get_all_records()
