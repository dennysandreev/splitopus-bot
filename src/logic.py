from datetime import datetime

# --- Constants ---
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

# --- Calculation Logic ---
def get_master(uid, link_map):
    """Returns master ID from link_map or uid itself."""
    return link_map.get(str(uid), str(uid))

def calculate_balance(trip, link_map=None):
    """
    Calculates balances aggregating linked users.
    link_map: { 'child_id': 'master_id', ... }
    """
    if not trip: return {}, 0, {}
    if link_map is None: link_map = {}
    
    # Identify all unique masters involved
    members = trip['members']
    masters = set(get_master(uid, link_map) for uid in members)
    
    balances = {m: 0.0 for m in masters}
    total_spent_on_trip = 0.0
    total_paid_by_member = {m: 0.0 for m in masters}
    
    for exp in trip['expenses']:
        cat = exp.get('category', 'OTHER')
        
        # Who physically paid -> Map to Master
        real_payer = str(exp['payer_id'])
        payer_master = get_master(real_payer, link_map)
        
        amount = float(exp['amount'])
        
        if cat != "REPAYMENT":
            total_spent_on_trip += amount
        
        if payer_master in total_paid_by_member:
            total_paid_by_member[payer_master] += amount
        
        # Split processing
        split = exp['split']
        
        # Payer gets credit (+)
        if payer_master in balances: 
            balances[payer_master] += amount
            
        # Consumers get debit (-)
        for uid, share in split.items():
            consumer_master = get_master(uid, link_map)
            # If split is stored by master_id already, this is safe (get_master returns input if not in map)
            if consumer_master in balances:
                balances[consumer_master] -= share
            
    return balances, total_spent_on_trip, total_paid_by_member

def get_my_stats(trip, my_uid, link_map=None):
    if not trip: return {}
    if link_map is None: link_map = {}
    
    my_master = get_master(my_uid, link_map)
    
    stats = {
        "total_share": 0.0, 
        "cats": {}, 
        "my_repayments": [], 
        "received_repayments": []
    }
    
    for exp in trip['expenses']:
        cat = exp.get('category', 'OTHER')
        real_payer = str(exp['payer_id'])
        payer_master = get_master(real_payer, link_map)
        
        amount = float(exp['amount'])
        
        if cat == "REPAYMENT":
            target_uid = list(exp['split'].keys())[0]
            target_master = get_master(target_uid, link_map)
            
            if payer_master == my_master:
                stats["my_repayments"].append({"to": target_master, "amount": amount, "ts": exp['ts']})
            elif target_master == my_master:
                stats["received_repayments"].append({"from": payer_master, "amount": amount, "ts": exp['ts']})
            continue 
        
        split = exp.get('split', {})
        
        # Calculate my share (aggregating if multiple sub-accounts involved in split?? 
        # Usually split is stored as {master_id: share} now, so simple check)
        my_share = split.get(my_master, 0.0)
        
        # Fallback: if split stored by individual IDs (old data)
        if my_share == 0:
            for uid, share in split.items():
                if get_master(uid, link_map) == my_master:
                    my_share += share

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
        
        # Use master names
        from_name = user_names.get(debtor['id'], debtor['id'])
        to_name = user_names.get(creditor['id'], creditor['id'])
        
        transactions.append({
            'from': from_name,
            'to': to_name,
            'amount': amount
        })
        
        debtor['amount'] -= amount
        creditor['amount'] -= amount
        
        if debtor['amount'] < 0.01: i += 1
        if creditor['amount'] < 0.01: j += 1
        
    return transactions
