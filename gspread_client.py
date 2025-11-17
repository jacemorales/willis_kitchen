import gspread
import json
from google.auth.exceptions import RefreshError

def get_sheets_client():
    """
    Initializes and returns an authorized gspread client.

    Authenticates using credentials from a file named 'service_account.json'.
    """
    try:
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

        client = gspread.service_account(filename="service_account.json", scopes=scopes)
        return client
    except FileNotFoundError:
        print("CRITICAL: 'service_account.json' not found. Please create this file with your Google Cloud service account credentials.")
        return None
    except json.JSONDecodeError:
        print("CRITICAL: Could not decode 'service_account.json'. The file may be corrupt or improperly formatted.")
        return None
    except RefreshError as e:
        print(f"CRITICAL: The credentials in 'service_account.json' are invalid. Please check the file and ensure it is correct. Details: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while setting up Google Sheets client: {e}")
        return None
