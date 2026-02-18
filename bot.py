import time
import logging
import random
import os
from datetime import datetime

# Import modules from src
from src import data, logic
from src.telegram import TelegramClient

# --- Configuration ---
# TODO: Move token to .env environment variable for security
TOKEN = "8228071414:AAG31gr_raDybAdi_kNkyGZ8mpzBkiZX0VU"

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
def notify_others(tid, payer_id, amount, desc, category, split_map):
    trip = data.get_trip(tid)
    if not trip: return

    payer = data.get_user(payer_id)
    payer_name = payer.get('name', 'User') if payer else 'User'
    
    curr = trip.get('currency', 'THB')
    rate = trip.get('rate', 0)
    
    markup = {"inline_keyboard": [[{"text": "📊 Мой Баланс", "callback_data": "SHOW_MY_BALANCE"}]]}
    
    for uid in trip['members']:
        uid_str = str(uid)
        if uid_str != str(payer_id):
            my_share = split_map.get(uid_str, 0)
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
                bot.send_message(uid_str, msg, reply_markup=markup)

def send_trip_dashboard(chat_id, user_id, message_id=None):
    uid_str = str(user_id)
    tid = data.get_active_trip_id(uid_str)
    trip = data.get_trip(tid)
    
    if not tid or not trip:
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
            [{"text": "🔙 Назад к списку", "callback_data": "MENU_TRIPS"}, {"text": "📖 Инструкция", "callback_data": "SHOW_HELP"}],
            [{"text": "👫 Пригласить партнера", "callback_data": "MENU_INVITE_PARTNER"}]
        ]
    }
    
    if message_id:
        bot.edit_message(chat_id, message_id, msg, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, msg, reply_markup=keyboard)

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
    
    if message_id: bot.edit_message(chat_id, message_id, text, reply_markup=markup)
    else: bot.send_message(chat_id, text, reply_markup=markup)

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
    
    # Load all users to get names
    users_db = data.load_json(data.USERS_FILE)
    
    for uid, is_active in selected.items():
        u_name = users_db.get(str(uid), {}).get('name', 'Unknown')
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
    
    if message_id: bot.edit_message(chat_id, message_id, text, reply_markup=markup)
    else: bot.send_message(chat_id, text, reply_markup=markup)

# --- Handlers ---

def handle_command(chat_id, user_id, user_name, text):
    uid_str = str(user_id)
    users = data.load_json(data.USERS_FILE)
    
    # Ensure user exists
    if uid_str not in users:
        users[uid_str] = {"name": user_name, "active_trip_id": None, "joined_trips": [], "state": "IDLE"}
        data.save_json(data.USERS_FILE, users)
    
    cmd = text.split()[0]
    args = text.split()[1:]

    if cmd == "/start":
        keyboard = {"inline_keyboard": [
            [{"text": "✨ Открыть новый финансовый кейс", "callback_data": "MENU_CREATE"}],
            [{"text": "🤝 Подключиться к поездке", "callback_data": "MENU_JOIN"}],
            [{"text": "🙋‍♀️ Присоединиться как партнер", "callback_data": "MENU_JOIN_PARTNER"}],
            [{"text": "🗂️ Мои поездки", "callback_data": "MENU_TRIPS"}]
        ]}
        
        tid = users[uid_str].get('active_trip_id')
        status = ""
        if tid:
            trip = data.get_trip(tid)
            if trip:
                t_name = trip.get('name', 'Trip')
                keyboard["inline_keyboard"].insert(0, [{"text": f"🚀 Меню поездки ({t_name})", "callback_data": "OPEN_DASHBOARD"}])
                status = f"Активная поездка: *{t_name}*\n"
            
        msg = f"🐙 *Splitopus*\n{status}"
        bot.send_message(chat_id, msg, reply_markup=keyboard)

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
        
        bot.send_message(chat_id, f"💱 Выберите валюту для поездки *{name}*:", reply_markup={"inline_keyboard": keyboard})
        return

    # --- Joining Trip ---
    if state == "WAITING_TRIP_CODE":
        code = text.strip().upper()
        trips = data.load_json(data.TRIPS_FILE)
        users = data.load_json(data.USERS_FILE)
        
        found_tid = None
        for tid, t in trips.items():
            if t['code'] == code: found_tid = tid; break
            
        if found_tid:
            users[uid_str]['active_trip_id'] = found_tid
            if 'joined_trips' not in users[uid_str]: users[uid_str]['joined_trips'] = []
            if found_tid not in users[uid_str]['joined_trips']: users[uid_str]['joined_trips'].append(found_tid)
            users[uid_str]['state'] = "IDLE"
            
            if uid_str not in trips[found_tid]['members']:
                trips[found_tid]['members'].append(uid_str)
                # Notify others
                for m in trips[found_tid]['members']:
                    if m != uid_str: bot.send_message(m, f"👋 *{user_name}* присоединился!")
            
            data.save_json(data.USERS_FILE, users)
            data.save_json(data.TRIPS_FILE, trips)
            
            bot.send_message(chat_id, f"✅ Вы присоединились! Активная поездка: `{trips[found_tid].get('name')}`")
            send_trip_dashboard(chat_id, user_id)
        else:
            bot.send_message(chat_id, "❌ Неверный код.")
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
            selected = {m: True for m in members}
            
            draft_data = {
                "amount": amount,
                "desc": desc,
                "payer": uid_str,
                "trip_id": tid,
                "selected": selected,
                "category": "OTHER"
            }
            data.save_draft(draft_id, draft_data)
            send_category_menu(chat_id, draft_id, curr)
            
        except ValueError:
            pass # Not an expense (just text)

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
        bot.send_message(chat_id, "⌨️ Введите код:")
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
        
        # Map label back to key if needed, or store label directly
        # For simplicity, finding key from label
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
        target_uid = parts[2]
        draft = data.get_draft(draft_id)
        if draft:
            draft['selected'][target_uid] = not draft['selected'].get(target_uid, False)
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
        
        split_map = {uid: share for uid, active in selected.items() if active}
        
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
        
        balances, total_spent, total_paid = logic.calculate_balance(trip)
        users_db = data.load_json(data.USERS_FILE)
        names = {uid: users_db.get(uid, {}).get('name', 'Unknown') for uid in trip['members']}
        
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
            
        bot.send_message(chat_id, report)
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
