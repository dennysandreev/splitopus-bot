import requests
import json
import time

TOKEN = "8228071414:AAG31gr_raDybAdi_kNkyGZ8mpzBkiZX0VU"
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
USERS_FILE = "skills/thai_split_bot/data/users.json"

def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send to {chat_id}: {e}")

def main():
    try:
        with open(USERS_FILE, 'r') as f:
            users = json.load(f)
    except:
        print("No users found.")
        return

    msg = (
        "🚀 *ThaiSplitBot Обновился (v3.0)!*\n\n"
        "Мы добавили важные функции для вашего удобства:\n\n"
        "💸 **Вернуть долг** — Новая кнопка в меню. Теперь можно фиксировать передачу денег, и долг спишется корректно.\n"
        "📝 **Заметки** — Сохраняйте коды, пароли и адреса командой `/note`.\n"
        "👤 **Моя статистика** — Узнайте, сколько вы потратили лично (`/me`).\n"
        "🎲 **Рулетка** — Пусть случай решит, кто платит (`/roulette`).\n\n"
        "👉 *Нажмите /start, чтобы обновить меню.*"
    )

    count = 0
    for uid in users:
        print(f"Sending to {uid}...")
        send_message(uid, msg)
        count += 1
        time.sleep(0.1) # Respect rate limits

    print(f"Broadcast complete. Sent to {count} users.")

if __name__ == "__main__":
    main()
