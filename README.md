# Willis Kitchen Telegram Bot

This is a Telegram bot that allows users to order food from Willis Kitchen.

## Features

-   Step-by-step food ordering process from the kitchen and a café.
-   Multi-select options for mixings and toppings.
-   Price calculation and billing breakdown.
-   Online payment link.
-   View past orders.
-   Worker application system with admin approval.
-   Order assignment system for workers.
-   Worker history command to view taken and accepted orders.
-   Admin panel to view today's and all orders.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/jacemorales/willis_kitchen.git
    cd willis_kitchen
    ```

2.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up the Telegram Bot Token and Admin ID:**
    -   Open `main.py`.
    -   Replace `"YOUR_TELEGRAM_BOT_TOKEN"` with your actual Telegram Bot Token.
    -   Replace `123456789` in `ADMIN_ID = 123456789` with your Telegram User ID.

4.  **Run the bot:**
    ```bash
    python3 main.py
    ```

## Usage

-   Start the bot by sending `/start`.
-   Use the `/work` command to apply to be a worker.
-   Approved workers can use the `/working` command to view their order history.
-   Use the `/admin` command to access the admin panel. The password is `wiliwili`.
