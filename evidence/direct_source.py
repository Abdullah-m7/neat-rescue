def eligible(order, policy):
    age = order['age_days']
    window = policy['window_days']
    if age < 0:
        return False
    return bool(age <= window)


def refund_cents(order):
    paid = order['paid_cents']
    done = order['already_refunded_cents']
    remaining = max(0, paid - done)
    requested = max(0, order['requested_cents'])
    return int(min(requested, remaining))


def operation_key(event):
    tenant = str(event['tenant_id'])
    refund = str(event['refund_id'])
    return tenant + ':' + refund


def inventory_after(stock, qty, already_applied):
    if already_applied:
        return int(stock)
    if qty <= 0:
        return int(stock)
    if qty > stock:
        return int(stock)
    return int(stock - qty)
