def eligible(order, policy):
    age = order['age_days']
    return age >= 0 and age <= policy['window_days']

def refund_cents(order):
    remaining = max(0, order['paid_cents'] - order['already_refunded_cents'])
    return max(0, min(order['requested_cents'], remaining))

def operation_key(event):
    return event['order_id']

def inventory_after(stock, qty, already_applied):
    if already_applied or qty <= 0 or qty > stock:
        return stock
    return stock - qty
