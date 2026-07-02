import requests
import json
from datetime import datetime

# ── GOOGLE API ENDPOINTS ──────────────────────────────────────────────────────
SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"
CALENDAR_BASE = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"

def export_to_sheets(token: str, portfolio: dict, watchlist: list) -> dict | None:
    """
    Creates a new Google Sheet containing portfolio positions and watchlists.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 1. Create spreadsheet metadata
    body = {
        "properties": {
            "title": f"FredAI Financial Intelligence Report — {datetime.now().strftime('%Y-%m-%d')}"
        },
        "sheets": [
            {"properties": {"title": "Portfolio Status"}},
            {"properties": {"title": "Active Watchlist"}}
        ]
    }
    
    try:
        r = requests.post(SHEETS_BASE, headers=headers, json=body, timeout=12)
        if r.status_code != 200:
            print(f"[Google Sheets] Create failed: {r.text}")
            return None
        res = r.json()
        sheet_id = res.get("spreadsheetId")
        sheet_url = res.get("spreadsheetUrl")
        
        # 2. Prepare portfolio grid data
        port_values = [["Asset / Symbol", "Shares / Qty", "Last Price", "Total Value", "Avg VADER Sentiment"]]
        for pos in portfolio.get("positions", []):
            port_values.append([
                pos.get("symbol", ""),
                pos.get("shares", 0),
                pos.get("price", 0.0),
                pos.get("value", 0.0),
                pos.get("sentiment", "neutral")
            ])
        port_values.append([])
        port_values.append(["Net Liquidation Value", portfolio.get("net_worth", 0.0)])
        port_values.append(["Total Cash", portfolio.get("cash", 0.0)])
        
        # 3. Prepare watchlist grid data
        wl_values = [["Symbol", "Interest Score", "Notes"]]
        for item in watchlist:
            wl_values.append([
                item.get("symbol", ""),
                item.get("interest_score", 10.0),
                item.get("notes", "")
            ])
            
        # 4. Populate values
        val_body = {
            "valueInputOption": "USER_ENTERED",
            "data": [
                {
                    "range": "Portfolio Status!A1:E50",
                    "values": port_values
                },
                {
                    "range": "Active Watchlist!A1:C50",
                    "values": wl_values
                }
            ]
        }
        
        up_url = f"{SHEETS_BASE}/{sheet_id}/values:batchUpdate"
        ur = requests.post(up_url, headers=headers, json=val_body, timeout=12)
        if ur.status_code == 200:
            return {"spreadsheetId": sheet_id, "url": sheet_url}
        else:
            print(f"[Google Sheets] Populate failed: {ur.text}")
    except Exception as e:
        print(f"[Google Sheets] Exception: {e}")
    return None

def sync_to_calendar(token: str, event_data: dict) -> bool:
    """
    Adds an economic calendar release event to Google Calendar.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Parse event details
    title = event_data.get("title", "Economic Release")
    desc = event_data.get("description", "")
    date_str = event_data.get("date") # e.g. "2026-07-01"
    
    body = {
        "summary": f"📊 FredAI: {title}",
        "description": desc,
        "start": {
            "date": date_str
        },
        "end": {
            "date": date_str
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 60}
            ]
        }
    }
    
    try:
        # Check if event already exists to prevent duplication
        list_url = f"{CALENDAR_BASE}?q={title}"
        lr = requests.get(list_url, headers=headers, timeout=10)
        if lr.status_code == 200 and lr.json().get("items"):
            # Already synced
            return True
            
        r = requests.post(CALENDAR_BASE, headers=headers, json=body, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[Google Calendar] Exception: {e}")
    return False

def backup_to_drive(token: str, profile_data: dict) -> bool:
    """
    Backs up user profile credentials, portfolio entries, and watchlist to Google Drive.
    """
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    metadata = {
        "name": "fredai_secure_backup.json",
        "mimeType": "application/json"
    }
    
    files = {
        "data": ("metadata", json.dumps(metadata), "application/json"),
        "file": ("file", json.dumps(profile_data), "application/json")
    }
    
    try:
        search_url = "https://www.googleapis.com/drive/v3/files?q=name='fredai_secure_backup.json' and trashed=false"
        sr = requests.get(search_url, headers=headers, timeout=10)
        file_id = None
        if sr.status_code == 200:
            items = sr.json().get("files", [])
            if items:
                file_id = items[0].get("id")
                
        if file_id:
            update_url = f"https://www.googleapis.com/upload/drive/v3/files/{file_id}?uploadType=media"
            up_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            ur = requests.patch(update_url, headers=up_headers, data=json.dumps(profile_data), timeout=12)
            return ur.status_code == 200
        else:
            r = requests.post(DRIVE_UPLOAD, headers=headers, files=files, timeout=15)
            return r.status_code == 200
    except Exception as e:
        print(f"[Google Drive] Exception: {e}")
    return False


def send_gmail_report(token: str, recipient: str, subject: str, html_content: str) -> bool:
    """
    Sends an HTML report to the recipient's email address using the Gmail send API.
    """
    import base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = "me"
    message["To"] = recipient
    
    part = MIMEText(html_content, "html")
    message.attach(part)
    
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    body = {
        "raw": raw_message
    }
    
    try:
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        r = requests.post(url, headers=headers, json=body, timeout=12)
        if r.status_code == 200:
            return True
        print(f"[Gmail API] Send failed: {r.text}")
    except Exception as e:
        print(f"[Gmail API] Exception: {e}")
    return False
