import sqlite3
import json
from datetime import datetime

DB_NAME = "kitchen_bot.db"

def init_db():
    """Initializes the database and creates the orders table if it doesn't exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
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
            order_date DATETIME NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def add_order(user_id, username, food_type, mixings, toppings, quantities, total):
    """Adds a new order to the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    order_date = datetime.now()
    cursor.execute("""
        INSERT INTO orders (user_id, username, food_type, mixings, toppings, quantities, total, order_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, username, food_type, json.dumps(mixings), json.dumps(toppings), json.dumps(quantities), total, order_date))
    conn.commit()
    conn.close()

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

if __name__ == '__main__':
    init_db()
    print("Database initialized.")
