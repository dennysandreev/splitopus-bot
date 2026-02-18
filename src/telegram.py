import json
import logging
import time
import requests

# --- Logging Setup ---
logger = logging.getLogger(__name__)

class TelegramClient:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.session = requests.Session()
        
        # --- Rate Limiting ---
        self.last_request_time = 0
        self.min_interval = 0.05  # Global limit: ~20 req/s (max is 30)

    def _request(self, method, endpoint, params=None, files=None, json_data=None):
        """
        Internal request wrapper with Rate Limiting and Retry logic.
        """
        url = f"{self.base_url}/{endpoint}"
        
        # Simple Global Rate Limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        
        self.last_request_time = time.time()

        for attempt in range(1, 4):  # Try 3 times
            try:
                if method == "GET":
                    resp = self.session.get(url, params=params, timeout=10)
                elif method == "POST":
                    resp = self.session.post(url, json=json_data, data=params, files=files, timeout=10)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                # --- Handle Rate Limits (429) ---
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 1))
                    logger.warning(f"Rate limited by Telegram (429). Waiting {retry_after}s...")
                    time.sleep(retry_after + 0.5)  # Wait + buffer
                    continue
                
                # --- Handle Other Errors ---
                if resp.status_code != 200:
                    logger.error(f"Telegram API Error ({endpoint}): {resp.status_code} - {resp.text}")
                    # Don't retry client errors (4xx) except 429
                    if 400 <= resp.status_code < 500:
                        return None 
                    time.sleep(1) # Wait before retry server error
                    continue
                
                return resp.json()

            except requests.RequestException as e:
                logger.error(f"Network error ({endpoint}): {e}")
                time.sleep(1 * attempt) # Exponential backoff
        
        logger.error(f"Failed to execute {endpoint} after retries.")
        return None

    # --- Public API Methods ---
    def get_updates(self, offset=None, timeout=30):
        params = {"timeout": timeout, "offset": offset, "allowed_updates": ["message", "callback_query"]}
        # Long polling timeout needs to be greater than request timeout
        # So we increase request timeout inside _request if needed, but here we just pass params
        try:
            # We use a longer timeout for getUpdates specifically
            url = f"{self.base_url}/getUpdates"
            resp = self.session.get(url, params=params, timeout=timeout + 5)
            if resp.status_code == 200:
                return resp.json().get("result", [])
        except Exception as e:
            logger.error(f"getUpdates failed: {e}")
        return []

    def send_message(self, chat_id, text, reply_markup=None, parse_mode="Markdown"):
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup
        return self._request("POST", "sendMessage", json_data=payload)

    def edit_message(self, chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload['reply_markup'] = json.dumps(reply_markup) if isinstance(reply_markup, dict) else reply_markup
        return self._request("POST", "editMessageText", json_data=payload)

    def delete_message(self, chat_id, message_id):
        return self._request("POST", "deleteMessage", json_data={"chat_id": chat_id, "message_id": message_id})

    def send_document(self, chat_id, file_path):
        try:
            with open(file_path, 'rb') as f:
                return self._request("POST", "sendDocument", params={"chat_id": chat_id}, files={"document": f})
        except Exception as e:
            logger.error(f"Failed to send document: {e}")
            return None

    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text: payload['text'] = text
        return self._request("POST", "answerCallbackQuery", json_data=payload)
