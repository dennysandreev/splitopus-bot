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
def calculate_balance(trip):
    """
    Calculates balances for all members in a trip.
    Returns: (balances, total_spent_on_trip, total_paid_by_member)
    """
    if not trip: 
        return {}, 0, {}
    
    balances = {uid: 0.0 for uid in trip['members']}
    total_spent_on_trip = 0.0
    total_paid_by_member = {uid: 0.0 for uid in trip['members']}
    
    for exp in trip['expenses']:
        cat = exp.get('category', 'OTHER')
        payer = str(exp['payer_id'])
        amount = float(exp['amount'])
        
        # 1. Total spent (excluding debt repayments)
        if cat != "REPAYMENT":
            total_spent_on_trip += amount
        
        # 2. Total paid by each member (contributions)
        if payer in total_paid_by_member:
            total_paid_by_member[payer] += amount
        
        # 3. Calculate balances (Who owes whom)
        split = exp['split']
        if payer in balances: 
            balances[payer] += amount
            
        for uid, share in split.items():
            uid_str = str(uid)
            if uid_str in balances: 
                balances[uid_str] -= share
            
    return balances, total_spent_on_trip, total_paid_by_member


def get_my_stats(trip, my_uid):
    """
    Calculates personal statistics for a user in a trip.
    """
    if not trip: 
        return {}
    
    stats = {
        "total_share": 0.0, 
        "cats": {}, 
        "my_repayments": [], 
        "received_repayments": []
    }
    my_uid = str(my_uid)
    
    for exp in trip['expenses']:
        cat = exp.get('category', 'OTHER')
        payer = str(exp['payer_id'])
        amount = float(exp['amount'])
        desc = exp.get('desc', 'Расход')
        
        if cat == "REPAYMENT":
            # I repaid a debt
            if payer == my_uid:
                target_uid = list(exp['split'].keys())[0]
                stats["my_repayments"].append({"to": target_uid, "amount": amount, "ts": exp['ts']})
            # Debt was repaid to me
            elif my_uid in exp['split']:
                stats["received_repayments"].append({"from": payer, "amount": amount, "ts": exp['ts']})
            continue 
        
        split = exp.get('split', {})
        my_share = split.get(my_uid, 0.0)
        
        if my_share > 0:
            stats["total_share"] += my_share
            stats["cats"][cat] = stats["cats"].get(cat, 0.0) + my_share
            
    return stats


def simplify_debts(balances, user_names):
    """
    Optimizes debt transactions to minimize transfers.
    Returns a list of transactions: [{'from': name, 'to': name, 'amount': X}, ...]
    """
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
