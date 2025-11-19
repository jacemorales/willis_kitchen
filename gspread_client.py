import gspread
import os
import json
from google.oauth2.service_account import Credentials
from google.auth.exceptions import RefreshError

def get_sheets_client():
    """
    Initializes and returns an authorized gspread client.

    Authenticates using service account credentials stored in the
    GOOGLE_CREDENTIALS environment variable.
    """
    try:
        creds_json_str = os.getenv("GOOGLE_CREDENTIALS")
        if not creds_json_str:
            print("CRITICAL: GOOGLE_CREDENTIALS environment variable not set.")
            return None

        creds_dict = json.loads(creds_json_str)

        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)

        return client
    except json.JSONDecodeError:
        print("CRITICAL: Failed to parse GOOGLE_CREDENTIALS. Make sure it's a valid JSON string.")
        return None
    except RefreshError as e:
        print(f"CRITICAL: The credentials in GOOGLE_CREDENTIALS are invalid. Please check the value. Details: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while setting up Google Sheets client: {e}")
        return None
