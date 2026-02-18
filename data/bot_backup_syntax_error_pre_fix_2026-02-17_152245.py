import requests
import json
import time
import os
import random
import string
import sqlite3
from datetime import datetime

# --- Configuration ---
TOKEN = "8228071414:AAG31gr_raDybAdi_kNkyGZ8mpzBkiZX0VU"
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
DATA_DIR = "skills/thai_split_bot/data"
DB_FILE = f"{DATA_DIR}/thai_split_bot.db"

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
def get_db_connection():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            active_trip_id TEXT,
            joined_trips TEXT, -- JSON array of trip_ids
            state TEXT DEFAULT 'IDLE',
            repay_target TEXT, -- For WAITING_REPAYMENT_AMOUNT
            draft_id TEXT,     -- For WAITING_CUSTOM_SPLIT
            roulette_trip_id TEXT, -- For WAITING_ROULETTE_AMOUNT
            roulette_payer_id TEXT -- For WAITING_ROULETTE_AMOUNT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trips (
            trip_id TEXT PRIMARY KEY,
            code TEXT UNIQUE,
            creator_id TEXT,
            name TEXT,
            currency TEXT,
            rate REAL,
            members TEXT, -- JSON array of user_ids
            notes TEXT    -- JSON array of note objects
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
            trip_id TEXT,
            payer_id TEXT,
            amount REAL,
            description TEXT,
            category TEXT,
            split_json TEXT, -- JSON string of {user_id: share_amount}
            timestamp REAL,
            FOREIGN KEY (trip_id) REFERENCES trips (trip_id),
            FOREIGN KEY (payer_id) REFERENCES users (user_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            draft_id TEXT PRIMARY KEY,
            user_id TEXT,
            amount REAL,
            description TEXT,
            payer_id TEXT,
            trip_id TEXT,
            selected_members TEXT, -- JSON string of {user_id: bool}
            category TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (trip_id) REFERENCES trips (trip_id)
        )
    """)
    conn.commit()
    conn.close()

def migrate_json_to_db():
    users_json_file = f"{DATA_DIR}/users.json"
    trips_json_file = f"{DATA_DIR}/trips.json"
    drafts_json_file = f"{DATA_DIR}/drafts.json"

    if not os.path.exists(users_json_file) and \
       not os.path.exists(trips_json_file) and \
       not os.path.exists(drafts_json_file):
        return # No old JSON files to migrate

    conn = get_db_connection()
    cursor = conn.cursor()

    # Migrate users
    if os.path.exists(users_json_file):
        with open(users_json_file, 'r') as f:
            old_users = json.load(f)
        for user_id, user_data in old_users.items():
            cursor.execute("INSERT OR IGNORE INTO users (user_id, name, active_trip_id, joined_trips, state) VALUES (?, ?, ?, ?, ?)",
                           (user_id, user_data.get('name', 'User'), user_data.get('active_trip_id'),
                            json.dumps(user_data.get('joined_trips', [])), user_data.get('state', 'IDLE')))
        os.remove(users_json_file) # Remove after migration
        print(f"Migrated {len(old_users)} users from JSON to DB.")

    # Migrate trips
    if os.path.exists(trips_json_file):
        with open(trips_json_file, 'r') as f:
            old_trips = json.load(f)
        for trip_id, trip_data in old_trips.items():
            cursor.execute("INSERT OR IGNORE INTO trips (trip_id, code, creator_id, name, currency, rate, members, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (trip_id, trip_data.get('code'), trip_data.get('creator'), trip_data.get('name'),
                            trip_data.get('currency', 'THB'), trip_data.get('rate', 0.0),
                            json.dumps(trip_data.get('members', [])), json.dumps(trip_data.get('notes', []))))
            # Migrate expenses separately
            for expense in trip_data.get('expenses', []):
                cursor.execute("INSERT INTO expenses (trip_id, payer_id, amount, description, category, split_json, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (trip_id, str(expense.get('payer_id')), expense.get('amount'), expense.get('desc', 'Расход'),
                                expense.get('category', 'OTHER'), json.dumps(expense.get('split', {})), expense.get('ts')))
        os.remove(trips_json_file) # Remove after migration
        print(f"Migrated {len(old_trips)} trips and their expenses from JSON to DB.")

    # Migrate drafts (if any, though drafts are usually short-lived)
    if os.path.exists(drafts_json_file):
        with open(drafts_json_file, 'r') as f:
            old_drafts = json.load(f)
        for draft_id, draft_data in old_drafts.items():
            cursor.execute("INSERT OR IGNORE INTO drafts (draft_id, user_id, amount, description, payer_id, trip_id, selected_members, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                           (draft_id, draft_data.get('user_id', ''), draft_data.get('amount'), draft_data.get('desc'),
                            draft_data.get('payer'), draft_data.get('trip_id'), json.dumps(draft_data.get('selected', {})),
                            draft_data.get('category', 'OTHER')))
        os.remove(drafts_json_file) # Remove after migration
        print(f"Migrated {len(old_drafts)} drafts from JSON to DB.")

    conn.commit()
    conn.close()


# --- DB Access Helpers ---
def db_get_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),))
    user_data = cursor.fetchone()
    conn.close()
    if user_data:
        d = dict(user_data)
        d['joined_trips'] = json.loads(d['joined_trips'])
        return d
    return None

def db_save_user(user_id, user_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    joined_trips_json = json.dumps(user_data.get('joined_trips', []))
    cursor.execute("""
        INSERT OR REPLACE INTO users 
        (user_id, name, active_trip_id, joined_trips, state, repay_target, draft_id, roulette_trip_id, roulette_payer_id) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (str(user_id), user_data.get('name', 'User'), user_data.get('active_trip_id'),
          joined_trips_json, user_data.get('state', 'IDLE'),
          user_data.get('repay_target'), user_data.get('draft_id'),
          user_data.get('roulette_trip_id'), user_data.get('roulette_payer_id')))
    conn.commit()
    conn.close()

def db_get_trip(trip_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trips WHERE trip_id = ?", (trip_id,))
    trip_data = cursor.fetchone()
    conn.close()
    if trip_data:
        d = dict(trip_data)
        d['members'] = json.loads(d['members'])
        d['notes'] = json.loads(d['notes'])
        return d
    return None

def db_get_all_trips():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trips")
    trips_raw = cursor.fetchall()
    conn.close()
    trips = {}
    for row in trips_raw:
        d = dict(row)
        d['members'] = json.loads(d['members'])
        d['notes'] = json.loads(d['notes'])
        trips[d['trip_id']] = d
    return trips

def db_save_trip(trip_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    members_json = json.dumps(trip_data.get('members', []))
    notes_json = json.dumps(trip_data.get('notes', []))
    cursor.execute("""
        INSERT OR REPLACE INTO trips 
        (trip_id, code, creator_id, name, currency, rate, members, notes) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (trip_data['trip_id'], trip_data.get('code'), trip_data.get('creator_id'),
          trip_data.get('name'), trip_data.get('currency', 'THB'), trip_data.get('rate', 0.0),
          members_json, notes_json))
    conn.commit()
    conn.close()

def db_add_expense(expense_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    split_json_str = json.dumps(expense_data.get('split', {}))
    cursor.execute("""
        INSERT INTO expenses 
        (trip_id, payer_id, amount, description, category, split_json, timestamp) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (expense_data['trip_id'], str(expense_data['payer_id']), expense_data['amount'],
          expense_data.get('desc', 'Расход'), expense_data.get('category', 'OTHER'),
          split_json_str, expense_data.get('ts', time.time())))
    conn.commit()
    conn.close()

def db_get_draft(draft_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM drafts WHERE draft_id = ?", (draft_id,))
    draft_data = cursor.fetchone()
    conn.close()
    if draft_data:
        d = dict(draft_data)
        d['selected_members'] = json.loads(d['selected_members'])
        return d
    return None

def db_save_draft(draft_id, draft_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    selected_members_json = json.dumps(draft_data.get('selected_members', {}))
    cursor.execute("""
        INSERT OR REPLACE INTO drafts 
        (draft_id, user_id, amount, description, payer_id, trip_id, selected_members, category) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (draft_id, str(draft_data.get('user_id', '')), draft_data.get('amount'),
          draft_data.get('description'), str(draft_data.get('payer_id')), draft_data.get('trip_id'),
          selected_members_json, draft_data.get('category', 'OTHER')))
    conn.commit()
    conn.close()

def db_delete_draft(draft_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM drafts WHERE draft_id = ?", (draft_id,))
    conn.commit()
    conn.close()


# --- Logic ---
def generate_trip_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM trips WHERE code = ?", (code,))
        if cursor.fetchone()[0] == 0:
            conn.close()
            return code
        conn.close()

def get_trip(trip_id):
    return db_get_trip(trip_id)

def get_active_trip_id(user_id):
    user = db_get_user(user_id)
    return user.get('active_trip_id') if user else None

def calculate_balance(trip_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    balances = {}
    total_spent_on_trip = 0.0
    total_paid_by_member = {}

    # Get trip members
    trip_data = db_get_trip(trip_id)
    if not trip_data:
        conn.close()
        return {}, 0.0, {}

    members = trip_data['members']
    for member_id in members:
        balances[member_id] = 0.0
        total_paid_by_member[member_id] = 0.0

    # Get all expenses for the trip
    cursor.execute("SELECT payer_id, amount, category, split_json FROM expenses WHERE trip_id = ?", (trip_id,))
    expenses = cursor.fetchall()

    for exp_payer_id, exp_amount, exp_category, exp_split_json in expenses:
        split_map = json.loads(exp_split_json)

        # Update total_spent_on_trip for non-repayment expenses
        if exp_category != "REPAYMENT":
            total_spent_on_trip += exp_amount

        # Update total_paid_by_member
        if exp_payer_id in total_paid_by_member:
            total_paid_by_member[exp_payer_id] += exp_amount

        # Update individual balances
        if exp_payer_id in balances:
            balances[exp_payer_id] += exp_amount
        for uid, share in split_map.items():
            if uid in balances:
                balances[uid] -= share
    
    conn.close()
    return balances, total_spent_on_trip, total_paid_by_member

def get_my_stats(trip_id, my_uid):
    conn = get_db_connection()
    cursor = conn.cursor()

    stats = {"total_share": 0.0, "cats": {}, "my_repayments": [], "received_repayments": []}
    my_uid = str(my_uid)

    # Simpler approach: fetch all and filter in Python for robustness
    cursor.execute("SELECT payer_id, amount, description, category, split_json, timestamp FROM expenses WHERE trip_id = ?", (trip_id,))
    expenses = cursor.fetchall()
    
    # Need user names for repayments (fetch them once)
    user_names = {}
    cursor.execute("SELECT user_id, name FROM users")
    for row in cursor.fetchall():
        user_names[row['user_id']] = row['name'] # Access by name due to row_factory

    for exp_payer_id, exp_amount, exp_desc, exp_category, exp_split_json, exp_ts in expenses:
        split_map = json.loads(exp_split_json)
        
        if exp_category == "REPAYMENT":
            # I repaid a debt
            if exp_payer_id == my_uid:
                target_uid = list(split_map.keys())[0]
                stats["my_repayments"].append({"to": target_uid, "amount": exp_amount, "ts": exp_ts})
            # Debt was repaid to me
            elif my_uid in split_map:
                stats["received_repayments"].append({"from": exp_payer_id, "amount": exp_amount, "ts": exp_ts})
            continue

        my_share = split_map.get(my_uid, 0.0)
        if my_share > 0:
            stats["total_share"] += my_share
            stats["cats"][exp_category] = stats["cats"].get(exp_category, 0.0) + my_share
            
    conn.close()
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
def answer_callback_query(callback_query_id, text=None, show_alert=False):
    url = f"{BASE_URL}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text: payload["text"] = text
    if show_alert: payload["show_alert"] = show_alert
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error answering callback query {callback_query_id}: {e}")

def send_message(chat_id, text, reply_markup=None):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload['reply_markup'] = json.dumps(reply_markup)
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending message to {chat_id}: {e}")

def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"{BASE_URL}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup: payload['reply_markup'] = json.dumps(reply_markup)
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error editing message {message_id} in {chat_id}: {e}")

def send_document(chat_id, file_path):
    url = f"{BASE_URL}/sendDocument"
    try:
        with open(file_path, 'rb') as f:
            requests.post(url, data={"chat_id": chat_id}, files={"document": f})
    except Exception as e:
        print(f"Error sending document to {chat_id}: {e}")

def get_updates(offset=None):
    url = f"{BASE_URL}/getUpdates"
    params = {"timeout": 1, "offset": offset}
    try:
        resp = requests.get(url, params=params, timeout=5).json()
        return resp.get("result", [])
    except Exception as e:
        print(f"Error getting updates: {e}")
        return []

# --- Handlers ---
def send_trip_dashboard(chat_id, user_id, message_id=None):
    user = db_get_user(user_id)
    if not user:
        # If user somehow not in DB, force /start
        return handle_command(chat_id, user_id, "User", "/start") 

    tid = user.get('active_trip_id')
    
    if not tid:
        return handle_command(chat_id, user_id, "User", "/start") 
        
    trip = db_get_trip(tid)
    if not trip: # Trip might have been deleted or corrupted
        user['active_trip_id'] = None
        user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
        db_save_user(user_id, user)
        return handle_command(chat_id, user_id, "User", "/start")

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
    user = db_get_user(user_id)
    tid = user.get('active_trip_id')

    if not tid:
        return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})

    trip = db_get_trip(tid)
    if not trip: # Trip might have been deleted or corrupted
        user['active_trip_id'] = None
        user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
        db_save_user(user_id, user)
        return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT expense_id, payer_id, amount, description, category, split_json, timestamp FROM expenses WHERE trip_id = ? ORDER BY timestamp DESC", (tid,))
    expenses_raw = cursor.fetchall()
    conn.close()

    expenses = []
    for row in expenses_raw:
        d = dict(row)
        d['split'] = json.loads(d['split_json'])
        expenses.append(d)

    curr = trip.get('currency', 'THB')
    
    # Fetch all user names once
    user_names = {}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name FROM users")
    for row in cursor.fetchall():
        user_names[row['user_id']] = row['name']
    conn.close()

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

    msg = f"🧾 *Все траты ({trip.get('name')}):*\n_Страница {page + 1} из {total_pages}_\n\n"
    
    for i in range(start_idx, end_idx):
        exp = expenses[i]
        date = datetime.fromtimestamp(exp['timestamp']).strftime('%d.%m %H:%M')
        payer_name = user_names.get(str(exp['payer_id']), 'Unknown')
        amount = exp['amount']
        desc = exp.get('description', 'Без описания')
        category_label = CATEGORIES.get(exp.get('category', 'OTHER'), exp.get('category', 'Другое'))
        
        if exp.get('category') != "REPAYMENT":
             msg += (
                f"*{date}* ({category_label})\n"
                f"👤 {payer_name} потратил: *{amount:,.0f} {curr}*\n"
                f"📝 {desc}\n\n"
            )
        else:
            repay_from_name = user_names.get(str(exp['payer_id']), 'Unknown')
            repay_to_id = list(exp['split'].keys())[0] # Get ID of recipient
            repay_to_name = user_names.get(str(repay_to_id), 'Unknown')
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
    user = db_get_user(user_id)
    tid = user.get('active_trip_id')

    if not tid:
        return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})

    trip = db_get_trip(tid)
    if not trip: # Trip might have been deleted or corrupted
        user['active_trip_id'] = None
        user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
        db_save_user(user_id, user)
        return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

    conn = get_db_connection()
    cursor = conn.cursor()
    # Get the last 10 expenses, sorted by timestamp (newest first)
    cursor.execute("SELECT expense_id, payer_id, amount, description, category, split_json, timestamp FROM expenses WHERE trip_id = ? ORDER BY timestamp DESC LIMIT 10", (tid,))
    expenses_raw = cursor.fetchall()
    conn.close()

    recent_expenses = []
    for row in expenses_raw:
        d = dict(row)
        d['split'] = json.loads(d['split_json'])
        recent_expenses.append(d)

    curr = trip.get('currency', 'THB')
    
    # Fetch all user names once
    user_names = {}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name FROM users")
    for row in cursor.fetchall():
        user_names[row['user_id']] = row['name']
    conn.close()

    if not recent_expenses:
        msg = "📝 Пока нет недавних трат в этой поездке."
        keyboard = {"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]}
        if message_id: edit_message(chat_id, message_id, msg, reply_markup=keyboard)
        else: send_message(chat_id, msg, reply_markup=keyboard)
        return

    msg = f"📜 *Последние 10 трат ({trip.get('name')}):*\n\n"
    
    for exp in recent_expenses:
        date = datetime.fromtimestamp(exp['timestamp']).strftime('%d.%m %H:%M')
        payer_name = user_names.get(str(exp['payer_id']), 'Unknown')
        amount = exp['amount']
        desc = exp.get('description', 'Без описания')
        category_label = CATEGORIES.get(exp.get('category', 'OTHER'), exp.get('category', 'Другое'))
        
        if exp.get('category') != "REPAYMENT":
             msg += (
                f"*{date}* ({category_label})\n"
                f"👤 {payer_name} потратил: *{amount:,.0f} {curr}*\n"
                f"📝 {desc}\n\n"
            )
        else:
            repay_from_name = user_names.get(str(exp['payer_id']), 'Unknown')
            repay_to_id = list(exp['split'].keys())[0]
            repay_to_name = user_names.get(str(repay_to_id), 'Unknown')
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
        "📖 *Инструкция (v3.3 - SQLite):*\n\n"
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
    trip = db_get_trip(tid)
    if not trip: return # Should not happen if tid is valid

    # Fetch all user names once
    user_names = {}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name FROM users")
    for row in cursor.fetchall():
        user_names[row['user_id']] = row['name']
    conn.close()

    payer_name = user_names.get(str(payer_id), 'User')
    
    curr = trip.get('currency', 'THB')
    rate = trip.get('rate', 0)
    
    markup = {"inline_keyboard": [[{"text": "📊 Мой Баланс", "callback_data": "SHOW_MY_BALANCE"}]]}
    
    for uid in trip['members']:
        if str(uid) != str(payer_id):
            my_share = split_map.get(str(uid), 0)
            if my_share > 0:
                share_text = f"*{my_share:,.0f} {curr}*"
                if rate > 0: share_text += f" (~{my_share*rate:,.0f} RUB)"
                
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
    user = db_get_user(user_id)
    if not user:
        user = {"user_id": str(user_id), "name": user_name, "active_trip_id": None, "joined_trips": [], "state": "IDLE"}
        db_save_user(user_id, user)
    elif "joined_trips" not in user or user['joined_trips'] is None: # Handle old user objects without joined_trips
        old_tid = user.get('trip_id')
        user['active_trip_id'] = old_tid
        user['joined_trips'] = [old_tid] if old_tid else []
        if 'trip_id' in user: del user['trip_id']
        db_save_user(user_id, user)

    cmd = text.split()[0]
    args = text.split()[1:]

    # LEVEL 1: GLOBAL MENU
    if cmd == "/start":
        keyboard = {"inline_keyboard": [
            [{"text": "🆕 Создать поездку", "callback_data": "MENU_CREATE"}],
            [{"text": "🔗 Присоединиться", "callback_data": "MENU_JOIN"}],
            [{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]
        ]}
        
        tid = user.get('active_trip_id')
        status = ""
        if tid:
            trip = db_get_trip(tid)
            if trip:
                t_name = trip.get('name', 'Trip')
                keyboard["inline_keyboard"].insert(0, [{"text": f"⚙️ Меню: {t_name}", "callback_data": "OPEN_DASHBOARD"}])
                status = f"✅ Активная: *{t_name}*\n"
            
        msg = (
            "🌍 *ThaiSplitBot v3.3 (SQLite)*\n\n"
            "Главное меню. Выберите действие:\n"
            f"{status}"
        )
        send_message(chat_id, msg, reply_markup=keyboard)
        
    elif cmd == "/menu":
        send_trip_dashboard(chat_id, user_id)

    elif cmd == "/balance": 
        handle_callback(chat_id, user_id, None, "MENU_BALANCE", None) # Pass None for callback_query_id for commands
    
    elif cmd == "/me": 
        handle_callback(chat_id, user_id, None, "MENU_ME", None)
    
    elif cmd == "/trips": 
        handle_callback(chat_id, user_id, None, "MENU_TRIPS", None)
    
    elif cmd == "/help":
        send_help_menu(chat_id)

    elif cmd == "/note":
        tid = user.get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
        
        note_text = " ".join(args)
        if not note_text: return send_message(chat_id, "Пример: `/note Код 1234`", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        
        trip = db_get_trip(tid)
        if not trip: # Should not happen if tid is active
            user['active_trip_id'] = None
            user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
            db_save_user(user_id, user)
            return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})
        
        trip['notes'].append({"text": note_text, "author": user_name, "ts": time.time()})
        db_save_trip(trip)
        send_message(chat_id, "✅ Заметка сохранена!", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})

    elif cmd == "/notes":
        tid = user.get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
        
        trip = db_get_trip(tid)
        if not trip:
            user['active_trip_id'] = None
            user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
            db_save_user(user_id, user)
            return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

        notes = trip.get('notes', [])
        if not notes: return send_message(chat_id, "📝 Заметок пока нет.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        
        msg = "📝 *Важные заметки:*\n\n"
        for i, note in enumerate(notes):
            date = datetime.fromtimestamp(note['ts']).strftime('%d.%m')
            msg += f"{i+1}. {note['text']} _({note['author']}, {date})_\n"
            
        send_message(chat_id, msg, reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})

    elif cmd == "/roulette":
        tid = user.get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
        
        trip = db_get_trip(tid)
        if not trip:
            user['active_trip_id'] = None
            user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
            db_save_user(user_id, user)
            return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

        members = trip['members']
        if not members: return send_message(chat_id, "В поездке нет участников для рулетки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        
        victim_id = random.choice(members)
        victim_user = db_get_user(victim_id)
        victim_name = victim_user.get('name', 'Someone') if victim_user else 'Someone'
        
        # Сохраняем жертву и устанавливаем состояние ожидания
        victim_user['state'] = "WAITING_ROULETTE_AMOUNT"
        victim_user['roulette_trip_id'] = tid
        victim_user['roulette_payer_id'] = str(victim_id)
        db_save_user(victim_id, victim_user)

        send_message(chat_id, "🎲 *Крутим рулетку...*")
        time.sleep(1.5) # Simulate thinking
        
        # Уведомление всем, кто в чате рулетки
        send_message(chat_id, f"🎯 Сегодня платит: *{victim_name.upper()}*! 🎉", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        
        # Отдельное уведомление жертве с запросом суммы
        send_message(victim_id, f"🎉 Вы были выбраны рулеткой! Пожалуйста, введите сумму, которую вы оплатили:", reply_markup={"inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "OPEN_DASHBOARD"}]]}) # Added cancel button for roulette

    elif cmd == "/export":
        tid = user.get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
        
        trip = db_get_trip(tid)
        if not trip:
            user['active_trip_id'] = None
            user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
            db_save_user(user_id, user)
            return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

        curr = trip.get('currency', 'THB')
        csv_path = f"{DATA_DIR}/expenses.csv"
        
        # Fetch all expenses for the trip
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT payer_id, amount, description, category, timestamp FROM expenses WHERE trip_id = ? ORDER BY timestamp ASC", (tid,))
        expenses_raw = cursor.fetchall()
        conn.close()

        # Fetch all user names once
        user_names = {}
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, name FROM users")
        for row in cursor.fetchall():
            user_names[row['user_id']] = row['name']
        conn.close()

        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write(f"Date,Category,Payer,Amount ({curr}),Description\n")
            for exp_payer_id, exp_amount, exp_desc, exp_category, exp_timestamp in expenses_raw:
                payer_name = user_names.get(str(exp_payer_id), 'Unknown')
                date = datetime.fromtimestamp(exp_timestamp).strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"\"{date}\",\"{CATEGORIES.get(exp_category, exp_category)}\",\"{payer_name}\",\"{exp_amount}\",\"{exp_desc}\"\n")
        
        send_document(chat_id, csv_path)
        send_message(chat_id, "✅ Отчет экспортирован.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})

    elif cmd == "/setrate":
        tid = user.get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
        
        trip = db_get_trip(tid)
        if not trip:
            user['active_trip_id'] = None
            user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
            db_save_user(user_id, user)
            return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

        try:
            rate = float(args[0])
            trip['rate'] = rate
            db_save_trip(trip)
            curr = trip.get('currency', 'UNIT')
            send_message(chat_id, f"✅ Курс установлен: 1 {curr} = {rate} RUB.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        except (ValueError, IndexError):
            send_message(chat_id, "❌ Пример: `/setrate 2.8`", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})

def handle_text(chat_id, user_id, user_name, text):
    user = db_get_user(user_id)
    if not user: # If user not in DB, create and set state
        user = {"user_id": str(user_id), "name": user_name, "active_trip_id": None, "joined_trips": [], "state": "IDLE"}
        db_save_user(user_id, user)
    
    state = user.get('state', 'IDLE')
    
    # --- Roulette Amount State ---
    if state == "WAITING_ROULETTE_AMOUNT":
        try:
            amount = float(text)
            tid = user.get('roulette_trip_id')
            payer_id = user.get('roulette_payer_id')

            if not tid or not payer_id:
                send_message(chat_id, "⚠️ Произошла ошибка с рулеткой. Попробуйте снова.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
                user['state'] = "IDLE"
                db_save_user(user_id, user)
                return

            trip = db_get_trip(tid)
            if not trip: # Trip might have been deleted or corrupted
                user['state'] = "IDLE"
                user['roulette_trip_id'] = None
                user['roulette_payer_id'] = None
                db_save_user(user_id, user)
                return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})


            members = trip['members']
            if not members:
                send_message(chat_id, "В поездке нет участников для рулетки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
                user['state'] = "IDLE"
                user['roulette_trip_id'] = None
                user['roulette_payer_id'] = None
                db_save_user(user_id, user)
                return

            split_map = {member_id: amount / len(members) for member_id in members}

            new_exp = {
                "trip_id": tid,
                "payer_id": payer_id,
                "amount": amount,
                "desc": "Расход по рулетке",
                "category": "FUN",
                "split": split_map,
                "ts": time.time()
            }
            db_add_expense(new_exp)

            # Clear roulette state
            user['state'] = "IDLE"
            user['roulette_trip_id'] = None
            user['roulette_payer_id'] = None
            db_save_user(user_id, user)

            send_message(chat_id, f"✅ Расход по рулетке *{amount:,.0f}* добавлен!", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            notify_others(tid, payer_id, amount, "Расход по рулетке", "FUN", split_map)

        except ValueError:
            send_message(chat_id, "❌ Введите числовое значение суммы.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        return
    
    # --- Repayment Amount State ---
    if state == "WAITING_REPAYMENT_AMOUNT":
        try:
            amount = float(text)
            target_uid = user.get('repay_target')
            tid = user.get('active_trip_id')
            
            if not tid or not target_uid:
                send_message(chat_id, "⚠️ Произошла ошибка с возвратом долга. Попробуйте снова.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
                user['state'] = "IDLE"
                user['repay_target'] = None
                db_save_user(user_id, user)
                return

            new_exp = {
                "trip_id": tid,
                "payer_id": user_id,
                "amount": amount,
                "desc": "Возврат долга",
                "category": "REPAYMENT",
                "split": {target_uid: amount},
                "ts": time.time()
            }
            db_add_expense(new_exp)
            
            user['state'] = "IDLE"
            user['repay_target'] = None
            db_save_user(user_id, user)
            
            target_user = db_get_user(target_uid)
            target_name = target_user.get('name', 'User') if target_user else 'User'
            send_message(chat_id, f"✅ Вы вернули *{amount:,.0f}* пользователю *{target_name}*.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            send_message(target_uid, f"💸 *{user_name}* вернул вам долг: *{amount:,.0f}*")
            
        except ValueError: send_message(chat_id, "❌ Введите число.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    # --- Joining Trip State ---
    if state == "WAITING_TRIP_CODE":
        code = text.strip().upper()
        
        all_trips = db_get_all_trips()
        found_tid = None
        for tid, t_data in all_trips.items():
            if t_data.get('code') == code:
                found_tid = tid
                break
            
        if found_tid:
            user['active_trip_id'] = found_tid
            if found_tid not in user['joined_trips']:
                user['joined_trips'].append(found_tid)
            
            user['state'] = "IDLE"
            db_save_user(user_id, user)

            # Add user to trip members if not already there
            trip = db_get_trip(found_tid)
            if str(user_id) not in trip['members']:
                trip['members'].append(str(user_id))
                db_save_trip(trip)
                for member_id in trip['members']:
                    if str(member_id) != str(user_id):
                        send_message(member_id, f"👋 *{user_name}* присоединился к поездке *{trip.get('name')}*!")
            
            send_message(chat_id, f"✅ Вы присоединились! Активная поездка: `{trip.get('name')}`", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            time.sleep(1)
            send_trip_dashboard(chat_id, user_id) 
        else:
            send_message(chat_id, "❌ Неверный код.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
        return

    # --- Naming Trip State ---
    if state == "WAITING_TRIP_NAME":
        name = text.strip()
        code = generate_trip_code()
        tid = f"trip_{int(time.time())}"
        
        new_trip = {
            "trip_id": tid,
            "code": code,
            "creator_id": str(user_id),
            "name": name,
            "currency": "THB",
            "rate": 0.0,
            "members": [str(user_id)],
            "notes": []
        }
        db_save_trip(new_trip)
        
        user['active_trip_id'] = tid
        user['joined_trips'].append(tid)
        
        user['state'] = "WAITING_TRIP_CURRENCY"
        db_save_user(user_id, user)
        
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
            tid = user.get('active_trip_id')
            if tid:
                trip = db_get_trip(tid)
                if trip:
                    trip['rate'] = rate
                    db_save_trip(trip)
                    code = trip['code']
                    curr = trip['currency']
                    send_message(chat_id, f"✅ Поездка создана!\nВалюта: *{curr}* (Курс: {rate})\n🔑 Код: `{code}`", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
                    time.sleep(1)
                    send_trip_dashboard(chat_id, user_id)
            user['state'] = "IDLE"
            db_save_user(user_id, user)
        except ValueError:
            send_message(chat_id, "❌ Введите число (например 2.8):", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    # --- Custom Currency State ---
    if state == "WAITING_CUSTOM_CURRENCY":
        curr = text.strip().upper()[:3]
        tid = user.get('active_trip_id')
        if tid:
            trip = db_get_trip(tid)
            if trip:
                trip['currency'] = curr
                db_save_trip(trip)
        user['state'] = "WAITING_TRIP_RATE"
        db_save_user(user_id, user)
        send_message(chat_id, f"💱 Какой курс 1 {curr} к рублю?", reply_markup={"inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "OPEN_DASHBOARD"}]]}) # Added cancel button
        return

    # --- Custom Split State ---
    if state == "WAITING_CUSTOM_SPLIT":
        try:
            parts = text.split()
            amounts = [float(x) for x in parts]
            
            draft = db_get_draft(user.get('draft_id'))
            
            if not draft: 
                send_message(chat_id, "⚠️ Время вышло. Начните ввод расхода заново.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
                user['state'] = "IDLE"
                user['draft_id'] = None
                db_save_user(user_id, user)
                return
            
            trip = db_get_trip(draft['trip_id'])
            if not trip:
                user['state'] = "IDLE"
                user['draft_id'] = None
                db_save_user(user_id, user)
                db_delete_draft(draft['draft_id'])
                return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

            members = trip['members']
            if len(amounts) != len(members): return send_message(chat_id, f"❌ Нужно {len(members)} сумм, введено {len(amounts)}. Введите суммы через пробел.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            if abs(sum(amounts) - draft['amount']) > 0.01: # Allow small floating point deviation
                return send_message(chat_id, f"❌ Сумма не сходится. Ожидалось: {draft['amount']:,.0f}, получено: {sum(amounts):,.0f}. Повторите ввод.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
                 
            split_map = {m_id: amt for m_id, amt in zip(members, amounts)}
            
            new_exp = {
                "trip_id": draft['trip_id'],
                "payer_id": draft['payer_id'],
                "amount": draft['amount'],
                "description": draft['description'],
                "category": draft.get('category', 'OTHER'),
                "split": split_map,
                "ts": time.time()
            }
            db_add_expense(new_exp)
            db_delete_draft(draft['draft_id'])
            
            user['state'] = "IDLE"
            user['draft_id'] = None
            db_save_user(user_id, user)
            
            send_message(chat_id, f"✅ Сохранено: *{draft['amount']:,.0f}* ({CATEGORIES.get(draft.get('category'), draft.get('category'))})\n", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            notify_others(draft['trip_id'], draft['payer_id'], draft['amount'], draft['description'], draft.get('category'), split_map)
                    
        except ValueError: send_message(chat_id, "❌ Введите числа. Пример: `100 200 300`", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    # --- Expense Input (General) ---
    # This block only runs if no other state handler consumed the text
    if state == "IDLE": 
        try:
            parts = text.split()
            amount = float(parts[0])
            desc = " ".join(parts[1:]) if len(parts) > 1 else "Расход"
            
            tid = get_active_trip_id(user_id)
            if not tid: return send_message(chat_id, "Сначала создайте или вступите в поездку!", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
            
            trip = db_get_trip(tid)
            if not trip:
                user['active_trip_id'] = None
                user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
                db_save_user(user_id, user)
                return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

            draft_id = f"{user_id}_{int(time.time())}"
            
            members = trip['members']
            selected_members_dict = {uid: True for uid in members} # All members selected by default
            
            new_draft = {
                "draft_id": draft_id,
                "user_id": str(user_id),
                "amount": amount,
                "description": desc,
                "payer_id": str(user_id),
                "trip_id": tid,
                "selected_members": selected_members_dict,
                "category": "OTHER"
            }
            db_save_draft(draft_id, new_draft)
            user['draft_id'] = draft_id
            db_save_user(user_id, user) # Save draft_id to user state
            
            send_category_menu(chat_id, draft_id, curr)
            
        except ValueError: 
            send_message(chat_id, "Не понял ваш ввод. Введите сумму и описание для добавления расхода, или используйте `/help`.", reply_markup={"inline_keyboard": [[{"text": "📖 Инструкция", "callback_data": "SHOW_HELP"}]]})
            pass 
        return
    # Fallback for unexpected states, if text is received and not consumed by any state handler
    else:
        send_message(chat_id, "Не понял ваш ввод. Пожалуйста, следуйте инструкциям или вернитесь в меню.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        user['state'] = "IDLE" # Reset state to prevent further confusion
        db_save_user(user_id, user)
        return


def send_category_menu(chat_id, draft_id, curr, message_id=None):
    draft = db_get_draft(draft_id)
    if not draft:
        send_message(chat_id, "⚠️ Время для выбора категории вышло. Начните ввод расхода заново.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        # Reset user state
        user = db_get_user(chat_id) # chat_id is user_id here for DMs
        if user:
            user['state'] = 'IDLE'
            user['draft_id'] = None
            db_save_user(chat_id, user)
        return

    keyboard = []
    row = []
    for key, label in CATEGORIES.items():
        if key == "REPAYMENT": continue # Repayment is a special category, not chosen here
        row.append({"text": label, "callback_data": f"CAT|{draft_id}|{key}"}) # Use KEY, not label for consistency
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    
    amount = draft['amount']
    desc = draft['description']
    text = f"💸 *{amount:,.0f} {curr}* ({desc})\n🏷 Выберите категорию:"
    markup = {"inline_keyboard": keyboard}
    if message_id: edit_message(chat_id, message_id, text, reply_markup=markup)
    else: send_message(chat_id, text, reply_markup=markup)

def send_split_menu(chat_id, user_id, draft_id, message_id=None):
    draft = db_get_draft(draft_id)
    if not draft:
        send_message(chat_id, "⚠️ Время для разделения вышло. Начните ввод расхода заново.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        # Reset user state
        user = db_get_user(user_id)
        if user:
            user['state'] = 'IDLE'
            user['draft_id'] = None
            db_save_user(user_id, user)
        return

    trip = db_get_trip(draft['trip_id'])
    if not trip: # Trip might have been deleted or corrupted
        db_delete_draft(draft_id)
        user = db_get_user(user_id)
        if user: user['state'] = "IDLE"; user['draft_id'] = None; db_save_user(user_id, user)
        return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})


    curr = trip.get('currency', 'THB')
    
    # Fetch all user names once
    user_names = {}
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name FROM users")
    for row in cursor.fetchall():
        user_names[row['user_id']] = row['name']
    conn.close()

    amount = draft['amount']
    desc = draft['description']
    cat_key = draft.get('category', 'OTHER')
    cat_label = CATEGORIES.get(cat_key, cat_key)
    selected_members_dict = draft['selected_members']
    
    keyboard = []
    row = []
    for uid in trip['members']: # Iterate through actual trip members
        is_active = selected_members_dict.get(uid, False)
        u_name = user_names.get(uid, 'Unknown')
        status = "✅" if is_active else "⬜️"
        row.append({"text": f"{status} {u_name}", "callback_data": f"TOGGLE|{draft_id}|{uid}"})
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    
    count = sum(1 for v in selected_members_dict.values() if v)
    share = amount / count if count > 0 else 0
    keyboard.append([{"text": f"💾 Сохранить (по {share:,.0f})", "callback_data": f"CONFIRM|{draft_id}"}])
    keyboard.append([{"text": "✏️ Ввести вручную", "callback_data": f"CUSTOM|{draft_id}"}])
    keyboard.append([{"text": "❌ Отмена", "callback_data": f"CANCEL|{draft_id}"}])
    
    text = f"💸 *{amount:,.0f} {curr}* ({desc})\n🏷 {cat_label}\nКто участвует?"
    markup = {"inline_keyboard": keyboard}
    if message_id: edit_message(chat_id, message_id, text, reply_markup=markup)
    else: send_message(chat_id, text, reply_markup=markup)

def handle_callback(chat_id, user_id, message_id, data, callback_query_id):
    # Acknowledge callback immediately to prevent Telegram client resending
    answer_callback_query(callback_query_id)

    parts = data.split("|")
    cmd = parts[0]
    uid_str = str(user_id)
    
    user = db_get_user(user_id)
    if not user: # Should not happen, but for safety
        user = {"user_id": uid_str, "name": "User", "active_trip_id": None, "joined_trips": [], "state": "IDLE"}
        db_save_user(user_id, user)

    # --- Navigation ---
    if cmd == "OPEN_DASHBOARD":
        send_trip_dashboard(chat_id, user_id, message_id)
        user['state'] = "IDLE"
        user['draft_id'] = None
        db_save_user(user_id, user)
        return

    if cmd == "MENU_CREATE":
        user['state'] = "WAITING_TRIP_NAME"
        db_save_user(user_id, user)
        send_message(chat_id, "✏️ Введите название поездки (например: `Тай 2026`):", reply_markup={"inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "BACK_MAIN"}]]})
        return

    if cmd == "MENU_JOIN":
        user['state'] = "WAITING_TRIP_CODE"
        db_save_user(user_id, user)
        send_message(chat_id, "⌨️ Введите код поездки:", reply_markup={"inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "BACK_MAIN"}]]})
        return

    if cmd == "MENU_TRIPS":
        joined_trips_ids = user.get('joined_trips', [])
        
        keyboard = []
        active_tid = user.get('active_trip_id')
        
        all_trips = db_get_all_trips() # Get all trips to display names

        for tid in joined_trips_ids:
            t = all_trips.get(tid)
            if not t: continue
            mark = "✅ " if tid == active_tid else ""
            keyboard.append([{"text": f"{mark}{t.get('name')}", "callback_data": f"SWITCH_TRIP|{tid}"}])
        
        keyboard.append([{"text": "🔙 В главное меню", "callback_data": "BACK_MAIN"}]
        )
        edit_message(chat_id, message_id, "🗂 *Ваши поездки*:", reply_markup={"inline_keyboard": keyboard})
        return

    if cmd == "BACK_MAIN":
        handle_command(chat_id, user_id, user.get('name', 'User'), "/start")
        return

    if cmd == "SWITCH_TRIP":
        target_tid = parts[1]
        if target_tid in user.get('joined_trips', []):
            user['active_trip_id'] = target_tid
            db_save_user(user_id, user)
            send_trip_dashboard(chat_id, user_id, message_id)
        else:
            send_message(chat_id, "⚠️ Вы не являетесь участником этой поездки.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})
        return

    # --- Dashboard Actions ---
    if cmd == "MENU_BALANCE": 
        tid = user.get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
        
        trip = db_get_trip(tid)
        if not trip: # Trip might have been deleted or corrupted
            user['active_trip_id'] = None
            user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
            db_save_user(user_id, user)
            return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

        curr = trip.get('currency', 'THB')
        rate = trip.get('rate', 0)
        
        balances, total_trip_expenses, total_paid_by_member = calculate_balance(tid)
        
        # Fetch all user names once
        user_names = {}
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, name FROM users")
        for row in cursor.fetchall():
            user_names[row['user_id']] = row['name']
        conn.close()
        
        report = f"📊 *Баланс ({trip.get('name')}):*\n"
        
        # 1) Overall trip expenses
        total_trip_expenses_str = f"{total_trip_expenses:,.0f} {curr}"
        if rate > 0: total_trip_expenses_str += f" (~{total_trip_expenses*rate:,.0f} RUB)"
        report += f"💰 *Всего потрачено на поездку: {total_trip_expenses_str}*\n\n"
        
        # 2) Each member's paid amount and balance difference
        report += "👤 *Статистика участников:*\n"
        for uid in trip['members']:
            name = user_names.get(uid, uid)
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
        simplified_transactions = simplify_debts(balances, user_names)
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
        
        edit_message(chat_id, message_id, report, reply_markup=keyboard)
        return

    elif cmd == "MENU_SETTLE":
        tid = user.get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
        
        trip = db_get_trip(tid)
        if not trip:
            user['active_trip_id'] = None
            user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
            db_save_user(user_id, user)
            return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

        curr = trip.get('currency', 'THB')
        rate = trip.get('rate', 0)
        balances, _, _ = calculate_balance(tid) # Get only balances
        
        # Fetch all user names once
        user_names = {}
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, name FROM users")
        for row in cursor.fetchall():
            user_names[row['user_id']] = row['name']
        conn.close()
        
        simplified_transactions = simplify_debts(balances, user_names)
        
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
            from_id = next((uid for uid, name in user_names.items() if name == from_name), None)
            to_id = next((uid for uid, name in user_names.items() if name == to_name), None)

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
        tid = user.get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
        
        trip = db_get_trip(tid)
        if not trip:
            user['active_trip_id'] = None
            user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
            db_save_user(user_id, user)
            return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

        stats = get_my_stats(tid, uid_str)
        curr = trip.get('currency', 'THB')
        
        # Fetch all user names once
        user_names = {}
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, name FROM users")
        for row in cursor.fetchall():
            user_names[row['user_id']] = row['name']
        conn.close()

        report = f"👤 *Ваша статистика ({trip.get('name')}):*\n\n"
        
        report += f"💰 *Всего потрачено вами (ваша доля): {stats['total_share']:,.0f} {curr}*\n"
        if stats['cats']:
            report += "*Траты по категориям:*\n"
            for cat, amt in stats['cats'].items():
                report += f"  - {CATEGORIES.get(cat, cat)}: {amt:,.0f} {curr}\n"
        
        if stats['my_repayments']:
            report += "\n💸 *Вы вернули долги:*\n"
            for rep in stats['my_repayments']:
                date = datetime.fromtimestamp(rep['ts']).strftime('%d.%m %H:%M')
                target_name = user_names.get(str(rep['to']), 'Unknown')
                report += f"  - {date}: *{rep['amount']:,.0f} {curr}* -> {target_name}\n"

        if stats['received_repayments']:
            report += "\n💰 *Вам вернули долги:*\n"
            for rep in stats['received_repayments']:
                date = datetime.fromtimestamp(rep['ts']).strftime('%d.%m %H:%M')
                from_name = user_names.get(str(rep['from']), 'Unknown')
                report += f"  - {date}: *{rep['amount']:,.0f} {curr}* от {from_name}\n"
            
        send_message(chat_id, report, reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "MENU_REPAY":
        tid = user.get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
        
        trip = db_get_trip(tid)
        if not trip:
            user['active_trip_id'] = None
            user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
            db_save_user(user_id, user)
            return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

        keyboard = []
        
        # Fetch all user names once
        user_names = {}
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, name FROM users")
        for row in cursor.fetchall():
            user_names[row['user_id']] = row['name']
        conn.close()

        for m_uid in trip['members']:
            if str(m_uid) != uid_str:
                name = user_names.get(str(m_uid), 'User')
                keyboard.append([{"text": name, "callback_data": f"REPAY_TO|{m_uid}"}])
        keyboard.append([{"text": "❌ Отмена", "callback_data": "OPEN_DASHBOARD"}]
        )
        send_message(chat_id, "💸 Кому?", reply_markup={"inline_keyboard": keyboard})
        return

    if cmd == "MENU_ROULETTE":
        handle_command(chat_id, user_id, user.get('name', 'User'), "/roulette")
        return

    if cmd == "MENU_NOTES":
        handle_command(chat_id, user_id, user.get('name', 'User'), "/notes")
        return

    if cmd == "MENU_EXPORT":
        handle_command(chat_id, user_id, user.get('name', 'User'), "/export")
        return

    # --- Logic Handlers ---
    if cmd == "REPAY_TO":
        target_uid = parts[1]
        user['state'] = "WAITING_REPAYMENT_AMOUNT"
        user['repay_target'] = target_uid
        db_save_user(user_id, user)
        send_message(chat_id, "💸 Введите сумму:", reply_markup={"inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "CURR":
        curr_code = parts[1]
        tid = user.get('active_trip_id')
        if not tid: return send_message(chat_id, "Нет активной поездки.", reply_markup={"inline_keyboard": [[{"text": "🔙 К главному меню", "callback_data": "BACK_MAIN"}]]})
        
        trip = db_get_trip(tid)
        if not trip:
            user['active_trip_id'] = None
            user['joined_trips'] = [t for t in user['joined_trips'] if t != tid] # Remove invalid trip from joined_trips
            db_save_user(user_id, user)
            return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

        if curr_code == "CUSTOM":
            user['state'] = "WAITING_CUSTOM_CURRENCY"
            db_save_user(user_id, user)
            send_message(chat_id, "⌨️ Введите код валюты (например: `YEN`):", reply_markup={"inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "OPEN_DASHBOARD"}]]})
        else:
            trip['currency'] = curr_code
            db_save_trip(trip)
            user['state'] = "WAITING_TRIP_RATE"
            db_save_user(user_id, user)
            send_message(chat_id, f"💱 Какой курс 1 {curr_code} к рублю? (например: `2.8`):", reply_markup={"inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "SHOW_MY_BALANCE": # This is a legacy callback, handled by MENU_BALANCE now.
        send_trip_dashboard(chat_id, user_id, message_id)
        return

    if cmd == "SHOW_HELP": send_help_menu(chat_id); return

    if cmd == "CAT": 
        draft_id = parts[1]
        cat_key = parts[2] # Use key, not label
        draft = db_get_draft(draft_id)

        if draft:
            draft['category'] = cat_key
            db_save_draft(draft_id, draft)
            send_split_menu(chat_id, user_id, draft_id, message_id)
        else:
            send_message(chat_id, "⚠️ Время для выбора категории вышло. Начните ввод расхода заново.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            user['state'] = 'IDLE'
            user['draft_id'] = None
            db_save_user(user_id, user)
        return

    if cmd == "TOGGLE":
        target_uid = parts[2]
        draft_id = parts[1]
        draft = db_get_draft(draft_id)

        if draft:
            current_status = draft['selected_members'].get(target_uid, False)
            draft['selected_members'][target_uid] = not current_status
            db_save_draft(draft_id, draft)
            send_split_menu(chat_id, user_id, draft_id, message_id)
        else:
            send_message(chat_id, "⚠️ Время для разделения вышло. Начните ввод расхода заново.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            user['state'] = 'IDLE'
            user['draft_id'] = None
            db_save_user(user_id, user)
        return
            
    elif cmd == "CONFIRM":
        draft_id = parts[1]
        draft = db_get_draft(draft_id)
        if not draft: 
            send_message(chat_id, "⚠️ Время вышло. Начните ввод расхода заново.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            user['state'] = 'IDLE'
            user['draft_id'] = None
            db_save_user(user_id, user)
            return
        
        selected_members_dict = draft['selected_members']
        active_uids = [uid for uid, v in selected_members_dict.items() if v]
        if not active_uids: return edit_message(chat_id, message_id, "❌ Никто не выбран! Выберите хотя бы одного участника.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        
        amount = draft['amount']
        share = amount / len(active_uids)
        split_map = {uid: share for uid in active_uids}
        
        new_exp = {
            "trip_id": draft['trip_id'],
            "payer_id": draft['payer_id'],
            "amount": amount,
            "description": draft['description'],
            "category": draft.get('category', 'OTHER'),
            "split": split_map,
            "ts": time.time()
        }
        db_add_expense(new_exp)
        db_delete_draft(draft['draft_id'])
        
        user['state'] = "IDLE"
        user['draft_id'] = None
        db_save_user(user_id, user)

        edit_message(chat_id, message_id, f"✅ Сохранено: *{amount:,.0f}* ({CATEGORIES.get(draft.get('category'), draft.get('category'))})\nРазделено на {len(active_uids)} чел.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        notify_others(draft['trip_id'], draft['payer_id'], amount, draft['description'], draft.get('category'), split_map)

    elif cmd == "CUSTOM":
        draft_id = parts[1]
        draft = db_get_draft(draft_id)
        if not draft: 
            send_message(chat_id, "⚠️ Время вышло. Начните ввод расхода заново.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            user['state'] = 'IDLE'
            user['draft_id'] = None
            db_save_user(user_id, user)
            return
        
        user['state'] = "WAITING_CUSTOM_SPLIT"
        user['draft_id'] = draft_id # Make sure user's draft_id is correct
        db_save_user(user_id, user)
        
        trip = db_get_trip(draft['trip_id'])
        if not trip: # Trip might have been deleted or corrupted
            db_delete_draft(draft_id)
            user['state'] = "IDLE"; user['draft_id'] = None; db_save_user(user_id, user)
            return send_message(chat_id, "Активная поездка не найдена. Выберите другую или создайте новую.", reply_markup={"inline_keyboard": [[{"text": "🗂 Мои поездки", "callback_data": "MENU_TRIPS"}]]})

        # Fetch all user names once
        user_names = {}
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, name FROM users")
        for row in cursor.fetchall():
            user_names[row['user_id']] = row['name']
        conn.close()

        members_names = [user_names.get(m, 'User') for m in trip['members']]
        edit_message(chat_id, message_id, f"✏️ Введите суммы для:\n*{', '.join(members_names)}*\n\nЧерез пробел.", reply_markup={"inline_keyboard": [[{"text": "❌ Отмена", "callback_data": f"CANCEL|{draft_id}"}]]})


    elif cmd == "CANCEL":
        draft_id = parts[1]
        db_delete_draft(draft_id)
        user['state'] = "IDLE"
        user['draft_id'] = None
        db_save_user(user_id, user)
        edit_message(chat_id, message_id, "❌ Отменено.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})

def main():
    print("ThaiSplitBot v3.3 (SQLite) Started...")
    init_db()
    migrate_json_to_db() # Run migration once at startup

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
                
                # Ensure user exists in DB
                if not db_get_user(user_id):
                    new_user = {"user_id": str(user_id), "name": name, "active_trip_id": None, "joined_trips": [], "state": "IDLE"}
                    db_save_user(user_id, new_user)

                if text.startswith("/"): handle_command(chat_id, user_id, name, text)
                else: handle_text(chat_id, user_id, name, text)
            elif "callback_query" in u:
                cb = u["callback_query"]
                handle_callback(cb["message"]["chat"]["id"], cb["from"]["id"], cb["message"]["message_id"], cb["data"], cb["id"])
        time.sleep(1)

if __name__ == "__main__":
    main()