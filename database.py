import sqlite3
import json
from datetime import datetime

DB_NAME = "kitchen_bot.db"

def init_db():
    """Initializes the database and creates/updates tables."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Create orders table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            food_type TEXT NOT NULL,
            mixings TEXT,
            toppings TEXT,
            quantities TEXT NOT NULL,
            total REAL NOT NULL,
            order_date DATETIME NOT NULL,
            source TEXT DEFAULT 'kitchen',
            status TEXT DEFAULT 'pending',
            taken_by INTEGER
        )
    """)

    # Add columns to orders table if they don't exist
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN source TEXT DEFAULT 'kitchen'")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN status TEXT DEFAULT 'pending'")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        cursor.execute("ALTER TABLE orders ADD COLUMN taken_by INTEGER")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Create workers table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            name TEXT,
            reg_no TEXT,
            matric_no TEXT,
            phone TEXT,
            status TEXT DEFAULT 'active'
        )
    """)
    conn.commit()
    conn.close()

def add_order(user_id, username, food_type, mixings, toppings, quantities, total, source='kitchen'):
    """Adds a new order to the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    order_date = datetime.now()
    cursor.execute("""
        INSERT INTO orders (user_id, username, food_type, mixings, toppings, quantities, total, order_date, source, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, username, food_type, json.dumps(mixings), json.dumps(toppings), json.dumps(quantities), total, order_date, source, 'pending'))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return order_id

def get_user_orders(user_id):
    """Retrieves all orders for a specific user."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY order_date DESC", (user_id,))
    orders = cursor.fetchall()
    conn.close()
    return orders

def get_all_orders():
    """Retrieves all orders from the database, sorted by date."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders ORDER BY order_date DESC")
    orders = cursor.fetchall()
    conn.close()
    return orders

def get_todays_orders():
    """Retrieves all orders placed today."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today_str = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT * FROM orders WHERE DATE(order_date) = ? ORDER BY order_date DESC", (today_str,))
    orders = cursor.fetchall()
    conn.close()
    return orders

def add_worker(user_id, name, reg_no, matric_no, phone):
    """Adds a new worker to the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO workers (user_id, name, reg_no, matric_no, phone, status)
        VALUES (?, ?, ?, ?, ?, 'active')
    """, (user_id, name, reg_no, matric_no, phone))
    conn.commit()
    conn.close()

def get_all_workers():
    """Retrieves all active workers."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM workers WHERE status = 'active'")
    workers = cursor.fetchall()
    conn.close()
    return [worker[0] for worker in workers]

def is_worker(user_id):
    """Checks if a user is an approved worker."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM workers WHERE user_id = ? AND status = 'active'", (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

def update_order_status(order_id, status, worker_id=None):
    """Updates the status of an order."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = ?, taken_by = ? WHERE id = ?", (status, worker_id, order_id))
    conn.commit()
    conn.close()

def get_worker_orders(worker_id, status):
    """Retrieves orders taken by a worker with a specific status."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE taken_by = ? AND status = ? ORDER BY order_date DESC", (worker_id, status))
    orders = cursor.fetchall()
    conn.close()
    return orders

def get_order_by_id(order_id):
    """Retrieves an order by its ID."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    conn.close()
    return order


if __name__ == '__main__':
    init_db()
    print("Database initialized.")
