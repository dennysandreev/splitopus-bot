import json
import os
import time
from . import db

# --- Initialization ---
db.init_db()

# --- Constants ---
DATA_DIR = "data"
USERS_FILE = os.path.join(DATA_DIR, "users.json")
TRIPS_FILE = os.path.join(DATA_DIR, "trips.json")
DRAFTS_FILE = os.path.join(DATA_DIR, "drafts.json")

# --- User Operations ---

def get_user(user_id):
    u = db.get_user(user_id)
    if u:
        temp = db.get_user_temp_data(user_id)
        u.update(temp)
    return u

def update_user_state(user_id, state, **kwargs):
    name = kwargs.get('user_name', 'Unknown')
    existing = db.get_user(user_id)
    if not existing:
        db.upsert_user(user_id, name)
    
    db.update_user_state(user_id, state)
    
    temp_kwargs = {k: v for k, v in kwargs.items() if k != 'user_name'}
    if temp_kwargs:
        db.update_user_temp_data(user_id, temp_kwargs)

def get_active_trip_id(user_id):
    u = db.get_user(user_id)
    return u['active_trip_id'] if u else None

def set_user_active_trip(user_id, trip_id):
    db.set_user_active_trip(user_id, trip_id)

def link_users(child_id, parent_id):
    db.link_users(child_id, parent_id)
    return True

def get_user_menu_id(user_id):
    u = db.get_user(user_id)
    return u['menu_msg_id'] if u else None

def set_user_menu_id(user_id, msg_id):
    db.set_user_menu_id(user_id, msg_id)
    
def get_linked_names(master_id):
    return db.get_linked_names(master_id)

def get_all_users_as_dict():
    return db.get_all_users_as_dict()

# --- Trip Operations ---

def create_trip(creator_id, name):
    tid = f"trip_{int(time.time())}"
    code = db.generate_trip_code()
    db.create_trip(tid, code, creator_id, name)
    db.set_user_active_trip(creator_id, tid)
    return tid, code

def get_trip(trip_id):
    return db.get_trip(trip_id)

def get_trip_by_code(code):
    return db.get_trip_by_code(code)

def add_member_to_trip(trip_id, user_id):
    db.add_member_to_trip(trip_id, user_id)

def get_user_trips(user_id):
    return db.get_user_trips(user_id)

def update_trip_rate(trip_id, rate):
    db.update_trip_rate(trip_id, rate)
    
def update_trip_currency(trip_id, currency):
    db.update_trip_currency(trip_id, currency)

# --- Expense & Note Operations ---

def add_expense(trip_id, payer_id, amount, desc, category, split_map):
    db.add_expense(trip_id, payer_id, amount, desc, category, split_map)

def add_note(trip_id, author_name, text):
    db.add_note(trip_id, author_name, text)

# --- Draft Operations ---

def save_draft(draft_id, data):
    db.save_draft(draft_id, data)

def get_draft(draft_id):
    return db.get_draft(draft_id)

def delete_draft(draft_id):
    db.delete_draft(draft_id)

# --- Legacy Compat ---

def load_json(path):
    if path == USERS_FILE:
        return db.get_all_users_as_dict()
    return {}

def save_json(path, data):
    pass 
