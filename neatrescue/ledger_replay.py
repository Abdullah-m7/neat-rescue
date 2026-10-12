"""Real-SQLite replay of the returns-desk idempotency contract.

One synthetic scenario on one newly created database: a legitimate partial
refund is committed, its acknowledgement is deliberately dropped AFTER the
commit, the connection is closed and reopened (a connection restart inside
this same process, not an operating system process fault), and the retry is
then processed next to two neighbouring logical operations -- another refund
on the same tenant and order, and a different tenant reusing the same
refund_id and order_id.

Candidate behaviour comes from bounded_python.load_validated_source: no
candidate source is exec'd and no reference oracle is imported here, so the
expectations below follow from the written business contract alone.

Synthetic fixtures only: no real money, no production system, and no
empirical reliability or production safety claim from one scenario.
"""
import hashlib
import json
import os
import random
import sqlite3
import tempfile
from pathlib import Path
from .bounded_python import load_validated_source

__all__=['LEDGER_PROTOCOL','INVARIANT_NAMES','replay']

LEDGER_PROTOCOL='ledger-replay/v1'
INVARIANT_NAMES=('no_duplicate_payment_after_retry','legitimate_sibling_paid','other_tenant_paid',
                 'amounts_correct','inventory_correct','commit_survived_connection_restart',
                 'no_missed_operations','no_unexpected_operations')

# operation_key is the idempotency key: one global SQL UNIQUE, not per tenant.
_SCHEMA=(
    'CREATE TABLE orders(tenant_id TEXT NOT NULL, order_id TEXT NOT NULL, paid_cents INTEGER NOT NULL,'
    ' refunded_cents INTEGER NOT NULL, age_days INTEGER NOT NULL, cached_window_days INTEGER NOT NULL,'
    ' stock INTEGER NOT NULL, PRIMARY KEY(tenant_id, order_id))',
    'CREATE TABLE payments(seq INTEGER PRIMARY KEY AUTOINCREMENT, operation_key TEXT NOT NULL UNIQUE,'
    ' tenant_id TEXT NOT NULL, refund_id TEXT NOT NULL, order_id TEXT NOT NULL, attempt_id TEXT NOT NULL,'
    ' amount_cents INTEGER NOT NULL)',
)
_PAYMENT=('seq','operation_key','tenant_id','refund_id','order_id','attempt_id','amount_cents')
_ORDER=('paid_cents','refunded_cents','age_days','cached_window_days','stock')
_ALPHA='abcdefghijklmnopqrstuvwxyz0123456789'

def _sha(text):return hashlib.sha256(text.encode()).hexdigest()
def _slot(tenant_id,order_id):return '{0}|{1}'.format(tenant_id,order_id)

def _logical_id(op):
    """Business identity of one refund, independent of any candidate key."""
    return _slot(op['tenant_id'],op['refund_id'])

def _check_seed(seed):
    if not isinstance(seed,int) or isinstance(seed,bool):raise ValueError('seed must be an int')
    if abs(seed)>2**31:raise ValueError('seed out of range')

def _word(rng,size):return ''.join(rng.choice(_ALPHA) for _ in range(size))

def _other(rng,size,taken):
    word=_word(rng,size)
    while word in taken:word=_word(rng,size)
    return word

def _scenario(seed):
    """Freeze ids, amounts and quantities for this seed. No path, no clock."""
    rng=random.Random('ledger-replay|{0}|{1}'.format(LEDGER_PROTOCOL,seed))
    tenant_a='t'+_word(rng,5);tenant_b='t'+_other(rng,5,{tenant_a[1:]})
    order_id='ord'+_word(rng,6)
    refund='rf'+_word(rng,6);sibling='rf'+_other(rng,6,{refund[2:]})
    first=_word(rng,rng.randint(6,9))
    # A retry carries a fresh attempt_id of a different length, by contract.
    retry=_word(rng,len(first)+rng.choice([1,2]))
    window=rng.choice([14,30,45])
    base_cents=12900+100*rng.randint(0,9)
    sibling_cents=4500+100*rng.randint(0,5)
    other_cents=7700+100*rng.randint(0,5)
    def order_row(tenant,stock):
        # Paid balance stays far above twice the request, so a wrong duplicate
        # is actually observable instead of being capped away.
        return {'tenant_id':tenant,'order_id':order_id,'paid_cents':100000+1000*rng.randint(0,20),
                'refunded_cents':0,'age_days':rng.choice([0,1]),
                'cached_window_days':max(1,window-rng.randint(1,3)),'stock':stock}
    def operation(role,phase,tenant,refund_id,attempt,cents,qty):
        return {'role':role,'phase':phase,'tenant_id':tenant,'refund_id':refund_id,'order_id':order_id,
                'attempt_id':attempt,'requested_cents':cents,'qty':qty}
    return {'policy':{'window_days':window},
            'orders':[order_row(tenant_a,rng.randint(6,9)),order_row(tenant_b,rng.randint(4,6))],
            'operations':[operation('base','first_connection',tenant_a,refund,first,base_cents,2),
                          operation('retry','after_restart',tenant_a,refund,retry,base_cents,2),
                          operation('sibling','after_restart',tenant_a,sibling,_word(rng,7),sibling_cents,1),
                          operation('other_tenant','after_restart',tenant_b,refund,_word(rng,7),other_cents,1)]}

# -------------------------------------------------------------------- oracle
# Derived from the contract text only: never calls a candidate function.

def _expected(scenario):
    window=scenario['policy']['window_days']
    books={(row['tenant_id'],row['order_id']):dict(row) for row in scenario['orders']}
    roles={}
    for op in scenario['operations']:roles.setdefault(_logical_id(op),[]).append(op['role'])
    logical={}
    for op in scenario['operations']:
        lid=_logical_id(op)
        if lid in logical:continue  # a retry of a settled operation settles nothing further
        row=books[(op['tenant_id'],op['order_id'])]
        if not 0<=row['age_days']<=window:
            logical[lid]={'payments':0,'amount_cents':0,'roles':roles[lid]};continue
        want=op['requested_cents'];remaining=row['paid_cents']-row['refunded_cents']
        amount=min(want,remaining) if want>0 and remaining>0 else 0
        row['refunded_cents']+=amount
        if 0<op['qty']<=row['stock']:row['stock']-=op['qty']
        logical[lid]={'payments':1,'amount_cents':amount,'roles':roles[lid]}
    return {'logical_operations':logical,
            'inventory':{_slot(*key):row['stock'] for key,row in books.items()},
            'rule':'each distinct tenant|refund settles exactly once at min(request, remaining paid balance)'
                   ' and lowers stock once; a retry of a settled operation pays nothing'}

def _observed(conn):
    rows=conn.execute('SELECT {0} FROM payments ORDER BY seq'.format(','.join(_PAYMENT))).fetchall()
    logical={}
    for row in rows:
        paid=dict(zip(_PAYMENT,row))
        slot=logical.setdefault(_slot(paid['tenant_id'],paid['refund_id']),
                                {'payments':0,'amount_cents':0,'operation_keys':[],'attempt_ids':[]})
        slot['payments']+=1;slot['amount_cents']+=paid['amount_cents']
        slot['operation_keys'].append(paid['operation_key']);slot['attempt_ids'].append(paid['attempt_id'])
    return {'logical_operations':logical,
            'inventory':{_slot(t,o):s for t,o,s in
                         conn.execute('SELECT tenant_id,order_id,stock FROM orders ORDER BY tenant_id,order_id')},
            'payment_rows':[dict(zip(_PAYMENT,row)) for row in rows]}

def _differences(expected,observed):
    missed,duplicated,amounts,inventory=[],[],[],[]
    for lid,want in expected['logical_operations'].items():
        got=observed['logical_operations'].get(lid,{'payments':0,'amount_cents':0})
        if got['payments']<want['payments']:missed.append(lid)
        if got['payments']>want['payments']:
            duplicated.append({'logical_id':lid,'expected':want['payments'],'observed':got['payments']})
        if got['amount_cents']!=want['amount_cents']:
            amounts.append({'logical_id':lid,'expected_cents':want['amount_cents'],
                            'observed_cents':got['amount_cents']})
    for slot,want in expected['inventory'].items():
        got=observed['inventory'].get(slot)
        if got!=want:inventory.append({'order':slot,'expected_stock':want,'observed_stock':got})
    unexpected=set(observed['logical_operations'])-set(expected['logical_operations'])
    return {'missed_operations':sorted(missed),'duplicate_operations':duplicated,
            'incorrect_amounts':amounts,'inventory_mismatches':inventory,
            'unexpected_operations':sorted(unexpected)}

def _role_id(scenario,role):
    return _logical_id(next(op for op in scenario['operations'] if op['role']==role))

def _settled_exactly(scenario,role,expected,observed):
    lid=_role_id(scenario,role);want=expected['logical_operations'][lid]
    got=observed['logical_operations'].get(lid,{'payments':0,'amount_cents':0})
    return got['payments']==want['payments'] and got['amount_cents']==want['amount_cents']

def _invariants(scenario,expected,observed,diff,restart):
    base=_role_id(scenario,'base')
    for_base=observed['logical_operations'].get(base,{'payments':0})['payments']
    return {'no_duplicate_payment_after_retry':for_base<=expected['logical_operations'][base]['payments'],
            'legitimate_sibling_paid':_settled_exactly(scenario,'sibling',expected,observed),
            'other_tenant_paid':_settled_exactly(scenario,'other_tenant',expected,observed),
            'amounts_correct':not diff['incorrect_amounts'],
            'inventory_correct':not diff['inventory_mismatches'],
            'commit_survived_connection_restart':bool(restart['committed_row_visible_after_reopen']),
            'no_missed_operations':not diff['missed_operations'],
            'no_unexpected_operations':not diff['unexpected_operations']}

# ------------------------------------------------------------------ database

def _create_exclusively(path):
    """Create the database file and nothing else; never touch an existing one."""
    try:handle=os.open(str(path),os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600)
    except FileExistsError:
        raise ValueError('refusing to reuse an existing database: '+path.name) from None
    except OSError as exc:
        raise ValueError('cannot create database {0}: {1}'.format(path.name,exc)) from None
    os.close(handle)

def _emit(events,kind,data):events.append({'seq':len(events)+1,'kind':kind,'data':data})

def _kind(role,outcome):
    if outcome=='REJECTED_INELIGIBLE':return 'REJECTED'
    if role=='retry':return 'DUPLICATE_PAYMENT' if outcome=='PAID' else 'REPLAY'
    if outcome=='PAID':return 'COMMIT' if role=='base' else 'NEW_PAYMENT'
    return 'BLOCKED'

def _process(conn,funcs,op,policy):
    """Candidate helpers decide the key, eligibility, amount and stock."""
    found=conn.execute('SELECT {0} FROM orders WHERE tenant_id=? AND order_id=?'.format(','.join(_ORDER)),
                       (op['tenant_id'],op['order_id'])).fetchone()
    if found is None:raise LookupError('scenario order row is missing for '+_logical_id(op))
    row=dict(zip(_ORDER,found))
    event={name:op[name] for name in ('tenant_id','refund_id','attempt_id','order_id')}
    key=funcs['operation_key'](event)
    if type(key) is not str or not key:raise TypeError('operation_key returned {0!r}'.format(key))
    verdict=funcs['eligible']({'age_days':row['age_days'],'cached_window_days':row['cached_window_days']},
                              dict(policy))
    if verdict is not True and verdict is not False:raise TypeError('eligible returned {0!r}'.format(verdict))
    result={'role':op['role'],'phase':op['phase'],'operation_key':key,'attempt_id':op['attempt_id'],
            'logical_id':_logical_id(op),'requested_cents':op['requested_cents'],'qty':op['qty'],
            'stock_before':row['stock'],'stock_after':row['stock'],'amount_cents':0,'paid':False}
    if not verdict:return dict(result,outcome='REJECTED_INELIGIBLE')
    settled=conn.execute('SELECT 1 FROM payments WHERE operation_key=?',(key,)).fetchone() is not None
    amount=funcs['refund_cents']({'requested_cents':op['requested_cents'],'paid_cents':row['paid_cents'],
                                  'already_refunded_cents':row['refunded_cents']})
    if type(amount) is not int:raise TypeError('refund_cents returned {0!r}'.format(amount))
    stock_after=funcs['inventory_after'](row['stock'],op['qty'],settled)
    if type(stock_after) is not int:raise TypeError('inventory_after returned {0!r}'.format(stock_after))
    outcome,paid='REPLAY_SKIPPED_AS_SETTLED',False
    if not settled:
        try:
            conn.execute('INSERT INTO payments(operation_key,tenant_id,refund_id,order_id,attempt_id,amount_cents)'
                         ' VALUES(?,?,?,?,?,?)',(key,op['tenant_id'],op['refund_id'],op['order_id'],
                                                 op['attempt_id'],amount))
            outcome,paid='PAID',True
        except sqlite3.IntegrityError:outcome='BLOCKED_BY_UNIQUE_KEY'
    conn.execute('UPDATE orders SET stock=?, refunded_cents=refunded_cents+? WHERE tenant_id=? AND order_id=?',
                 (stock_after,amount if paid else 0,op['tenant_id'],op['order_id']))
    conn.commit()
    return dict(result,outcome=outcome,paid=paid,stock_after=stock_after,key_already_settled=settled,
                amount_cents=amount if paid else 0)

def _sequence(path,funcs,scenario):
    """Commit, lose the acknowledgement, restart the connection, then retry."""
    events,errors=[],[]
    observed={'logical_operations':{},'inventory':{},'payment_rows':[]}
    restart={'rows_after_reopen':0,'committed_row_visible_after_reopen':False}
    conn=None
    try:
        conn=sqlite3.connect(str(path))
        for statement in _SCHEMA:conn.execute(statement)
        for row in scenario['orders']:
            conn.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?)',
                         (row['tenant_id'],row['order_id'],row['paid_cents'],row['refunded_cents'],
                          row['age_days'],row['cached_window_days'],row['stock']))
        conn.commit()
        _emit(events,'DB_CREATED',{'connection_generation':1,'orders':len(scenario['orders']),
                                   'journal_mode':conn.execute('PRAGMA journal_mode').fetchone()[0],
                                   'idempotency_key':'payments.operation_key UNIQUE'})
        by_role={op['role']:op for op in scenario['operations']}
        first=_process(conn,funcs,by_role['base'],scenario['policy'])
        _emit(events,_kind('base',first['outcome']),dict(first,connection_generation=1))
        _emit(events,'ACK_LOST',{'role':'base','operation_key':first['operation_key'],
                                 'committed_before_loss':first['paid'],'amount_cents':first['amount_cents'],
                                 'note':'acknowledgement dropped after the SQLite commit; rows stay durable'})
        conn.close()
        _emit(events,'CONNECTION_CLOSED',{'connection_generation':1})
        conn=sqlite3.connect(str(path))
        back=conn.execute('SELECT operation_key,attempt_id,amount_cents FROM payments ORDER BY seq').fetchall()
        restart={'rows_after_reopen':len(back),
                 'committed_row_visible_after_reopen':first['paid'] and any(r[0]==first['operation_key'] for r in back)}
        _emit(events,'REOPEN',{'connection_generation':2,'mechanism':'connection restart',
                               'rows_read_back':[{'operation_key':r[0],'attempt_id':r[1],'amount_cents':r[2]}
                                                 for r in back],
                               'stock_read_back':_observed(conn)['inventory'],
                               'retry_attempt_id':by_role['retry']['attempt_id']})
        for role in ('retry','sibling','other_tenant'):
            step=_process(conn,funcs,by_role[role],scenario['policy'])
            _emit(events,_kind(role,step['outcome']),dict(step,connection_generation=2))
        observed=_observed(conn)
        _emit(events,'FINAL_ROWS',{'payments':observed['payment_rows'],'inventory':observed['inventory']})
    except Exception as exc:  # a candidate runtime error is a failing report, never a pass
        detail={'error':type(exc).__name__,'detail':str(exc)[:300]}
        errors.append(detail);_emit(events,'ERROR',detail)
    finally:
        if conn is not None:
            try:conn.close()
            except sqlite3.Error:pass
    return observed,events,errors,restart

def replay(source,seed=117,database_path=None):
    """Run the committed-then-retried refund scenario on a real SQLite database.

    An unsupported source, a non-int seed or an already existing database file
    raises ValueError before any database work. A candidate runtime error
    inside the scenario produces a failing report instead.
    """
    _check_seed(seed)
    funcs=load_validated_source(source)  # validates the subset before any file is touched
    scenario=_scenario(seed)
    holder=None
    if database_path is None:
        holder=tempfile.TemporaryDirectory(prefix='ledger-replay-')
        path=Path(holder.name)/'ledger.sqlite3'
    else:
        path=Path(database_path)
    _create_exclusively(path)
    try:observed,events,errors,restart=_sequence(path,funcs,scenario)
    finally:
        if holder is not None:holder.cleanup()  # outputs are already collected in memory
    expected=_expected(scenario)
    diff=_differences(expected,observed)
    invariants=_invariants(scenario,expected,observed,diff,restart)
    replayed=next((e for e in events if e['data'].get('role')=='retry'),None)
    kept_stock=bool(replayed) and replayed['data']['stock_before']==replayed['data']['stock_after']
    return {'protocol':LEDGER_PROTOCOL,
            'passed':not errors and all(invariants.values()),
            # Deliberately blind to the sibling and cross-tenant outcomes: an
            # incomplete patch can pass this and still be wrong.
            'retry_only_passed':not errors and kept_stock and _settled_exactly(scenario,'base',expected,observed),
            'invariants':invariants,'events':events,'expected':expected,'observed':observed,
            'differences':diff,'errors':errors,'restart':restart,'scenario':scenario,'seed':seed,
            'source_sha256':_sha(source),
            'scenario_sha256':_sha(json.dumps(scenario,sort_keys=True,separators=(',',':'))),
            'database_path':str(path),'database_temporary':holder is not None,
            'synthetic':True,'no_production_changes':True,
            'claims':'one synthetic scenario; no empirical reliability or production safety claim'}
