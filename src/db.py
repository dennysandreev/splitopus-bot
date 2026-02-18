import sqlite3
import json
import os
import time
import random
import string

DB_PATH = os.path.join("data", "splitopus.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

def get_connection():
    """Создает подключение к базе данных"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row # Позволяет обращаться к колонкам по имени
    return conn

def init_db():
    """Создает таблицы, если их нет"""
    if not os.path.exists("data"):
        os.makedirs("data")
        
    with open(SCHEMA_PATH, 'r') as f:
        schema = f.read()
        
    conn = get_connection()
    conn.executescript(schema)
    conn.commit()
    conn.close()

# --- Users ---

def upsert_user(user_id, name):
    """Добавляет или обновляет пользователя"""
    conn = get_connection()
    conn.execute(
        "INSERT INTO users (id, name) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET name=?",
        (str(user_id), name, name)
    )
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (str(user_id),)).fetchone()
    conn.close()
    return dict(user) if user else None

def update_user_state(user_id, state):
    conn = get_connection()
    conn.execute("UPDATE users SET state = ? WHERE id = ?", (state, str(user_id)))
    conn.commit()
    conn.close()

def set_user_active_trip(user_id, trip_id):
    conn = get_connection()
    conn.execute("UPDATE users SET active_trip_id = ? WHERE id = ?", (trip_id, str(user_id)))
    conn.commit()
    conn.close()
    
def link_users(child_id, parent_id):
    conn = get_connection()
    conn.execute("UPDATE users SET linked_to = ? WHERE id = ?", (str(parent_id), str(child_id)))
    conn.commit()
    conn.close()

def update_user_temp_data(user_id, temp_data):
    conn = get_connection()
    curr = conn.execute("SELECT temp_data_json FROM users WHERE id = ?", (str(user_id),)).fetchone()
    current_data = json.loads(curr['temp_data_json']) if curr and curr['temp_data_json'] else {}
    current_data.update(temp_data)
    conn.execute("UPDATE users SET temp_data_json = ? WHERE id = ?", (json.dumps(current_data), str(user_id)))
    conn.commit()
    conn.close()

def get_user_temp_data(user_id):
    conn = get_connection()
    curr = conn.execute("SELECT temp_data_json FROM users WHERE id = ?", (str(user_id),)).fetchone()
    conn.close()
    return json.loads(curr['temp_data_json']) if curr and curr['temp_data_json'] else {}

def get_all_users_as_dict():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    users = {}
    for r in rows:
        d = dict(r)
        temp = json.loads(d['temp_data_json']) if d['temp_data_json'] else {}
        d.update(temp)
        users[d['id']] = d
    return users

def get_linked_names(master_id):
    conn = get_connection()
    mid = str(master_id)
    master = conn.execute("SELECT name FROM users WHERE id = ?", (mid,)).fetchone()
    master_name = master['name'] if master else 'Unknown'
    children = conn.execute("SELECT name FROM users WHERE linked_to = ?", (mid,)).fetchall()
    child_names = [c['name'] for c in children]
    all_names = [master_name] + child_names
    conn.close()
    return " + ".join(all_names)

# --- Trips ---

def generate_trip_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def create_trip(trip_id, code, creator_id, name):
    conn = get_connection()
    conn.execute(
        "INSERT INTO trips (id, code, creator_id, name) VALUES (?, ?, ?, ?)",
        (trip_id, code, str(creator_id), name)
    )
    # Создатель сразу становится участником
    conn.execute("INSERT INTO trip_members (trip_id, user_id) VALUES (?, ?)", (trip_id, str(creator_id)))
    conn.commit()
    conn.close()

def get_trip(trip_id):
    conn = get_connection()
    trip = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    if not trip:
        conn.close()
        return None
    
    # Получаем участников
    members = conn.execute("SELECT user_id FROM trip_members WHERE trip_id = ?", (trip_id,)).fetchall()
    member_ids = [m['user_id'] for m in members]
    
    # Получаем расходы
    expenses_rows = conn.execute("SELECT * FROM expenses WHERE trip_id = ?", (trip_id,)).fetchall()
    expenses = []
    for row in expenses_rows:
        exp = dict(row)
        exp['split'] = json.loads(row['split_json']) # Декодируем JSON обратно в словарь
        exp['ts'] = row['created_at'] # Для совместимости с логикой бота
        del exp['split_json']
        expenses.append(exp)
        
    # Получаем заметки
    notes = conn.execute("SELECT * FROM notes WHERE trip_id = ?", (trip_id,)).fetchall()
    
    trip_dict = dict(trip)
    trip_dict['members'] = member_ids
    trip_dict['expenses'] = expenses
    trip_dict['notes'] = [dict(n) for n in notes]
    
    conn.close()
    return trip_dict

def get_trip_by_code(code):
    conn = get_connection()
    trip = conn.execute("SELECT id FROM trips WHERE code = ?", (code,)).fetchone()
    conn.close()
    return trip['id'] if trip else None

def add_member_to_trip(trip_id, user_id):
    conn = get_connection()
    try:
        conn.execute("INSERT INTO trip_members (trip_id, user_id) VALUES (?, ?)", (trip_id, str(user_id)))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # Уже участник
    conn.close()

def get_user_trips(user_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT t.id, t.name FROM trips t JOIN trip_members tm ON t.id = tm.trip_id WHERE tm.user_id = ?",
        (str(user_id),)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_trip_rate(trip_id, rate):
    conn = get_connection()
    conn.execute("UPDATE trips SET rate = ? WHERE id = ?", (rate, trip_id))
    conn.commit()
    conn.close()
    
def update_trip_currency(trip_id, currency):
    conn = get_connection()
    conn.execute("UPDATE trips SET currency = ? WHERE id = ?", (currency, trip_id))
    conn.commit()
    conn.close()

def get_all_trips_as_dict():
    conn = get_connection()
    rows = conn.execute("SELECT id FROM trips").fetchall()
    conn.close()
    
    trips = {}
    for r in rows:
        t = get_trip(r['id'])
        if t:
            trips[r['id']] = t
    return trips

# --- Expenses ---

def add_expense(trip_id, payer_id, amount, desc, category, split_map):
    conn = get_connection()
    conn.execute(
        "INSERT INTO expenses (trip_id, payer_id, amount, description, category, split_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (trip_id, str(payer_id), amount, desc, category, json.dumps(split_map), int(time.time()))
    )
    conn.commit()
    conn.close()

# --- Notes ---

def add_note(trip_id, author_name, text):
    conn = get_connection()
    conn.execute(
        "INSERT INTO notes (trip_id, author_name, text, created_at) VALUES (?, ?, ?, ?)",
        (trip_id, author_name, text, int(time.time()))
    )
    conn.commit()
    conn.close()

# --- Drafts ---

def save_draft(draft_id, data):
    conn = get_connection()
    # data - это словарь. Разложим его по колонкам
    conn.execute(
        "INSERT OR REPLACE INTO drafts (id, user_id, trip_id, amount, description, category, selected_users_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            draft_id, 
            data.get('payer'), 
            data.get('trip_id'), 
            data.get('amount'), 
            data.get('desc'), 
            data.get('category'), 
            json.dumps(data.get('selected', {})), 
            int(time.time())
        )
    )
    conn.commit()
    conn.close()

def get_draft(draft_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    conn.close()
    
    if not row: return None
    
    # Собираем обратно в словарь, как привык бот
    d = dict(row)
    return {
        "payer": d['user_id'],
        "trip_id": d['trip_id'],
        "amount": d['amount'],
        "desc": d['description'],
        "category": d['category'],
        "selected": json.loads(d['selected_users_json']) if d['selected_users_json'] else {}
    }

def delete_draft(draft_id):
    conn = get_connection()
    conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
    conn.commit()
    conn.close()

# --- Menu ID ---
def set_user_menu_id(user_id, msg_id):
    conn = get_connection()
    conn.execute("UPDATE users SET menu_msg_id = ? WHERE id = ?", (msg_id, str(user_id)))
    conn.commit()
    conn.close()
