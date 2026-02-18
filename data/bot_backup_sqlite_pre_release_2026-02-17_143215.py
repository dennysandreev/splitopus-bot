import requests
import json
import time
import os
import random
import string
from datetime import datetime

# --- Configuration ---
TOKEN = "8228071414:AAG31gr_raDybAdi_kNkyGZ8mpzBkiZX0VU"
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
DATA_DIR = "skills/thai_split_bot/data"
USERS_FILE = f"{DATA_DIR}/users.json"
TRIPS_FILE = f"{DATA_DIR}/trips.json"
DRAFTS_FILE = f"{DATA_DIR}/drafts.json"

CATEGORIES = {
    "FOOD": "🍔 Еда",
    "ALCOHOL": "🍺 Алкоголь",
    "TRANSPORT": "🚕 Транспорт",
    "SHOP": "🛒 Магазин",
    "FUN": "🎉 Развлечения",
    "HOME": "🏠 Жилье",
    "REPAYMENT": "💸 Возврат долга",
    "OTHER": "📦 Другое"
}

CURRENCIES = {
    "THB": "🇹🇭 THB",
    "RUB": "🇷🇺 RUB",
    "USD": "🇺🇸 USD",
    "EUR": "🇪🇺 EUR",
    "AED": "🇦🇪 AED",
    "CUSTOM": "✏️ Своя"
}

# --- Database ---
def load_json(path):
    if os.path.exists(path):
        with open(path, 'r') as f: return json.load(f)
    return {}

def save_json(path, data):
    with open(path, 'w') as f: json.dump(data, f, indent=2, ensure_ascii=False)

# --- Logic ---
def generate_trip_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def get_trip(trip_id):
    trips = load_json(TRIPS_FILE)
    return trips.get(trip_id)

def get_active_trip_id(user_id):
    users = load_json(USERS_FILE)
    return users.get(str(user_id), {}).get('active_trip_id')

def calculate_balance(trip_id):
    trip = get_trip(trip_id)
    if not trip: return {}, 0, {} # Added return for empty dict for total_paid_by_member
    
    balances = {uid: 0.0 for uid in trip['members']}
    total_spent_on_trip = 0.0 # Renamed for clarity
    total_paid_by_member = {uid: 0.0 for uid in trip['members']} # New dictionary
    
    for exp in trip['expenses']:
        cat = exp.get('category', 'OTHER')
        payer = str(exp['payer_id'])
        amount = float(exp['amount'])
        
        # Total amount spent on trip's common needs
        if cat != "REPAYMENT":
            total_spent_on_trip += amount
        
        # Total amount each member contributed to the system (including debts they lent)
        if payer in total_paid_by_member: # Check if payer is a valid member
            total_paid_by_member[payer] += amount
        
        split = exp['split']
        if payer in balances: balances[payer] += amount # Ensure payer is in balances
        for uid, share in split.items():
            if str(uid) in balances: balances[str(uid)] -= share # Ensure uid is in balances
            
    return balances, total_spent_on_trip, total_paid_by_member # Changed return values

def get_my_stats(trip_id, my_uid):
    trip = get_trip(trip_id)
    if not trip: return {}
    
    stats = {"total_share": 0.0, "cats": {}, "my_repayments": [], "received_repayments": []}
    my_uid = str(my_uid)
    
    for exp in trip['expenses']:
        cat = exp.get('category', 'OTHER')
        payer = str(exp['payer_id'])
        amount = float(exp['amount'])
        desc = exp.get('desc', 'Расход') # Added for detail
        
        if cat == "REPAYMENT":
            # I repaid a debt
            if payer == my_uid:
                target_uid = list(exp['split'].keys())[0]
                stats["my_repayments"].append({"to": target_uid, "amount": amount, "ts": exp['ts']})
            # Debt was repaid to me
            elif my_uid in exp['split']:
                stats["received_repayments"].append({"from": payer, "amount": amount, "ts": exp['ts']})
            continue # Skip REPAYMENT for regular expenses
        
        split = exp.get('split', {})
        my_share = split.get(my_uid, 0.0)
        
        if my_share > 0:
            stats["total_share"] += my_share
            stats["cats"][cat] = stats["cats"].get(cat, 0.0) + my_share
            
    return stats

def simplify_debts(balances, user_names):
    creditors = []
    debtors = []
    for uid, bal in balances.items():
        if bal > 0.01: creditors.append({'id': uid, 'amount': bal})
        if bal < -0.01: debtors.append({'id': uid, 'amount': -bal})
    creditors.sort(key=lambda x: x['amount'], reverse=True)
    debtors.sort(key=lambda x: x['amount'], reverse=True)
    transactions = []
    i = 0
    j = 0
    while i < len(debtors) and j < len(creditors):
        debtor = debtors[i]
        creditor = creditors[j]
        amount = min(debtor['amount'], creditor['amount'])
        transactions.append({
            'from': user_names.get(debtor['id'], debtor['id']),
            'to': user_names.get(creditor['id'], creditor['id']),
            'amount': amount
        })
        debtor['amount'] -= amount
        creditor['amount'] -= amount
        if debtor['amount'] < 0.01: i += 1
        if creditor['amount'] < 0.01: j += 1
    return transactions

# --- Telegram API ---
def send_message(chat_id, text, reply_markup=None):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload['reply_markup'] = json.dumps(reply_markup)
    try: requests.post(url, json=payload)
    except: pass

def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"{BASE_URL}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload['reply_markup'] = json.dumps(reply_markup)
    try: requests.post(url, json=payload)
    except: pass

def send_document(chat_id, file_path):
    url = f"{BASE_URL}/sendDocument"
    try:
        with open(file_path, 'rb') as f:
            requests.post(url, data={"chat_id": chat_id}, files={"document": f})
    except: pass

def get_updates(offset=None):
    url = f"{BASE_URL}/getUpdates"
    params = {"timeout": 1, "offset": offset}
    try:
        resp = requests.get(url, params=params, timeout=5).json()
        return resp.get("result", [])
    except: return []

# --- Handlers ---
def send_trip_dashboard(chat_id, user_id, message_id=None):
    users = load_json(USERS_FILE)
    trips = load_json(TRIPS_FILE)
    tid = users.get(str(user_id), {}).get('active_trip_id')
    
    if not tid or tid not in trips:
        return handle_command(chat_id, user_id, "User", "/start") 
        
    trip = trips[tid]
    name = trip.get('name', 'Trip')
    code = trip.get('code')
    
    msg = (
        f"🌴 *Поездка: {name}*\n"
        f"🔑 Код: `{code}`\n\n"
        "✍️ *Чтобы добавить трату:*\n"
        "Просто напишите сумму и название в этот чат.\n"
        "Пример: `500 Обед` или `200 Такси`\n\n"
        "👇 *Инструменты:*"
    )
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "📊 Баланс", "callback_data": "MENU_BALANCE"}, {"text": "👤 Моя статистика", "callback_data": "MENU_ME"}],
            [{"text": "💸 Вернуть долг", "callback_data": "MENU_REPAY"}, {"text": "🎲 Рулетка", "callback_data": "MENU_ROULETTE"}],
            [{"text": "🧾 Все траты", "callback_data": "MENU_ALL_EXPENSES"}, {"text": "📜 История трат", "callback_data": "MENU_RECENT_EXPENSES"}],
            [{"text": "📝 Заметки", "callback_data": "MENU_NOTES"}, {"text": "💾 Скачать отчет", "callback_data": "MENU_EXPORT"}],
            [{"text": "🔙 Назад к списку", "callback_data": "MENU_TRIPS"}, {"text": "📖 Инструкция", "callback_data": "SHOW_HELP"}]
        ]
    }
    
    if message_id:
        edit_message(chat_id, message_id, msg, reply_markup=keyboard)
    else:
        send_message(chat_id, msg, reply_markup=keyboard)

def send_all_expenses_list(chat_id, user_id, message_id=None, page=0):
    users = load_json(USERS_FILE)
    trips = load_json(TRIPS_FILE)
    tid = users.get(str(user_id), {}).get('active_trip_id')

    if not tid or tid not in trips:
        return send_message(chat_id, "Нет активной поездки.")

    trip = trips[tid]
    expenses = sorted(trip.get('expenses', []), key=lambda x: x['ts'], reverse=True) # Sort by date, newest first
    curr = trip.get('currency', 'THB')
    names = {uid: users.get(uid, {}).get('name', 'Unknown') for uid in trip['members']}

    PAGE_SIZE = 10 # Number of expenses per page
    total_pages = (len(expenses) + PAGE_SIZE - 1) // PAGE_SIZE
    
    start_idx = page * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, len(expenses))
    
    if not expenses:
        msg = "📝 В этой поездке пока нет трат."
        keyboard = {"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]}
        if message_id: edit_message(chat_id, message_id, msg, reply_markup=keyboard)
        else: send_message(chat_id, msg, reply_markup=keyboard)
        return

    msg = f"🧾 *Все траты ({trip.get('name')}):*\n\n"
    
    for i in range(start_idx, end_idx):
        exp = expenses[i]
        date = datetime.fromtimestamp(exp['ts']).strftime('%d.%m %H:%M')
        payer_name = names.get(str(exp['payer_id']), 'Unknown')
        amount = exp['amount']
        desc = exp.get('desc', 'Без описания')
        category_label = CATEGORIES.get(exp.get('category', 'OTHER'), exp.get('category', 'Другое'))
        
        # Only for regular expenses, not debt repayment
        if exp.get('category') != "REPAYMENT":
             msg += (
                f"*{date}* ({category_label})\n"
                f"👤 {payer_name} потратил: *{amount:,.0f} {curr}*\n"
                f"📝 {desc}\n\n"
            )
        else:
            # For debt repayment, show "Who repaid whom"
            repay_from_name = names.get(str(exp['payer_id']), 'Unknown')
            repay_to_id = list(exp['split'].keys())[0] # Get ID of recipient
            repay_to_name = names.get(str(repay_to_id), 'Unknown')
            msg += (
                f"*{date}* ({category_label})\n"
                f"💸 {repay_from_name} вернул {repay_to_name}: *{amount:,.0f} {curr}*\n\n"
            )


    keyboard_rows = []
    nav_row = []

    if page > 0:
        nav_row.append({"text": "◀️ Назад", "callback_data": f"ALL_EXPENSES_PAGE|{page-1}"})
    if page < total_pages - 1:
        nav_row.append({"text": "Вперед ▶️", "callback_data": f"ALL_EXPENSES_PAGE|{page+1}"})
    
    if nav_row:
        keyboard_rows.append(nav_row)

    keyboard_rows.append([{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}])
    
    keyboard = {"inline_keyboard": keyboard_rows}

    if message_id:
        edit_message(chat_id, message_id, msg, reply_markup=keyboard)
    else:
        send_message(chat_id, msg, reply_markup=keyboard)

def send_recent_expenses(chat_id, user_id, message_id=None):
    users = load_json(USERS_FILE)
    trips = load_json(TRIPS_FILE)
    tid = users.get(str(user_id), {}).get('active_trip_id')

    if not tid or tid not in trips:
        return send_message(chat_id, "Нет активной поездки.")

    trip = trips[tid]
    # Get the last 10 expenses, sorted by timestamp (newest first)
    recent_expenses = sorted(trip.get('expenses', []), key=lambda x: x['ts'], reverse=True)[:10]
    curr = trip.get('currency', 'THB')
    names = {uid: users.get(uid, {}).get('name', 'Unknown') for uid in trip['members']}

    if not recent_expenses:
        msg = "📝 Пока нет недавних трат в этой поездке."
        keyboard = {"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]}
        if message_id: edit_message(chat_id, message_id, msg, reply_markup=keyboard)
        else: send_message(chat_id, msg, reply_markup=keyboard)
        return

    msg = f"📜 *Последние 10 трат ({trip.get('name')}):*\n\n"
    
    for exp in recent_expenses:
        date = datetime.fromtimestamp(exp['ts']).strftime('%d.%m %H:%M')
        payer_name = names.get(str(exp['payer_id']), 'Unknown')
        amount = exp['amount']
        desc = exp.get('desc', 'Без описания')
        category_label = CATEGORIES.get(exp.get('category', 'OTHER'), exp.get('category', 'Другое'))
        
        if exp.get('category') != "REPAYMENT":
             msg += (
                f"*{date}* ({category_label})\n"
                f"👤 {payer_name} потратил: *{amount:,.0f} {curr}*\n"
                f"📝 {desc}\n\n"
            )
        else:
            repay_from_name = names.get(str(exp['payer_id']), 'Unknown')
            repay_to_id = list(exp['split'].keys())[0]
            repay_to_name = names.get(str(repay_to_id), 'Unknown')
            msg += (
                f"*{date}* ({category_label})\n"
                f"💸 {repay_from_name} вернул {repay_to_name}: *{amount:,.0f} {curr}*\n\n"
            )

    keyboard = {"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]}

    if message_id:
        edit_message(chat_id, message_id, msg, reply_markup=keyboard)
    else:
        send_message(chat_id, msg, reply_markup=keyboard)

def send_help_menu(chat_id):
    msg = (
        "📖 *Инструкция (v3.2.1):*\n\n"
        "💸 **Финансы:**\n"
        "• `500 Обед` — Добавить трату\n"
        "• `/balance` — Долги и общий бюджет\n"
        "• **[💸 Вернуть долг]** — Зафиксировать передачу денег\n"
        "• `/me` — Ваша личная статистика\n\n"
        "📝 **Заметки:**\n"
        "• `/note Код 1234` — Сохранить заметку\n"
        "• `/notes` — Показать все заметки\n\n"
        "🎲 **Развлечения:**\n"
        "• `/roulette` — Кто платит?\n\n"
        "⚙️ **Настройки:**\n"
        "• `/trips` — Сменить поездку\n"
        "• `/setrate` — Курс валют\n"
        "• `/export` — Скачать отчет"
    )
    send_message(chat_id, msg)

def notify_others(tid, payer_id, amount, desc, category, split_map):
    users = load_json(USERS_FILE)
    trips = load_json(TRIPS_FILE)
    payer_name = users.get(str(payer_id), {}).get('name', 'User')
    
    trip = trips[tid]
    curr = trip.get('currency', 'THB')
    rate = trip.get('rate', 0)
    
    markup = {"inline_keyboard": [[{"text": "📊 Мой Баланс", "callback_data": "SHOW_MY_BALANCE"}]]}
    
    for uid in trips[tid]['members']:
        if str(uid) != str(payer_id):
            my_share = split_map.get(str(uid), 0)
            if my_share > 0:
                share_text = f"*{my_share:.0f} {curr}*"
                if rate > 0: share_text += f" (~{my_share*rate:.0f} RUB)"
                
                title = "🧾 Новый Расход"
                if category == "REPAYMENT": title = "💸 Возврат Долга"
                
                msg = (
                    f"{title}\n"
                    f"👤 *{payer_name}* -> *{amount:,.0f} {curr}*\n"
                    f"📝 {desc}\n"
                    f"📉 {share_text}"
                )
                send_message(uid, msg, reply_markup=markup)

def handle_command(chat_id, user_id, user_name, text):
    users = load_json(USERS_FILE)
    trips = load_json(TRIPS_FILE)
    uid_str = str(user_id)
    
    if uid_str not in users:
        users[uid_str] = {"name": user_name, "active_trip_id": None, "joined_trips": [], "state": "IDLE"}
        save_json(USERS_FILE, users)
    elif "joined_trips" not in users[uid_str]: 
        old_tid = users[uid_str].get('trip_id')
        users[uid_str]["active_trip_id"] = old_tid
        users[uid_str]["joined_trips"] = [old_tid] if old_tid else []
        if 'trip_id' in users[uid_str]: del users[uid_str]['trip_id']
        save_json(USERS_FILE, users)

    cmd = text.split()[0]
    args = text.split()[1:]

    # LEVEL 1: GLOBAL MENU
    if cmd == "/start":
        keyboard = {"inline_keyboard": [
            [{"text": "🆕 Создать поездку", "callback_data": "MENU_CREATE"}],
            [{"text": "🔗 Присоединиться", "callback_data": "MENU_JOIN"}],
            [{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]
        ]}
        
        tid = users[uid_str].get('active_trip_id')
        status = ""
        if tid and tid in trips:
            t_name = trips[tid].get('name', 'Trip')
            keyboard["inline_keyboard"].insert(0, [{"text": f"⚙️ Меню: {t_name}", "callback_data": "OPEN_DASHBOARD"}])
            status = f"✅ Активная: *{t_name}*\n"
            
        msg = (
            "🌍 *ThaiSplitBot v3.2*\n\n"
            "Главное меню. Выберите действие:\n"
            f"{status}"
        )
        send_message(chat_id, msg, reply_markup=keyboard)
        
    elif cmd == "/menu":
        send_trip_dashboard(chat_id, user_id)

    elif cmd == "/balance": 
        handle_callback(chat_id, user_id, None, "MENU_BALANCE")
    
    elif cmd == "/me": 
        handle_callback(chat_id, user_id, None, "MENU_ME")
    
    elif cmd == "/trips": 
        handle_callback(chat_id, user_id, None, "MENU_TRIPS")
    
    elif cmd == "/help":
        send_help_menu(chat_id)

    elif cmd == "/note":
        tid = users[uid_str].get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.")
        note_text = " ".join(args)
        if not note_text: return send_message(chat_id, "Пример: `/note Код 1234`")
        if 'notes' not in trips[tid]: trips[tid]['notes'] = []
        trips[tid]['notes'].append({"text": note_text, "author": user_name, "ts": time.time()})
        save_json(TRIPS_FILE, trips)
        send_message(chat_id, "✅ Заметка сохранена!", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})

    elif cmd == "/notes":
        tid = users[uid_str].get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.")
        
        trip = trips[tid]
        notes = trip.get('notes', [])
        if not notes: return send_message(chat_id, "📝 Заметок пока нет.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        
        msg = "📝 *Важные заметки:*\n\n"
        for i, note in enumerate(notes):
            date = datetime.fromtimestamp(note['ts']).strftime('%d.%m')
            msg += f"{i+1}. {note['text']} _({note['author']}, {date})_\n"
            
        send_message(chat_id, msg, reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})

    elif cmd == "/roulette":
        tid = users[uid_str].get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.")
        
        members = trips[tid]['members']
        if not members: return send_message(chat_id, "В поездке нет участников для рулетки.")
        
        victim_id = random.choice(members)
        victim_name = users.get(str(victim_id), {}).get('name', 'Someone')
        
        # Сохраняем жертву и устанавливаем состояние ожидания
        users[str(victim_id)]['state'] = "WAITING_ROULETTE_AMOUNT"
        users[str(victim_id)]['roulette_trip_id'] = tid
        users[str(victim_id)]['roulette_payer_id'] = str(victim_id)
        save_json(USERS_FILE, users)

        send_message(chat_id, "🎲 *Крутим рулетку...*")
        time.sleep(1.5)
        
        # Уведомление всем, кто в чате рулетки
        send_message(chat_id, f"🎯 Сегодня платит: *{victim_name.upper()}*! 🎉", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        
        # Отдельное уведомление жертве с запросом суммы
        send_message(victim_id, f"🎉 Вы были выбраны рулеткой! Пожалуйста, введите сумму, которую вы оплатили:")

    elif cmd == "/export":
        tid = users[uid_str].get('active_trip_id')
        if not tid: return
        trip = trips[tid]
        curr = trip.get('currency', 'THB')
        csv_path = f"{DATA_DIR}/expenses.csv"
        with open(csv_path, 'w') as f:
            f.write(f"Date,Category,Payer,Amount ({curr}),Description\n")
            names = {uid: users.get(uid, {}).get('name', 'Unknown') for uid in trip['members']}
            for exp in trip['expenses']:
                payer = names.get(str(exp['payer_id']), exp['payer_id'])
                desc = exp.get('desc', '-')
                cat = exp.get('category', 'Other')
                f.write(f"{datetime.fromtimestamp(exp['ts'])},{cat},{payer},{exp['amount']},{desc}\n")
        send_document(chat_id, csv_path)
        send_message(chat_id, "✅ Отчет экспортирован.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})

    elif cmd == "/setrate":
        tid = users[uid_str].get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.")
        try:
            rate = float(args[0])
            trips[tid]['rate'] = rate
            save_json(TRIPS_FILE, trips)
            curr = trips[tid].get('currency', 'UNIT')
            send_message(chat_id, f"✅ Курс установлен: 1 {curr} = {rate} RUB.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        except:
            send_message(chat_id, "❌ Пример: `/setrate 2.8`")

def handle_text(chat_id, user_id, user_name, text):
    users = load_json(USERS_FILE)
    trips = load_json(TRIPS_FILE)
    uid_str = str(user_id)
    state = users.get(uid_str, {}).get('state', 'IDLE')
    
    # --- Roulette Amount State ---
    if state == "WAITING_ROULETTE_AMOUNT":
        try:
            amount = float(text)
            tid = users[uid_str].get('roulette_trip_id')
            payer_id = users[uid_str].get('roulette_payer_id')

            if not tid or not payer_id:
                send_message(chat_id, "⚠️ Произошла ошибка с рулеткой. Попробуйте снова.")
                users[uid_str]['state'] = "IDLE"
                save_json(USERS_FILE, users)
                return

            trip = trips[tid]
            members = trip['members']
            split_map = {member_id: amount / len(members) for member_id in members}

            new_exp = {
                "id": int(time.time()),
                "payer_id": payer_id,
                "amount": amount,
                "desc": "Расход по рулетке",
                "category": "FUN", # Or create a new category "ROULETTE"
                "split": split_map,
                "ts": time.time()
            }
            trips[tid]['expenses'].append(new_exp)
            save_json(TRIPS_FILE, trips)

            # Clear roulette state
            users[uid_str]['state'] = "IDLE"
            if 'roulette_trip_id' in users[uid_str]: del users[uid_str]['roulette_trip_id']
            if 'roulette_payer_id' in users[uid_str]: del users[uid_str]['roulette_payer_id']
            save_json(USERS_FILE, users)

            send_message(chat_id, f"✅ Расход по рулетке *{amount}* добавлен!", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            notify_others(tid, payer_id, amount, "Расход по рулетке", "FUN", split_map)

        except ValueError:
            send_message(chat_id, "❌ Введите числовое значение суммы.")
        return
    
    # --- Repayment Amount State ---
    if state == "WAITING_REPAYMENT_AMOUNT":
        try:
            amount = float(text)
            target_uid = users[uid_str].get('repay_target')
            tid = users[uid_str].get('active_trip_id')
            
            new_exp = {
                "id": int(time.time()),
                "payer_id": uid_str,
                "amount": amount,
                "desc": "Возврат долга",
                "category": "REPAYMENT",
                "split": {target_uid: amount},
                "ts": time.time()
            }
            trips[tid]['expenses'].append(new_exp)
            save_json(TRIPS_FILE, trips)
            
            users[uid_str]['state'] = "IDLE"
            save_json(USERS_FILE, users)
            
            target_name = users.get(target_uid, {}).get('name', 'User')
            send_message(chat_id, f"✅ Вы вернули *{amount}* пользователю *{target_name}*.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            send_message(target_uid, f"💸 *{user_name}* вернул вам долг: *{amount}*")
            
        except ValueError: send_message(chat_id, "❌ Введите число.")
        return

    # --- Joining Trip State ---
    if state == "WAITING_TRIP_CODE":
        code = text.strip().upper()
        found = None
        for tid, t in trips.items():
            if t['code'] == code: found = tid; break
            
        if found:
            users[uid_str]['active_trip_id'] = found
            if 'joined_trips' not in users[uid_str]: users[uid_str]['joined_trips'] = []
            if found not in users[uid_str]['joined_trips']: users[uid_str]['joined_trips'].append(found)
            
            users[uid_str]['state'] = "IDLE"
            if uid_str not in trips[found]['members']:
                trips[found]['members'].append(uid_str)
                for m in trips[found]['members']:
                    if m != uid_str: send_message(m, f"👋 *{user_name}* присоединился!")
            save_json(USERS_FILE, users)
            save_json(TRIPS_FILE, trips)
            
            send_message(chat_id, f"✅ Вы присоединились! Активная поездка: `{trips[found].get('name')}`")
            time.sleep(1)
            send_trip_dashboard(chat_id, user_id) 
        else:
            send_message(chat_id, "❌ Неверный код.")
        return

    # --- Naming Trip State ---
    if state == "WAITING_TRIP_NAME":
        name = text.strip()
        code = generate_trip_code()
        tid = f"trip_{int(time.time())}"
        trips[tid] = {"code": code, "creator": uid_str, "members": [uid_str], "expenses": [], "name": name, "rate": 0, "currency": "THB", "notes": []}
        
        users[uid_str]['active_trip_id'] = tid
        if 'joined_trips' not in users[uid_str]: users[uid_str]['joined_trips'] = []
        users[uid_str]['joined_trips'].append(tid)
        
        users[uid_str]['state'] = "WAITING_TRIP_CURRENCY"
        save_json(TRIPS_FILE, trips)
        save_json(USERS_FILE, users)
        
        keyboard = []
        row = []
        for code, label in CURRENCIES.items():
            row.append({"text": label, "callback_data": f"CURR|{code}"})
            if len(row) == 2: keyboard.append(row); row = []
        if row: keyboard.append(row)
        
        send_message(chat_id, f"💱 Выберите валюту для поездки *{name}*:", reply_markup={"inline_keyboard": keyboard})
        return

    # --- Trip Rate State ---
    if state == "WAITING_TRIP_RATE":
        try:
            rate = float(text.replace(',', '.'))
            tid = users[uid_str].get('active_trip_id')
            if tid:
                trips[tid]['rate'] = rate
                save_json(TRIPS_FILE, trips)
                code = trips[tid]['code']
                curr = trips[tid]['currency']
                send_message(chat_id, f"✅ Поездка создана!\nВалюта: *{curr}* (Курс: {rate})\n🔑 Код: `{code}`", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
                time.sleep(1)
                send_trip_dashboard(chat_id, user_id)
            users[uid_str]['state'] = "IDLE"
            save_json(USERS_FILE, users)
        except ValueError:
            send_message(chat_id, "❌ Введите число (например 2.8):")
        return

    # --- Custom Currency State ---
    if state == "WAITING_CUSTOM_CURRENCY":
        curr = text.strip().upper()[:3]
        tid = users[uid_str].get('active_trip_id')
        if tid:
            trips[tid]['currency'] = curr
            save_json(TRIPS_FILE, trips)
        users[uid_str]['state'] = "WAITING_TRIP_RATE"
        save_json(USERS_FILE, users)
        send_message(chat_id, f"💱 Какой курс 1 {curr} к рублю?")
        return

    # --- Custom Split State ---
    if state == "WAITING_CUSTOM_SPLIT":
        try:
            parts = text.split()
            amounts = [float(x) for x in parts]
            drafts = load_json(DRAFTS_FILE)
            draft_id = users[uid_str].get('draft_id')
            draft = drafts.get(draft_id)
            
            if not draft: return send_message(chat_id, "⚠️ Время вышло.")
            
            members = trips[draft['trip_id']]['members']
            if len(amounts) != len(members): return send_message(chat_id, f"❌ Нужно {len(members)} сумм.")
            if abs(sum(amounts) - draft['amount']) > 1.0: return send_message(chat_id, f"❌ Сумма не сходится.")
                 
            split_map = {m_id: amt for m_id, amt in zip(members, amounts)}
            
            new_exp = {
                "id": int(time.time()),
                "payer_id": draft['payer'],
                "amount": draft['amount'],
                "desc": draft['desc'],
                "category": draft.get('category', 'OTHER'),
                "split": split_map,
                "ts": time.time()
            }
            trips[draft['trip_id']]['expenses'].append(new_exp)
            save_json(TRIPS_FILE, trips)
            del drafts[draft_id]
            save_json(DRAFTS_FILE, drafts)
            users[uid_str]['state'] = "IDLE"
            save_json(USERS_FILE, users)
            
            send_message(chat_id, f"✅ Сохранено: *{draft['amount']}* ({draft['desc']})", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            notify_others(draft['trip_id'], draft['payer'], draft['amount'], draft['desc'], draft.get('category'), split_map)
                    
        except ValueError: send_message(chat_id, "❌ Введите числа.")
        return

    # --- Expense Input ---
    try:
        parts = text.split()
        amount = float(parts[0])
        desc = " ".join(parts[1:]) if len(parts) > 1 else "Расход"
        
        tid = get_active_trip_id(uid_str)
        if not tid: return send_message(chat_id, "Сначала создайте или вступите в поездку!")
        
        trip = trips[tid]
        curr = trip.get('currency', 'THB')
        
        drafts = load_json(DRAFTS_FILE)
        draft_id = f"{user_id}_{int(time.time())}"
        
        members = trips[tid]['members']
        selected = {uid: True for uid in members} 
        
        drafts[draft_id] = {
            "amount": amount,
            "desc": desc,
            "payer": str(user_id),
            "trip_id": tid,
            "selected": selected,
            "category": "OTHER"
        }
        save_json(DRAFTS_FILE, drafts)
        send_category_menu(chat_id, draft_id, curr)
        
    except ValueError: pass

def send_category_menu(chat_id, draft_id, curr, message_id=None):
    keyboard = []
    row = []
    for key, label in CATEGORIES.items():
        if key == "REPAYMENT": continue
        row.append({"text": label, "callback_data": f"CAT|{draft_id}|{label}"})
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    
    drafts = load_json(DRAFTS_FILE)
    amount = drafts[draft_id]['amount']
    desc = drafts[draft_id]['desc']
    text = f"💸 *{amount} {curr}* ({desc})\n🏷 Выберите категорию:"
    markup = {"inline_keyboard": keyboard}
    if message_id: edit_message(chat_id, message_id, text, reply_markup=markup)
    else: send_message(chat_id, text, reply_markup=markup)

def send_split_menu(chat_id, draft_id, user_name, message_id=None):
    drafts = load_json(DRAFTS_FILE)
    draft = drafts.get(draft_id)
    if not draft: return
    trip = get_trip(draft['trip_id'])
    curr = trip.get('currency', 'THB')
    users = load_json(USERS_FILE)
    amount = draft['amount']
    desc = draft['desc']
    cat = draft.get('category', '')
    selected = draft['selected']
    
    keyboard = []
    row = []
    for uid, is_active in selected.items():
        u_name = users.get(uid, {}).get('name', 'Unknown')
        status = "✅" if is_active else "⬜️"
        row.append({"text": f"{status} {u_name}", "callback_data": f"TOGGLE|{draft_id}|{uid}"})
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    
    count = sum(1 for v in selected.values() if v)
    share = amount / count if count > 0 else 0
    keyboard.append([{"text": f"💾 Сохранить (по {share:.0f})", "callback_data": f"CONFIRM|{draft_id}"}])
    keyboard.append([{"text": "✏️ Ввести вручную", "callback_data": f"CUSTOM|{draft_id}"}])
    keyboard.append([{"text": "❌ Отмена", "callback_data": f"CANCEL|{draft_id}"}])
    
    text = f"💸 *{amount} {curr}* ({desc})\n🏷 {cat}\nКто участвует?"
    markup = {"inline_keyboard": keyboard}
    if message_id: edit_message(chat_id, message_id, text, reply_markup=markup)
    else: send_message(chat_id, text, reply_markup=markup)

def handle_callback(chat_id, user_id, message_id, data):
    parts = data.split("|")
    cmd = parts[0]
    uid_str = str(user_id)
    
    # --- Navigation ---
    if cmd == "OPEN_DASHBOARD":
        send_trip_dashboard(chat_id, user_id, message_id)
        return

    if cmd == "MENU_CREATE":
        users = load_json(USERS_FILE)
        users[uid_str]['state'] = "WAITING_TRIP_NAME"
        save_json(USERS_FILE, users)
        send_message(chat_id, "✏️ Введите название поездки (например: `Тай 2026`):")
        return

    if cmd == "MENU_JOIN":
        users = load_json(USERS_FILE)
        users[uid_str]['state'] = "WAITING_TRIP_CODE"
        save_json(USERS_FILE, users)
        send_message(chat_id, "⌨️ Введите код:")
        return

    if cmd == "MENU_TRIPS":
        users = load_json(USERS_FILE)
        trips = load_json(TRIPS_FILE)
        joined = users[uid_str].get('joined_trips', [])
        keyboard = []
        active = users[uid_str].get('active_trip_id')
        
        for tid in joined:
            t = trips.get(tid)
            if not t: continue
            mark = "✅ " if tid == active else ""
            keyboard.append([{"text": f"{mark}{t.get('name')}", "callback_data": f"SWITCH_TRIP|{tid}"}])
        
        keyboard.append([{"text": "🔙 В главное меню", "callback_data": "BACK_MAIN"}]
        )
        edit_message(chat_id, message_id, "🗂 *Ваши поездки*:", reply_markup={"inline_keyboard": keyboard})
        return

    if cmd == "BACK_MAIN":
        handle_command(chat_id, user_id, "User", "/start")
        return

    if cmd == "SWITCH_TRIP":
        target_tid = parts[1]
        users = load_json(USERS_FILE)
        trips = load_json(TRIPS_FILE)
        if target_tid in users[uid_str].get('joined_trips', []):
            users[uid_str]['active_trip_id'] = target_tid
            save_json(USERS_FILE, users)
            send_trip_dashboard(chat_id, user_id, message_id)
        return

    # --- Dashboard Actions ---
    if cmd == "MENU_BALANCE": 
        users = load_json(USERS_FILE)
        tid = users[uid_str].get('active_trip_id')
        if not tid: return
        trips = load_json(TRIPS_FILE)
        trip = trips[tid]
        curr = trip.get('currency', 'THB')
        rate = trip.get('rate', 0)
        
        balances, total_trip_expenses, total_paid_by_member = calculate_balance(tid)
        names = {uid: users.get(uid, {}).get('name', 'Unknown') for uid in trip['members']}
        
        report = f"📊 *Баланс ({trip.get('name')}):*\n"
        
        # 1) Overall trip expenses
        total_trip_expenses_str = f"{total_trip_expenses:,.0f} {curr}"
        if rate > 0: total_trip_expenses_str += f" (~{total_trip_expenses*rate:,.0f} RUB)"
        report += f"💰 *Всего потрачено на поездку: {total_trip_expenses_str}*\n\n"
        
        # 2) Each member's paid amount and balance difference
        report += "👤 *Статистика участников:*\n"
        for uid in trip['members']:
            name = names.get(uid, uid)
            paid = total_paid_by_member.get(uid, 0.0)
            balance_amt = balances.get(uid, 0.0)
            emoji = "🟢" if balance_amt >= 0 else "🔴"
            
            paid_str = f"{paid:,.0f} {curr}"
            balance_str = f"{balance_amt:+.0f} {curr}"
            if rate > 0:
                paid_str += f" (~{paid*rate:,.0f} RUB)"
                balance_str += f" (~{balance_amt*rate:+.0f} RUB)"
            
            report += f"- {name}: Потрачено: *{paid_str}* | Баланс: {emoji} *{balance_str}*\n"
        
        # 3) Simplified debts
        simplified_transactions = simplify_debts(balances, names)
        if simplified_transactions:
            report += "\n🤝 *Кто кому должен (для выравнивания):*\n"
            for t in simplified_transactions:
                report += f"- {t['from']} должен {t['to']}: *{t['amount']:,.0f} {curr}*\n"
        else:
            report += "\n✅ *Балансы выровнены!*\n"

        keyboard = {"inline_keyboard": [
            [{"text": "⚙️ Сделать расчет", "callback_data": "MENU_SETTLE"}],
            [{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]
        ]}
        
        send_message(chat_id, report, reply_markup=keyboard)
        return

    elif cmd == "MENU_SETTLE":
        users = load_json(USERS_FILE)
        tid = users[uid_str].get('active_trip_id')
        if not tid: return
        trips = load_json(TRIPS_FILE)
        trip = trips[tid]
        curr = trip.get('currency', 'THB')
        rate = trip.get('rate', 0)
        balances, _, _ = calculate_balance(tid) # Get only balances
        names = {uid: users.get(uid, {}).get('name', 'Unknown') for uid in trip['members']}
        
        simplified_transactions = simplify_debts(balances, names)
        
        if not simplified_transactions:
            send_message(chat_id, "✅ Балансы уже выровнены, расчетов не требуется!", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            return

        # Send personalized notifications
        for transaction in simplified_transactions:
            from_name = transaction['from']
            to_name = transaction['to']
            amount = transaction['amount']
            
            amount_str = f"*{amount:,.0f} {curr}*"
            if rate > 0: amount_str += f" (~{amount*rate:,.0f} RUB)"

            # Find sender and recipient IDs by name
            from_id = next((uid for uid, name in names.items() if name == from_name), None)
            to_id = next((uid for uid, name in names.items() if name == to_name), None)

            if from_id:
                send_message(from_id, f"💸 Вам необходимо перевести *{amount_str}* пользователю *{to_name}*.")
            if to_id:
                send_message(to_id, f"💰 Пользователь *{from_name}* должен вам *{amount_str}*.")
        
        send_message(chat_id, "✅ Расчеты инициированы! Всем участникам отправлены личные сообщения с инструкциями.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "MENU_ALL_EXPENSES":
        send_all_expenses_list(chat_id, user_id, message_id)
        return

    if cmd == "ALL_EXPENSES_PAGE":
        page = int(parts[1])
        send_all_expenses_list(chat_id, user_id, message_id, page)
        return

    if cmd == "MENU_RECENT_EXPENSES":
        send_recent_expenses(chat_id, user_id, message_id)
        return

    if cmd == "MENU_ME":
        users = load_json(USERS_FILE)
        tid = users[uid_str].get('active_trip_id')
        if not tid: return
        trips = load_json(TRIPS_FILE)
        stats = get_my_stats(tid, uid_str)
        curr = trips[tid].get('currency', 'THB')
        names = {uid: users.get(uid, {}).get('name', 'Unknown') for uid in trips[tid]['members']} # Get names
        
        report = f"👤 *Ваша статистика ({trips[tid].get('name')}):*\n\n"
        
        report += f"💰 *Всего потрачено вами поровну: {stats['total_share']:.0f} {curr}*\n"
        if stats['cats']:
            report += "*Траты по категориям:*\n"
            for cat, amt in stats['cats'].items():
                report += f"  - {CATEGORIES.get(cat, cat)}: {amt:.0f} {curr}\n"
        
        if stats['my_repayments']:
            report += "\n💸 *Вы вернули долги:*\n"
            for rep in stats['my_repayments']:
                date = datetime.fromtimestamp(rep['ts']).strftime('%d.%m %H:%M')
                target_name = names.get(str(rep['to']), 'Unknown')
                report += f"  - {date}: *{rep['amount']:.0f} {curr}* -> {target_name}\n"

        if stats['received_repayments']:
            report += "\n💰 *Вам вернули долги:*\n"
            for rep in stats['received_repayments']:
                date = datetime.fromtimestamp(rep['ts']).strftime('%d.%m %H:%M')
                from_name = names.get(str(rep['from']), 'Unknown')
                report += f"  - {date}: *{rep['amount']:.0f} {curr}* от {from_name}\n"
            
        send_message(chat_id, report, reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "MENU_REPAY":
        users = load_json(USERS_FILE)
        trips = load_json(TRIPS_FILE)
        tid = users[uid_str].get('active_trip_id')
        if not tid: return
        keyboard = []
        for m in trips[tid]['members']:
            if str(m) != uid_str:
                name = users.get(str(m), {}).get('name', 'User')
                keyboard.append([{"text": name, "callback_data": f"REPAY_TO|{m}"}])
        send_message(chat_id, "💸 Кому?", reply_markup={"inline_keyboard": keyboard})
        return

    if cmd == "MENU_ROULETTE":
        handle_command(chat_id, user_id, "U", "/roulette")
        return

    if cmd == "MENU_NOTES":
        handle_command(chat_id, user_id, "U", "/notes")
        return

    if cmd == "MENU_EXPORT":
        handle_command(chat_id, user_id, "U", "/export")
        return

    # --- Logic Handlers ---
    if cmd == "REPAY_TO":
        target_uid = parts[1]
        users = load_json(USERS_FILE)
        users[uid_str]['state'] = "WAITING_REPAYMENT_AMOUNT"
        users[uid_str]['repay_target'] = target_uid
        save_json(USERS_FILE, users)
        send_message(chat_id, "💸 Введите сумму:")
        return

    if cmd == "CURR":
        curr_code = parts[1]
        users = load_json(USERS_FILE)
        trips = load_json(TRIPS_FILE)
        tid = users[uid_str].get('active_trip_id')
        if curr_code == "CUSTOM":
            users[uid_str]['state'] = "WAITING_CUSTOM_CURRENCY"
            save_json(USERS_FILE, users)
            send_message(chat_id, "⌨️ Введите код:")
        else:
            if tid: trips[tid]['currency'] = curr_code; save_json(TRIPS_FILE, trips)
            users[uid_str]['state'] = "WAITING_TRIP_RATE"
            save_json(USERS_FILE, users)
            send_message(chat_id, f"💱 Какой курс 1 {curr} к рублю?")
        return

    if cmd == "SHOW_MY_BALANCE":
        users = load_json(USERS_FILE)
        tid = users.get(uid_str, {}).get('active_trip_id')
        if tid:
            trips = load_json(TRIPS_FILE)
            trip = trips.get(tid)
            if trip:
                curr = trip.get('currency', 'THB')
                rate = trip.get('rate', 0)
                balances, _, _ = calculate_balance(tid) # Corrected to get 3 returns
                my_bal = balances.get(uid_str, 0)
                emoji = "🟢" if my_bal >= 0 else "🔴"
                amt = f"{my_bal:+.0f} {curr}"
                if rate > 0: amt += f" (~{my_bal*rate:+.0f} RUB)"
                send_message(chat_id, f"📊 Ваш баланс: {emoji} *{amt}*", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "SHOW_HELP": send_help_menu(chat_id); return

    if cmd == "CAT": 
        draft_id = parts[1]
        cat_label = parts[2]
        drafts = load_json(DRAFTS_FILE)
        if draft_id in drafts:
            drafts[draft_id]['category'] = cat_label
            save_json(DRAFTS_FILE, drafts)
            users = load_json(USERS_FILE)
            user_name = users.get(uid_str, {}).get('name', 'User')
            send_split_menu(chat_id, draft_id, user_name, message_id)
        return

    if cmd == "TOGGLE":
        target_uid = parts[2]
        draft_id = parts[1]
        drafts = load_json(DRAFTS_FILE)
        if draft_id in drafts:
            curr = drafts[draft_id]['selected'].get(target_uid, False)
            drafts[draft_id]['selected'][target_uid] = not curr
            save_json(DRAFTS_FILE, drafts)
            users = load_json(USERS_FILE)
            user_name = users.get(uid_str, {}).get('name', 'User')
            send_split_menu(chat_id, draft_id, user_name, message_id)
            
    elif cmd == "CONFIRM":
        draft_id = parts[1]
        drafts = load_json(DRAFTS_FILE)
        draft = drafts.get(draft_id)
        if not draft: return
        selected = draft['selected']
        active_uids = [uid for uid, v in selected.items() if v]
        if not active_uids: return 
        amount = draft['amount']
        share = amount / len(active_uids)
        split_map = {uid: share for uid in active_uids}
        trips = load_json(TRIPS_FILE)
        tid = draft['trip_id']
        new_exp = {
            "id": int(time.time()),
            "payer_id": draft['payer'],
            "amount": amount,
            "desc": draft['desc'],
            "category": draft.get('category', 'Other'),
            "split": split_map,
            "ts": time.time()
        }
        trips[tid]['expenses'].append(new_exp)
        save_json(TRIPS_FILE, trips)
        del drafts[draft_id]
        save_json(DRAFTS_FILE, drafts)
        edit_message(chat_id, message_id, f"✅ Сохранено: *{amount}* ({draft.get('category')})\nРазделено на {len(active_uids)} чел.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        notify_others(tid, draft['payer'], amount, draft['desc'], draft.get('category'), split_map)

    elif cmd == "CUSTOM":
        draft_id = parts[1]
        users = load_json(USERS_FILE)
        users[uid_str]['state'] = "WAITING_CUSTOM_SPLIT"
        users[uid_str]['draft_id'] = draft_id
        save_json(USERS_FILE, users)
        trips = load_json(TRIPS_FILE)
        drafts = load_json(DRAFTS_FILE)
        tid = drafts[draft_id]['trip_id']
        members = trips[tid]['members']
        names = [users.get(m, {}).get('name', 'User') for m in members]
        edit_message(chat_id, message_id, f"✏️ Введите суммы для:\n*{', '.join(names)}*\n\nЧерез пробел.")

    elif cmd == "CANCEL":
        draft_id = parts[1]
        drafts = load_json(DRAFTS_FILE)
        if draft_id in drafts: del drafts[draft_id]; save_json(DRAFTS_FILE, drafts)
        edit_message(chat_id, message_id, "❌ Отменено.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})

def main():
    print("ThaiSplitBot v3.2.1 (Fix) Started...")
    offset = None
    while True:
        updates = get_updates(offset)
        for u in updates:
            offset = u["update_id"] + 1
            if "message" in u:
                msg = u["message"]
                chat_id = msg["chat"]["id"]
                user_id = msg["from"]["id"]
                name = msg["from"].get("first_name", "User")
                text = msg.get("text", "")
                if text.startswith("/"): handle_command(chat_id, user_id, name, text)
                else: handle_text(chat_id, user_id, name, text)
            elif "callback_query" in u:
                cb = u["callback_query"]
                handle_callback(cb["message"]["chat"]["id"], cb["from"]["id"], cb["message"]["message_id"], cb["data"])
        time.sleep(1)

if __name__ == "__main__":
    main()
