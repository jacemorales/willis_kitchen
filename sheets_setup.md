# Google Sheets Setup Instructions

To use this bot, you need to set up several Google Sheets and share them with the service account associated with your bot's credentials.

## 1. Create the Google Sheets

You must create a new Google Sheets document. This document will contain all the necessary sheets (tabs) for the bot to function.

**Spreadsheet Name:** You can name the main spreadsheet document anything you like, for example, "WillisKitchenBot_DB".

## 2. Create the Individual Sheets (Tabs)

Inside the spreadsheet document, create the following sheets with the exact names and headers as listed below. The order of the columns is important.

### `Users` Sheet
This sheet stores information about every user who interacts with the bot.

| user_id | username | first_name | last_login |
|---|---|---|---|

- **user_id**: The unique Telegram user ID.
- **username**: The user's Telegram @username.
- **first_name**: The user's first name.
- **last_login**: The timestamp of the user's last interaction.

### `Orders` Sheet
This sheet contains a record of every order placed.

| order_id | user_id | username | food_type | items | total | order_date | status | delivery_info | notes | taken_by | delivery_issue |
|---|---|---|---|---|---|---|---|---|---|---|---|

- **order_id**: A unique ID for the order (e.g., a timestamp or an incrementing number).
- **user_id**: The Telegram user ID of the person who placed the order.
- **username**: The user's Telegram @username.
- **food_type**: The main category of the order (e.g., "Indomie", "Custard", "Cafe Order").
- **items**: A JSON string representing the list of items in the order.
- **total**: The total cost of the order.
- **order_date**: The timestamp when the order was placed.
- **status**: The current status of the order (e.g., `pending_payment`, `pending`, `taken`, `accepted`, `rejected`).
- **delivery_info**: A JSON string containing delivery details like `hall_and_room_number` and `delivery_time`.
- **notes**: Any additional notes provided by the user.
- **taken_by**: The user ID of the worker who took the order.

### `Workers` Sheet
This sheet manages the list of approved workers.

| user_id | name | reg_no | matric_no | phone | status | gender |
|---|---|---|---|---|---|---|

- **user_id**: The worker's Telegram user ID.
- **name**: The worker's full name.
- **reg_no**: Registration number.
- **matric_no**: Matriculation number.
- **phone**: Phone number.
- **status**: The worker's status (e.g., `active`, `inactive`).
- **gender**: The worker's gender (`male` or `female`).

### `WorkerApplications` Sheet
This sheet stores applications from users who want to become workers.

| application_id | user_id | username | name | reg_no | matric_no | phone | status | gender |
|---|---|---|---|---|---|---|---|---|

- **application_id**: A unique ID for the application.
- **user_id**: The applicant's Telegram user ID.
- **username**: The applicant's Telegram @username.
- **name**: The applicant's full name.
- **reg_no**: Registration number.
- **matric_no**: Matriculation number.
- **phone**: Phone number.
- **status**: The application status (`pending`, `approved`, `rejected`).

### `Feedback` Sheet
This sheet collects feedback from customers.

| feedback_id | user_id | username | name | feedback_text | timestamp |
|---|---|---|---|---|---|

- **feedback_id**: A unique ID for the feedback entry.
- **user_id**: The user's Telegram user ID.
- **username**: The user's Telegram @username.
- **name**: The user's full name.
- **feedback_text**: The text of the feedback.
- **timestamp**: The time the feedback was submitted.

### `Payments` Sheet
This sheet logs payment screenshot information.

| payment_id | order_id | screenshot_file_id | username | total | timestamp |
|---|---|---|---|---|---|
- **payment_id**: A unique ID for the payment.
- **order_id**: The ID of the order this payment is for.
- **screenshot_file_id**: The Telegram file ID of the uploaded screenshot.
- **username**: The user who made the payment.
- **total**: The total amount paid.
- **timestamp**: The time the payment was recorded.

## 3. Share the Spreadsheet with the Service Account

1.  Open the Google Sheets document.
2.  Click the "Share" button in the top-right corner.
3.  Find the `client_email` from your Google Service Account JSON credentials. It will look something like `your-bot-name@your-project-id.iam.gserviceaccount.com`.
4.  Paste this email address into the sharing dialog.
5.  Give the service account **Editor** permissions.
6.  Click "Send" or "Share".

This will allow the bot to programmatically read from and write to your new database sheets.
