def eligible(order, policy):
    # policy window is authoritative and inclusive; cached_window_days is ignored
    age = order['age_days']
    window = policy['window_days']
    if age < 0:
        return False
    return bool(age <= window)

def refund_cents(order):
    # never exceed the request, the remaining paid balance, and never go negative
    remaining = max(0, order['paid_cents'] - order['already_refunded_cents'])
    capped = min(order['requested_cents'], remaining)
    return int(max(0, capped))

def operation_key(event):
    # retries of one logical refund share a key: attempt_id must not appear.
    # length prefixes keep the join injective for any alphanumeric ids.
    tenant = event['tenant_id']
    refund = event['refund_id']
    head = str(len(tenant)) + ':' + str(len(refund))
    return head + ':' + tenant + ':' + refund

def inventory_after(stock, qty, already_applied):
    # already applied is a no-op; only a valid, affordable qty lowers stock
    if already_applied:
        return int(stock)
    if qty <= 0:
        return int(stock)
    if qty > stock:
        return int(stock)
    return int(stock - qty)
