import gspread
import os
import json
from google.oauth2.service_account import Credentials

def get_sheets_client():
    """
    Initializes and returns an authorized gspread client.

    Authenticates using service account credentials stored in the
    GOOGLE_CREDENTIALS environment variable.
    """
    try:
        creds_json_str = os.getenv("GOOGLE_CREDENTIALS")
        if not creds_json_str:
            raise ValueError("GOOGLE_CREDENTIALS environment variable not set.")

        creds_dict = json.loads(creds_json_str)

        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)

        return client
    except json.JSONDecodeError:
        raise ValueError("Failed to parse GOOGLE_CREDENTIALS. Make sure it's a valid JSON string.")
    except Exception as e:
        print(f"An error occurred while setting up Google Sheets client: {e}")
        return None
