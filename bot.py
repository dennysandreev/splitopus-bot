import time
import logging
import random
import os
from datetime import datetime

# Import modules from src
from src import data, logic
from src.telegram import TelegramClient

# --- Configuration ---
# Load environment variables from .env file (look in same dir as script)
script_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(script_dir, ".env")

if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                key, value = line.strip().split("=", 1)
                os.environ[key] = value

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("Error: BOT_TOKEN not found in environment variables or .env file.")
    exit(1)

# --- Logging Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Initialize Client ---
bot = TelegramClient(TOKEN)

# --- Helper Functions ---
def get_link_map():
    users = data.load_json(data.USERS_FILE)
    return {uid: u['linked_to'] for uid, u in users.items() if u.get('linked_to')}

def refresh_menu_msg(chat_id, user_id, text, reply_markup):
    """
    Deletes old menu message and sends a new one to keep it at the bottom.
    """
    old_msg_id = data.get_user_menu_id(user_id)
    if old_msg_id:
        try:
            bot.delete_message(chat_id, old_msg_id)
        except:
            pass # Message might be too old or already deleted
            
    resp = bot.send_message(chat_id, text, reply_markup=reply_markup)
    if resp and 'result' in resp:
        new_msg_id = resp['result']['message_id']
        data.set_user_menu_id(user_id, new_msg_id)

def notify_others(tid, payer_id, amount, desc, category, split_map):
    trip = data.get_trip(tid)
    if not trip: return

    link_map = get_link_map()
    users_db = data.load_json(data.USERS_FILE)
    
    payer_user = users_db.get(str(payer_id))
    payer_name = payer_user.get('name', 'User') if payer_user else 'User'
    
    curr = trip.get('currency', 'THB')
    rate = trip.get('rate', 0)
    
    markup = {"inline_keyboard": [[{"text": "📊 Мой Баланс", "callback_data": "SHOW_MY_BALANCE"}]]}
    
    members = trip['members']
    masters = set(logic.get_master(m, link_map) for m in members)
    payer_master = logic.get_master(payer_id, link_map)
    
    for mid in masters:
        if mid != payer_master:
            my_share = split_map.get(mid, 0)
            if my_share > 0:
                share_text = f"*{my_share:.0f} {curr}*"
                if rate > 0: share_text += f" (~{my_share*rate:.0f} RUB)"
                
                title = "🧾 Новый Расход"
                if category == "REPAYMENT": title = "💸 Возврат Долга"
                
                msg = (
                    f"{title}\n"
                    f"👤 *{payer_name}* -> *{amount:,.0f} {curr}*\n"
                    f"📝 {desc}\n"
                    f"📉 Ваша доля: {share_text}"
                )
                bot.send_message(mid, msg, reply_markup=markup)

def send_trip_dashboard(chat_id, user_id, message_id=None):
    uid_str = str(user_id)
    tid = data.get_active_trip_id(uid_str)
    trip = data.get_trip(tid)
    
    if not tid or not trip:
        return handle_command(chat_id, user_id, "User", "/start") 
        
    name = trip.get('name', 'Trip')
    code = trip.get('code')
    
    link_map = get_link_map()
    master_id = logic.get_master(user_id, link_map)
    is_linked = (master_id != uid_str)
    
    role_info = ""
    if is_linked:
        master_name = data.load_json(data.USERS_FILE).get(master_id, {}).get('name', 'Master')
        role_info = f"\n🔗 Вы привязаны к: *{master_name}*"
    
    msg = (
        f"🌴 *Поездка: {name}*\n"
        f"🔑 Код: `{code}`{role_info}\n\n"
        "✍️ *Чтобы добавить трату:*\n"
        "Просто напишите сумму и название в этот чат.\n"
        "Пример: `500 Обед` или `200 Такси`\n\n"
        "👇 *Инструменты:*"
    )
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "📊 Баланс", "callback_data": "MENU_BALANCE"}, {"text": "👤 Моя статистика", "callback_data": "MENU_ME"}],
            [{"text": "💸 Вернуть долг", "callback_data": "MENU_REPAY"}, {"text": "🎲 Рулетка", "callback_data": "MENU_ROULETTE"}],
            [{"text": "📜 История трат", "callback_data": "MENU_ALL_EXPENSES"}],
            [{"text": "📝 Заметки", "callback_data": "MENU_NOTES"}, {"text": "💾 Скачать отчет", "callback_data": "MENU_EXPORT"}],
            [{"text": "🔙 Назад к списку", "callback_data": "MENU_TRIPS"}, {"text": "📖 Инструкция", "callback_data": "SHOW_HELP"}],
        ]
    }
    
    if message_id:
        # Navigation inside menu: Edit existing
        bot.edit_message(chat_id, message_id, msg, reply_markup=keyboard)
    else:
        # Fresh menu: Delete old, send new
        refresh_menu_msg(chat_id, user_id, msg, reply_markup=keyboard)

def send_category_menu(chat_id, draft_id, curr, message_id=None):
    keyboard = []
    row = []
    for key, label in logic.CATEGORIES.items():
        if key == "REPAYMENT": continue
        row.append({"text": label, "callback_data": f"CAT|{draft_id}|{label}"})
        if len(row) == 2: keyboard.append(row); row = []
    if row: keyboard.append(row)
    
    draft = data.get_draft(draft_id)
    if not draft: return

    amount = draft['amount']
    desc = draft['desc']
    text = f"💸 *{amount} {curr}* ({desc})\n🏷 Выберите категорию:"
    markup = {"inline_keyboard": keyboard}
    
    # Category menu always replaces/refreshes main menu or is a fresh message
    # If triggered by text input, message_id is None -> send fresh
    if message_id: 
        bot.edit_message(chat_id, message_id, text, reply_markup=markup)
    else:
        # We treat this as a temporary menu overlay. 
        # Ideally, we should also track this ID to delete it if cancelled.
        # For now, let's just send it.
        # Alternatively: Replace the Main Menu with this!
        refresh_menu_msg(chat_id, draft['payer'], text, reply_markup=markup)

def send_split_menu(chat_id, draft_id, message_id=None):
    draft = data.get_draft(draft_id)
    if not draft: return
    
    trip = data.get_trip(draft['trip_id'])
    curr = trip.get('currency', 'THB')
    
    amount = draft['amount']
    desc = draft['desc']
    cat = draft.get('category', '')
    selected = draft['selected']
    
    keyboard = []
    row = []
    
    users_db = data.load_json(data.USERS_FILE)
    members = trip['members']
    masters = set()
    for m in members:
        master_id = users_db.get(str(m), {}).get('linked_to') or str(m)
        masters.add(master_id)
        
    for mid in masters:
        display_name = data.get_linked_names(mid)
        is_active = selected.get(mid, True)
        status = "✅" if is_active else "⬜️"
        keyboard.append([{"text": f"{status} {display_name}", "callback_data": f"TOGGLE|{draft_id}|{mid}"}])
            
    count = sum(1 for v in selected.values() if v)
    share = amount / count if count > 0 else 0
    
    keyboard.append([{"text": f"💾 Сохранить (по {share:.0f})", "callback_data": f"CONFIRM|{draft_id}"}])
    keyboard.append([{"text": "✏️ Ввести вручную", "callback_data": f"CUSTOM|{draft_id}"}])
    keyboard.append([{"text": "❌ Отмена", "callback_data": f"CANCEL|{draft_id}"}])
    
    text = f"💸 *{amount} {curr}* ({desc})\n🏷 {cat}\nКто участвует (семьями)?"
    markup = {"inline_keyboard": keyboard}
    
    if message_id: bot.edit_message(chat_id, message_id, text, reply_markup=markup)
    else: bot.send_message(chat_id, text, reply_markup=markup)

def send_all_expenses_list(chat_id, user_id, message_id=None, page=0):
    uid_str = str(user_id)
    tid = data.get_active_trip_id(uid_str)
    trip = data.get_trip(tid)
    if not trip: return

    expenses = sorted(trip.get('expenses', []), key=lambda x: x['ts'], reverse=True)
    curr = trip.get('currency', 'THB')
    users_db = data.load_json(data.USERS_FILE)
    names = {uid: users_db.get(uid, {}).get('name', 'Unknown') for uid in trip['members']}

    PAGE_SIZE = 10
    total_pages = (len(expenses) + PAGE_SIZE - 1) // PAGE_SIZE
    start_idx = page * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, len(expenses))
    
    if not expenses:
        msg = "📝 В этой поездке пока нет трат."
        keyboard = {"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]}
        if message_id: bot.edit_message(chat_id, message_id, msg, reply_markup=keyboard)
        else: bot.send_message(chat_id, msg, reply_markup=keyboard)
        return

    msg = f"🧾 *Все траты ({trip.get('name')}):*\n\n"
    for i in range(start_idx, end_idx):
        exp = expenses[i]
        date = datetime.fromtimestamp(exp['ts']).strftime('%d.%m %H:%M')
        payer_name = names.get(str(exp['payer_id']), 'Unknown')
        amount = exp['amount']
        desc = exp.get('desc', 'Без описания')
        category_label = logic.CATEGORIES.get(exp.get('category', 'OTHER'), exp.get('category', 'Другое'))
        
        if exp.get('category') != "REPAYMENT":
             msg += (f"*{date}* ({category_label})\n"
                     f"👤 {payer_name} потратил: *{amount:,.0f} {curr}*\n"
                     f"📝 {desc}\n\n")
        else:
            repay_to_id = list(exp['split'].keys())[0]
            repay_to_name = names.get(str(repay_to_id), 'Unknown')
            msg += (f"*{date}* ({category_label})\n"
                    f"💸 {payer_name} вернул {repay_to_name}: *{amount:,.0f} {curr}*\n\n")

    keyboard_rows = []
    nav_row = []
    if page > 0: nav_row.append({"text": "◀️ Назад", "callback_data": f"ALL_EXPENSES_PAGE|{page-1}"})
    if page < total_pages - 1: nav_row.append({"text": "Вперед ▶️", "callback_data": f"ALL_EXPENSES_PAGE|{page+1}"})
    if nav_row: keyboard_rows.append(nav_row)
    keyboard_rows.append([{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}])
    
    if message_id: bot.edit_message(chat_id, message_id, msg, reply_markup={"inline_keyboard": keyboard_rows})
    else: bot.send_message(chat_id, msg, reply_markup={"inline_keyboard": keyboard_rows})

# --- Handlers ---

def handle_command(chat_id, user_id, user_name, text):
    uid_str = str(user_id)
    users = data.load_json(data.USERS_FILE)
    
    if uid_str not in users:
        users[uid_str] = {"name": user_name, "active_trip_id": None, "joined_trips": [], "state": "IDLE"}
        data.save_json(data.USERS_FILE, users)
    
    cmd = text.split()[0]
    args = text.split()[1:]

    if cmd == "/start":
        data.update_user_state(user_id, "IDLE") # Reset state on start
        
        keyboard = {"inline_keyboard": [
            [{"text": "🆕 Создать новую поездку", "callback_data": "MENU_CREATE"}],
            [{"text": "🔗 Присоединиться по коду", "callback_data": "MENU_JOIN"}],
            [{"text": "📂 Мои поездки", "callback_data": "MENU_TRIPS"}]
        ]}
        
        tid = users[uid_str].get('active_trip_id')
        active_trip_info = ""
        
        if tid:
            trip = data.get_trip(tid)
            if trip:
                t_name = trip.get('name', 'Trip')
                keyboard["inline_keyboard"].insert(0, [{"text": f"🚀 Меню: {t_name}", "callback_data": "OPEN_DASHBOARD"}])
                active_trip_info = f"\n\n🔥 Активная поездка: *{t_name}*"
            
        msg = (
            "🐙 *Привет! Я Splitopus.*\n\n"
            "Я помогаю вести учет общих расходов в путешествиях и компаниях. "
            "Больше не нужно спорить, кто за что платил — я всё посчитаю сам!\n\n"
            "👇 *Что будем делать?*"
            f"{active_trip_info}"
        )
        refresh_menu_msg(chat_id, user_id, msg, reply_markup=keyboard)

    elif cmd == "/menu":
        send_trip_dashboard(chat_id, user_id)
        
    elif cmd == "/setrate":
        tid = users[uid_str].get('active_trip_id')
        if not tid: return bot.send_message(chat_id, "Нет активной поездки.")
        try:
            rate = float(args[0].replace(',', '.'))
            trips = data.load_json(data.TRIPS_FILE)
            trips[tid]['rate'] = rate
            data.save_json(data.TRIPS_FILE, trips)
            curr = trips[tid].get('currency', 'UNIT')
            bot.send_message(chat_id, f"✅ Курс установлен: 1 {curr} = {rate} RUB.", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        except:
            bot.send_message(chat_id, "❌ Пример: `/setrate 2.8`")

def handle_text(chat_id, user_id, user_name, text):
    user = data.get_user(user_id)
    state = user.get('state', 'IDLE')
    uid_str = str(user_id)

    # --- Trip Creation Flow ---
    if state == "WAITING_TRIP_NAME":
        name = text.strip()
        tid, code = data.create_trip(user_id, name)
        data.update_user_state(user_id, "WAITING_TRIP_CURRENCY")
        
        keyboard = []
        row = []
        for code, label in logic.CURRENCIES.items():
            row.append({"text": label, "callback_data": f"CURR|{code}"})
            if len(row) == 2: keyboard.append(row); row = []
        if row: keyboard.append(row)
        
        refresh_menu_msg(chat_id, user_id, f"💱 Выберите валюту для поездки *{name}*:", reply_markup={"inline_keyboard": keyboard})
        return

    # --- Joining Trip ---
    if state == "WAITING_TRIP_CODE":
        code = text.strip().upper()
        trips = data.load_json(data.TRIPS_FILE)
        
        found_tid = None
        for tid, t in trips.items():
            if t['code'] == code: found_tid = tid; break
            
        if found_tid:
            data.update_user_state(user_id, "WAITING_ROLE_SELECTION", temp_trip_id=found_tid)
            trip_name = trips[found_tid].get('name', 'Trip')
            msg = (
                f"🎉 Код принят! Поездка: *{trip_name}*\n\n"
                "Как вы хотите присоединиться?\n"
                "👤 **Я самостоятельный участник** — буду платить за себя (или за семью).\n"
                "💞 **Присоединиться к партнеру** — у нас общий бюджет с кем-то, кто уже здесь."
            )
            keyboard = {"inline_keyboard": [
                [{"text": "👤 Я самостоятельный участник", "callback_data": "JOIN_SOLO"}],
                [{"text": "💞 Присоединиться к партнеру", "callback_data": "JOIN_LINKED"}]
            ]}
            refresh_menu_msg(chat_id, user_id, msg, reply_markup=keyboard)
        else:
            refresh_menu_msg(chat_id, user_id, "❌ Неверный код. Попробуйте еще раз:", reply_markup={"inline_keyboard": [[{"text": "🔙 Отмена", "callback_data": "BACK_MAIN"}]]})
        return

    # --- Repayment Amount ---
    if state == "WAITING_REPAYMENT_AMOUNT":
        try:
            amount = float(text)
            target_uid = user.get('repay_target')
            tid = user.get('active_trip_id')
            trips = data.load_json(data.TRIPS_FILE)
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
            data.save_json(data.TRIPS_FILE, trips)
            data.update_user_state(user_id, "IDLE")
            target_user = data.get_user(target_uid)
            target_name = target_user.get('name', 'User') if target_user else 'User'
            
            # Send notification as new message, then refresh menu
            bot.send_message(chat_id, f"✅ Вы вернули *{amount}* пользователю *{target_name}*.")
            bot.send_message(target_uid, f"💸 *{user_name}* вернул вам долг: *{amount}*")
            send_trip_dashboard(chat_id, user_id) # Refresh
            
        except ValueError: bot.send_message(chat_id, "❌ Введите число.")
        return

    # --- Roulette Amount ---
    if state == "WAITING_ROULETTE_AMOUNT":
        try:
            amount = float(text)
            tid = user.get('roulette_trip_id')
            payer_id = user.get('roulette_payer_id')
            
            trip = data.get_trip(tid)
            link_map = get_link_map()
            payer_master = logic.get_master(payer_id, link_map)
            split_map = {payer_master: amount}

            new_exp = {
                "id": int(time.time()),
                "payer_id": payer_id, 
                "amount": amount,
                "desc": "Рулетка (Угощение) 🎁",
                "category": "FUN", 
                "split": split_map,
                "ts": time.time()
            }
            
            trip['expenses'].append(new_exp)
            trips = data.load_json(data.TRIPS_FILE)
            trips[tid] = trip
            data.save_json(data.TRIPS_FILE, trips)
            data.update_user_state(user_id, "IDLE")

            # Notification + Refresh
            bot.send_message(chat_id, f"✅ Угощение на *{amount}* записано!")
            send_trip_dashboard(chat_id, user_id)
            
            users_db = data.load_json(data.USERS_FILE)
            payer_name = users_db.get(str(payer_id), {}).get('name', 'User')
            curr = trip.get('currency', 'THB')
            for m in trip['members']:
                if str(m) != str(payer_id):
                    bot.send_message(m, f"🎁 *Рулетка!* \n*{payer_name}* угостил всех на сумму *{amount} {curr}*! 🥳")

        except ValueError:
            bot.send_message(chat_id, "❌ Введите числовое значение суммы.")
        return

    # --- Note Input ---
    if state == "WAITING_FOR_NOTE_INPUT":
        tid = user.get('active_trip_id')
        if not tid: return
        trips = data.load_json(data.TRIPS_FILE)
        if 'notes' not in trips[tid]: trips[tid]['notes'] = []
        trips[tid]['notes'].append({"text": text, "author": user_name, "ts": time.time()})
        data.save_json(data.TRIPS_FILE, trips)
        data.update_user_state(user_id, "IDLE")
        bot.send_message(chat_id, "✅ Заметка сохранена!")
        send_trip_dashboard(chat_id, user_id)
        return

    # --- Expense Entry (Default) ---
    if state == "IDLE":
        try:
            parts = text.split()
            amount = float(parts[0])
            desc = " ".join(parts[1:]) if len(parts) > 1 else "Расход"
            tid = data.get_active_trip_id(user_id)
            if not tid: return bot.send_message(chat_id, "Сначала создайте или вступите в поездку! /start")
            trip = data.get_trip(tid)
            curr = trip.get('currency', 'THB')
            draft_id = f"{user_id}_{int(time.time())}"
            members = trip['members']
            link_map = get_link_map()
            masters = set(logic.get_master(m, link_map) for m in members)
            selected = {m: True for m in masters}
            draft_data = {
                "amount": amount,
                "desc": desc,
                "payer": uid_str,
                "trip_id": tid,
                "selected": selected,
                "category": "OTHER"
            }
            data.save_draft(draft_id, draft_data)
            send_category_menu(chat_id, draft_id, curr) # This will use refresh_menu_msg inside
        except ValueError:
            pass 

def handle_callback(chat_id, user_id, message_id, data_str):
    parts = data_str.split("|")
    cmd = parts[0]
    uid_str = str(user_id)
    
    if cmd == "OPEN_DASHBOARD":
        send_trip_dashboard(chat_id, user_id, message_id)
        return

    if cmd == "MENU_CREATE":
        data.update_user_state(user_id, "WAITING_TRIP_NAME")
        bot.send_message(chat_id, "✏️ Введите название поездки (например: `Тай 2026`):")
        return

    if cmd == "MENU_JOIN":
        data.update_user_state(user_id, "WAITING_TRIP_CODE")
        refresh_menu_msg(chat_id, user_id, "⌨️ Введите код поездки:", reply_markup={"inline_keyboard": [[{"text": "🔙 Отмена", "callback_data": "BACK_MAIN"}]]})
        return

    # --- Joining Logic ---
    if cmd == "JOIN_SOLO":
        user = data.get_user(user_id)
        tid = user.get('temp_trip_id')
        if not tid: return bot.send_message(chat_id, "⚠️ Ошибка сессии. Введите код заново.")
        users = data.load_json(data.USERS_FILE)
        trips = data.load_json(data.TRIPS_FILE)
        users[uid_str]['active_trip_id'] = tid
        if 'joined_trips' not in users[uid_str]: users[uid_str]['joined_trips'] = []
        if tid not in users[uid_str]['joined_trips']: users[uid_str]['joined_trips'].append(tid)
        users[uid_str]['state'] = "IDLE"
        if 'temp_trip_id' in users[uid_str]: del users[uid_str]['temp_trip_id']
        if uid_str not in trips[tid]['members']:
            trips[tid]['members'].append(uid_str)
            for m in trips[tid]['members']:
                if m != uid_str: bot.send_message(m, f"👋 *{users[uid_str].get('name')}* присоединился!")
        data.save_json(data.USERS_FILE, users)
        data.save_json(data.TRIPS_FILE, trips)
        bot.send_message(chat_id, f"✅ Вы присоединились! Активная поездка: `{trips[tid].get('name')}`")
        send_trip_dashboard(chat_id, user_id)
        return

    if cmd == "JOIN_LINKED":
        user = data.get_user(user_id)
        tid = user.get('temp_trip_id')
        if not tid: return
        trip = data.get_trip(tid)
        users_db = data.load_json(data.USERS_FILE)
        keyboard = []
        for mid in trip['members']:
            if mid == uid_str: continue
            m_user = users_db.get(str(mid), {})
            if not m_user.get('linked_to'):
                name = m_user.get('name', 'Unknown')
                keyboard.append([{"text": f"К {name}", "callback_data": f"REQ_LINK|{mid}"}])
        keyboard.append([{"text": "🔙 Отмена (я сам)", "callback_data": "JOIN_SOLO"}])
        bot.edit_message(chat_id, message_id, "💞 Выберите, к кому присоединиться (кто будет платить):", reply_markup={"inline_keyboard": keyboard})
        return

    if cmd == "REQ_LINK":
        target_id = parts[1]
        user = data.get_user(user_id)
        tid = user.get('temp_trip_id')
        my_name = user.get('name', 'User')
        msg = (
            f"🔔 *Запрос на привязку*\n"
            f"Пользователь *{my_name}* хочет присоединиться к вашему счету.\n"
            "Если вы примете, вы будете платить за двоих."
        )
        keyboard = {"inline_keyboard": [
            [{"text": "✅ Принять", "callback_data": f"APPROVE_LINK|{user_id}|{tid}"}],
            [{"text": "❌ Отклонить", "callback_data": f"REJECT_LINK|{user_id}"}]
        ]}
        bot.send_message(target_id, msg, reply_markup=keyboard)
        bot.edit_message(chat_id, message_id, "⏳ Запрос отправлен! Ждем подтверждения...")
        return

    if cmd == "APPROVE_LINK":
        child_id = parts[1]
        tid = parts[2]
        data.link_users(child_id, user_id)
        users = data.load_json(data.USERS_FILE)
        trips = data.load_json(data.TRIPS_FILE)
        child_str = str(child_id)
        users[child_str]['active_trip_id'] = tid
        if 'joined_trips' not in users[child_str]: users[child_str]['joined_trips'] = []
        if tid not in users[child_str]['joined_trips']: users[child_str]['joined_trips'].append(tid)
        users[child_str]['state'] = "IDLE"
        if 'temp_trip_id' in users[child_str]: del users[child_str]['temp_trip_id']
        if child_str not in trips[tid]['members']:
            trips[tid]['members'].append(child_str)
        data.save_json(data.USERS_FILE, users)
        data.save_json(data.TRIPS_FILE, trips)
        child_name = users[child_str].get('name', 'Partner')
        master_name = users[str(user_id)].get('name', 'Master')
        
        bot.edit_message(chat_id, message_id, f"✅ Вы приняли *{child_name}*! Теперь у вас общий счет.")
        bot.send_message(child_id, f"✅ *{master_name}* принял запрос! Ваши счета объединены.")
        send_trip_dashboard(child_id, child_id)
        return

    if cmd == "REJECT_LINK":
        child_id = parts[1]
        bot.edit_message(chat_id, message_id, "❌ Запрос отклонен.")
        bot.send_message(child_id, "❌ Запрос отклонен. Попробуйте войти как самостоятельный участник.", 
                         reply_markup={"inline_keyboard": [[{"text": "Попробовать снова", "callback_data": "BACK_MAIN"}]]})
        return

    if cmd == "MENU_TRIPS":
        users = data.load_json(data.USERS_FILE)
        trips = data.load_json(data.TRIPS_FILE)
        joined = users[uid_str].get('joined_trips', [])
        keyboard = []
        active = users[uid_str].get('active_trip_id')
        for tid in joined:
            t = trips.get(tid)
            if not t: continue
            mark = "✅ " if tid == active else ""
            keyboard.append([{"text": f"{mark}{t.get('name')}", "callback_data": f"SWITCH_TRIP|{tid}"}])
        keyboard.append([{"text": "🔙 В главное меню", "callback_data": "BACK_MAIN"}])
        bot.edit_message(chat_id, message_id, "🗂 *Ваши поездки*:", reply_markup={"inline_keyboard": keyboard})
        return

    if cmd == "SWITCH_TRIP":
        target_tid = parts[1]
        users = data.load_json(data.USERS_FILE)
        if target_tid in users[uid_str].get('joined_trips', []):
            users[uid_str]['active_trip_id'] = target_tid
            data.save_json(data.USERS_FILE, users)
            send_trip_dashboard(chat_id, user_id, message_id)
        return

    if cmd == "BACK_MAIN":
        handle_command(chat_id, user_id, "User", "/start")
        return

    if cmd == "CURR":
        curr_code = parts[1]
        tid = data.get_active_trip_id(user_id)
        if tid:
            trips = data.load_json(data.TRIPS_FILE)
            trips[tid]['currency'] = curr_code
            data.save_json(data.TRIPS_FILE, trips)
            trip = trips[tid]
            bot.send_message(chat_id, f"✅ Поездка создана!\nВалюта: *{curr_code}*\n🔑 Код: `{trip['code']}`", 
                             reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            data.update_user_state(user_id, "IDLE")
            send_trip_dashboard(chat_id, user_id)
        return

    if cmd == "CAT":
        draft_id = parts[1]
        category_label = parts[2]
        cat_key = "OTHER"
        for k, v in logic.CATEGORIES.items():
            if v == category_label:
                cat_key = k
                break
        draft = data.get_draft(draft_id)
        if draft:
            draft['category'] = cat_key
            data.save_draft(draft_id, draft)
            send_split_menu(chat_id, draft_id, message_id)
        return

    if cmd == "TOGGLE":
        draft_id = parts[1]
        target_mid = parts[2]
        draft = data.get_draft(draft_id)
        if draft:
            draft['selected'][target_mid] = not draft['selected'].get(target_mid, False)
            data.save_draft(draft_id, draft)
            send_split_menu(chat_id, draft_id, message_id)
        return

    if cmd == "CONFIRM":
        draft_id = parts[1]
        draft = data.get_draft(draft_id)
        if not draft: return
        tid = draft['trip_id']
        selected = draft['selected']
        count = sum(1 for v in selected.values() if v)
        if count == 0: return bot.answer_callback_query(message_id, "Выберите хотя бы одного участника!")
        amount = draft['amount']
        share = amount / count
        split_map = {mid: share for mid, active in selected.items() if active}
        new_exp = {
            "id": int(time.time()),
            "payer_id": draft['payer'],
            "amount": amount,
            "desc": draft['desc'],
            "category": draft['category'],
            "split": split_map,
            "ts": time.time()
        }
        trips = data.load_json(data.TRIPS_FILE)
        trips[tid]['expenses'].append(new_exp)
        data.save_json(data.TRIPS_FILE, trips)
        data.delete_draft(draft_id)
        
        # Success message instead of menu (notification style)
        bot.edit_message(chat_id, message_id, f"✅ Сохранено: *{amount}* ({draft['desc']})", 
                         reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        notify_others(tid, draft['payer'], amount, draft['desc'], draft['category'], split_map)
        return

    if cmd == "CANCEL":
        draft_id = parts[1]
        data.delete_draft(draft_id)
        bot.edit_message(chat_id, message_id, "❌ Отменено.", 
                         reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "MENU_BALANCE":
        tid = data.get_active_trip_id(user_id)
        if not tid: return
        trip = data.get_trip(tid)
        link_map = get_link_map()
        balances, total_spent, total_paid = logic.calculate_balance(trip, link_map)
        users_db = data.load_json(data.USERS_FILE)
        names = {}
        for uid in balances.keys():
            names[uid] = data.get_linked_names(uid)
        curr = trip.get('currency', 'THB')
        report = f"📊 *Баланс ({trip.get('name')}):*\n"
        report += f"💰 Всего: *{total_spent:,.0f} {curr}*\n\n"
        for uid, bal in balances.items():
            name = names.get(uid, uid)
            emoji = "🟢" if bal >= 0 else "🔴"
            report += f"{name}: {emoji} *{bal:+.0f} {curr}*\n"
        txs = logic.simplify_debts(balances, names)
        if txs:
            report += "\n🤝 *Расчеты:*\n"
            for t in txs:
                report += f"{t['from']} -> {t['to']}: *{t['amount']:,.0f} {curr}*\n"
        else:
            report += "\n✅ Все чисто!"
        keyboard = {"inline_keyboard": [
            [{"text": "⚙️ Сделать расчет", "callback_data": "MENU_SETTLE"}],
            [{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]
        ]}
        bot.edit_message(chat_id, message_id, report, reply_markup=keyboard)
        return

    if cmd == "MENU_SETTLE":
        tid = data.get_active_trip_id(user_id)
        if not tid: return
        trip = data.get_trip(tid)
        link_map = get_link_map()
        balances, _, _ = logic.calculate_balance(trip, link_map)
        users_db = data.load_json(data.USERS_FILE)
        names = {}
        for uid in balances.keys():
            names[uid] = data.get_linked_names(uid)
        curr = trip.get('currency', 'THB')
        rate = trip.get('rate', 0)
        txs = logic.simplify_debts(balances, names)
        if not txs:
            bot.edit_message(chat_id, message_id, "✅ Балансы уже выровнены!", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
            return
        for transaction in txs:
            from_name = transaction['from']
            to_name = transaction['to']
            amount = transaction['amount']
            amount_str = f"*{amount:,.0f} {curr}*"
            if rate > 0: amount_str += f" (~{amount*rate:,.0f} RUB)"
            from_id = next((uid for uid, n in names.items() if n == from_name), None)
            to_id = next((uid for uid, n in names.items() if n == to_name), None)
            if from_id:
                bot.send_message(from_id, f"💸 Вам необходимо перевести *{amount_str}* пользователю *{to_name}*.")
            if to_id:
                bot.send_message(to_id, f"💰 Пользователь *{from_name}* должен вам *{amount_str}*.")
        bot.edit_message(chat_id, message_id, "✅ Расчеты отправлены участникам в ЛС!", reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "MENU_ME":
        tid = data.get_active_trip_id(user_id)
        if not tid: return
        trip = data.get_trip(tid)
        link_map = get_link_map()
        stats = logic.get_my_stats(trip, uid_str, link_map)
        curr = trip.get('currency', 'THB')
        report = f"👤 *Ваша статистика ({trip.get('name')}):*\n\n"
        report += f"💰 *Всего потрачено (на семью): {stats['total_share']:.0f} {curr}*\n"
        if stats['cats']:
            report += "*Траты по категориям:*\n"
            for cat, amt in stats['cats'].items():
                label = logic.CATEGORIES.get(cat, cat)
                report += f"- {label}: {amt:.0f}\n"
        bot.edit_message(chat_id, message_id, report, reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "MENU_REPAY":
        tid = data.get_active_trip_id(user_id)
        if not tid: return
        trip = data.get_trip(tid)
        link_map = get_link_map()
        my_master = logic.get_master(user_id, link_map)
        masters = set(logic.get_master(m, link_map) for m in trip['members'])
        keyboard = []
        for mid in masters:
            if mid != my_master:
                name = data.get_linked_names(mid)
                keyboard.append([{"text": f"Вернуть {name}", "callback_data": f"REPAY_TO|{mid}"}])
        keyboard.append([{"text": "🔙 Назад", "callback_data": "OPEN_DASHBOARD"}])
        bot.edit_message(chat_id, message_id, "💸 Кому вы вернули долг?", reply_markup={"inline_keyboard": keyboard})
        return

    if cmd == "REPAY_TO":
        target_uid = parts[1]
        data.update_user_state(user_id, "WAITING_REPAYMENT_AMOUNT", repay_target=target_uid)
        tid = data.get_active_trip_id(user_id)
        trip = data.get_trip(tid)
        link_map = get_link_map()
        balances, _, _ = logic.calculate_balance(trip, link_map)
        users_db = data.load_json(data.USERS_FILE)
        names = {}
        for uid in balances.keys(): names[uid] = uid
        txs = logic.simplify_debts(balances, names)
        my_master = logic.get_master(user_id, link_map)
        target_master = logic.get_master(target_uid, link_map)
        debt_amount = 0
        for t in txs:
            if t['from'] == my_master and t['to'] == target_master:
                debt_amount = t['amount']
                break
        curr = trip.get('currency', 'THB')
        hint = f"(Ваш текущий долг: *{debt_amount:,.0f} {curr}*)" if debt_amount > 0 else "(У вас нет долгов перед этим участником)"
        
        # Here we use refresh_menu because we are prompting for text, and we want the prompt to be the "menu"
        refresh_menu_msg(chat_id, user_id, f"⌨️ Введите сумму возврата:\n{hint}", reply_markup={"inline_keyboard": [[{"text": "🔙 Отмена", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "MENU_ROULETTE":
        tid = data.get_active_trip_id(user_id)
        if not tid: return
        trip = data.get_trip(tid)
        link_map = get_link_map()
        masters = list(set(logic.get_master(m, link_map) for m in trip['members']))
        victim_id = random.choice(masters)
        victim_name = data.get_linked_names(victim_id)
        
        # Animation
        bot.edit_message(chat_id, message_id, f"🎲 *Крутим рулетку...*")
        time.sleep(1)
        
        # Set state for victim
        data.update_user_state(victim_id, "WAITING_ROULETTE_AMOUNT", roulette_trip_id=tid, roulette_payer_id=victim_id)
        
        # Result shown in the menu
        bot.edit_message(chat_id, message_id, f"🎯 Сегодня платит: *{victim_name.upper()}*! 🎉", 
                         reply_markup={"inline_keyboard": [[{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]]})
        
        # Direct prompt to victim (as a fresh message to get attention)
        refresh_menu_msg(victim_id, victim_id, "🎉 Вы проиграли в рулетку! Введите сумму, которую оплатили:", reply_markup={"inline_keyboard": [[{"text": "🔙 Отмена", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "MENU_ALL_EXPENSES":
        send_all_expenses_list(chat_id, user_id, message_id)
        return

    if cmd == "ALL_EXPENSES_PAGE":
        page = int(parts[1])
        send_all_expenses_list(chat_id, user_id, message_id, page)
        return

    if cmd == "MENU_NOTES":
        tid = data.get_active_trip_id(user_id)
        if not tid: return
        trip = data.get_trip(tid)
        notes = trip.get('notes', [])
        msg = "📝 *Важные заметки:*\n\n"
        if not notes: msg = "📝 Заметок пока нет."
        else:
            for i, note in enumerate(notes):
                date = datetime.fromtimestamp(note['ts']).strftime('%d.%m')
                msg += f"{i+1}. {note['text']} _({note['author']}, {date})_\n"
        keyboard = {"inline_keyboard": [
            [{"text": "➕ Добавить заметку", "callback_data": "ADD_NOTE_PROMPT"}],
            [{"text": "🔙 К меню поездки", "callback_data": "OPEN_DASHBOARD"}]
        ]}
        bot.edit_message(chat_id, message_id, msg, reply_markup=keyboard)
        return

    if cmd == "ADD_NOTE_PROMPT":
        data.update_user_state(user_id, "WAITING_FOR_NOTE_INPUT")
        refresh_menu_msg(chat_id, user_id, "✍️ Введите текст заметки:", reply_markup={"inline_keyboard": [[{"text": "🔙 Отмена", "callback_data": "OPEN_DASHBOARD"}]]})
        return

    if cmd == "MENU_EXPORT":
        tid = data.get_active_trip_id(user_id)
        if not tid: return
        trip = data.get_trip(tid)
        curr = trip.get('currency', 'THB')
        users_db = data.load_json(data.USERS_FILE)
        csv_path = os.path.join(data.DATA_DIR, "expenses.csv")
        with open(csv_path, 'w', encoding='utf-8') as f:
            f.write(f"Date,Category,Payer,Amount ({curr}),Description\n")
            names = {uid: users_db.get(uid, {}).get('name', 'Unknown') for uid in trip['members']}
            for exp in trip['expenses']:
                payer = names.get(str(exp['payer_id']), exp['payer_id'])
                desc = exp.get('desc', '-').replace(',', ' ')
                cat = exp.get('category', 'Other')
                f.write(f"{datetime.fromtimestamp(exp['ts'])},{cat},{payer},{exp['amount']},{desc}\n")
        bot.send_document(chat_id, csv_path)
        return
    
    if cmd == "SHOW_HELP":
        help_text = (
            "📖 *Как пользоваться Splitopus*\n\n"
            "💸 *Добавление трат:*\n"
            "Просто напишите сумму и название в чат.\n"
            "Пример: `500 Обед` или `1200 Такси`.\n"
            "Бот предложит выбрать категорию и участников.\n\n"
            "💞 *Партнеры (Семейный счет):*\n"
            "Если вы в поездке парой, один может присоединиться к другому (через код поездки -> Присоединиться к партнеру). "
            "Тогда у вас будет общий баланс, и в списках вы будете отображаться как одна семья.\n\n"
            "📊 *Баланс и Долги:*\n"
            "Нажмите **Баланс**, чтобы увидеть, кто сколько потратил и кто кому должен. "
            "Кнопка **Сделать расчет** пришлет всем уведомления о долгах.\n\n"
            "🎲 *Рулетка:*\n"
            "Не можете решить, кто платит за ужин? Рулетка выберет счастливчика! "
            "Этот расход считается как **угощение** (подарок) от плательщика и не создает долгов у остальных.\n\n"
            "🔄 *Возврат долга:*\n"
            "Если вы перевели деньги другу, нажмите **Вернуть долг**, выберите его и введите сумму. Это уменьшит ваш долг в системе."
        )
        bot.edit_message(chat_id, message_id, help_text, reply_markup={"inline_keyboard": [[{"text": "🔙 К меню", "callback_data": "OPEN_DASHBOARD"}]]})
        return

# --- Main Loop ---
def run():
    logger.info("Bot started...")
    offset = None
    while True:
        try:
            updates = bot.get_updates(offset=offset, timeout=30)
            for u in updates:
                offset = u['update_id'] + 1
                
                if 'message' in u:
                    msg = u['message']
                    chat_id = msg['chat']['id']
                    user = msg.get('from', {})
                    user_id = user.get('id')
                    user_name = user.get('first_name', 'User')
                    text = msg.get('text', '')
                    
                    if text.startswith('/'):
                        handle_command(chat_id, user_id, user_name, text)
                    else:
                        handle_text(chat_id, user_id, user_name, text)
                        
                elif 'callback_query' in u:
                    cb = u['callback_query']
                    chat_id = cb['message']['chat']['id']
                    user_id = cb['from']['id']
                    msg_id = cb['message']['message_id']
                    data_str = cb['data']
                    
                    handle_callback(chat_id, user_id, msg_id, data_str)
                    bot.answer_callback_query(cb['id'])
                    
        except KeyboardInterrupt:
            logger.info("Stopping bot...")
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}", exc_info=True)
            time.sleep(5)

if __name__ == "__main__":
    run()
