# Willis Kitchen Telegram Bot

This is a Telegram bot that allows users to order food from Willis Kitchen.

## Features

-   Step-by-step food ordering process.
-   Multi-select options for mixings and toppings.
-   Price calculation and billing breakdown.
-   Online payment link.
-   View past orders.
-   Admin panel to view today's and all orders.

## Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/willis-kitchen-bot.git
    cd willis-kitchen-bot
    ```

2.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up the Telegram Bot Token:**
    -   Open `main.py`.
    -   Replace `"YOUR_TELEGRAM_BOT_TOKEN"` with your actual Telegram Bot Token. You can also use an environment variable for better security.

4.  **Run the bot:**
    ```bash
    python3 main.py
    ```

## Usage

-   Start the bot by sending `/start`.
-   Use the `/admin` command to access the admin panel. The password is `wiliwili`.
