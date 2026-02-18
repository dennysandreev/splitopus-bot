import json
import os
import random
import string
import time

# --- Configuration & Constants ---
DATA_DIR = "data"
USERS_FILE = os.path.join(DATA_DIR, "users.json")
TRIPS_FILE = os.path.join(DATA_DIR, "trips.json")
DRAFTS_FILE = os.path.join(DATA_DIR, "drafts.json")

# Ensure data directory exists
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# --- Base JSON Operations ---
def load_json(path):
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# --- User Operations ---
def get_user(user_id):
    users = load_json(USERS_FILE)
    return users.get(str(user_id))

def get_active_trip_id(user_id):
    user = get_user(user_id)
    return user.get('active_trip_id') if user else None

def update_user_state(user_id, state, **kwargs):
    users = load_json(USERS_FILE)
    uid_str = str(user_id)
    if uid_str not in users:
        users[uid_str] = {"state": state}
    else:
        users[uid_str]['state'] = state
    
    # Merge additional fields into user data
    for k, v in kwargs.items():
        users[uid_str][k] = v
        
    save_json(USERS_FILE, users)

# --- Trip Operations ---
def generate_trip_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def get_trip(trip_id):
    trips = load_json(TRIPS_FILE)
    return trips.get(trip_id)

def create_trip(creator_id, name):
    trips = load_json(TRIPS_FILE)
    users = load_json(USERS_FILE)
    
    code = generate_trip_code()
    tid = f"trip_{int(time.time())}"
    uid_str = str(creator_id)
    
    trips[tid] = {
        "code": code,
        "creator": uid_str,
        "members": [uid_str],
        "expenses": [],
        "name": name,
        "rate": 0,
        "currency": "THB",
        "notes": []
    }
    
    # Update user active trip
    if uid_str not in users: users[uid_str] = {}
    users[uid_str]['active_trip_id'] = tid
    if 'joined_trips' not in users[uid_str]: users[uid_str]['joined_trips'] = []
    if tid not in users[uid_str]['joined_trips']: users[uid_str]['joined_trips'].append(tid)
    
    save_json(TRIPS_FILE, trips)
    save_json(USERS_FILE, users)
    return tid, code

# --- Draft Operations ---
def save_draft(draft_id, data):
    drafts = load_json(DRAFTS_FILE)
    drafts[draft_id] = data
    save_json(DRAFTS_FILE, drafts)

def get_draft(draft_id):
    drafts = load_json(DRAFTS_FILE)
    return drafts.get(draft_id)

def delete_draft(draft_id):
    drafts = load_json(DRAFTS_FILE)
    if draft_id in drafts:
        del drafts[draft_id]
        save_json(DRAFTS_FILE, drafts)

# --- Linkage / Family Operations ---
def link_users(child_id, parent_id):
    """
    Links child_id to parent_id.
    child_id will effectively use parent_id's balance.
    """
    users = load_json(USERS_FILE)
    cid, pid = str(child_id), str(parent_id)
    
    if cid in users and pid in users:
        users[cid]['linked_to'] = pid
        save_json(USERS_FILE, users)
        return True
    return False

def get_master_id(user_id):
    """
    Returns the ID of the wallet owner.
    If user is linked, returns their parent's ID.
    If user is independent, returns their own ID.
    """
    users = load_json(USERS_FILE)
    uid = str(user_id)
    user = users.get(uid)
    
    if user and user.get('linked_to'):
        return user['linked_to']
    return uid

def get_linked_names(master_id):
    """Returns a string like 'Denis + Anya' or just 'Denis'"""
    users = load_json(USERS_FILE)
    mid = str(master_id)
    
    names = [users.get(mid, {}).get('name', 'Unknown')]
    
    # Find children
    for uid, u in users.items():
        if u.get('linked_to') == mid:
            names.append(u.get('name', 'Partner'))
            
    return " + ".join(names)

