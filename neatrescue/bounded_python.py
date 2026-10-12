"""Resource-bounded evaluator for the validated pure-Python adapter subset.

Not a general Python sandbox. No candidate bytecode is exec'd, no imports,
files, arbitrary attributes, loops or unknown calls. Semantics match the
supported expression/statement subset; size and step ceilings are explicit.
"""
import ast
import operator

BUILTINS={'min':min,'max':max,'str':str,'int':int,'len':len,'bool':bool}
CMP={ast.Eq:operator.eq,ast.NotEq:operator.ne,ast.Lt:operator.lt,
     ast.LtE:operator.le,ast.Gt:operator.gt,ast.GtE:operator.ge,ast.Is:operator.is_,ast.IsNot:operator.is_not}


def bounded(value, budget=None):
    if budget is None:budget=[512]
    budget[0]-=1
    if budget[0]<0:raise ValueError('Value structure exceeds sandbox limit')
    if value is None or type(value) is bool:return value
    if type(value) is int:
        if abs(value)>10**12:raise ValueError('Integer exceeds sandbox limit')
        return value
    if type(value) is str:
        if len(value)>1024:raise ValueError('String exceeds sandbox limit')
        return value
    if type(value) in (list,tuple,dict):
        if len(value)>128:raise ValueError('Collection exceeds sandbox limit')
        values=value.values() if type(value) is dict else value
        for v in values:bounded(v,budget)
        return value
    raise ValueError('Unsupported sandbox value '+type(value).__name__)


class Returned(Exception):
    def __init__(self,value):self.value=value


class Evaluator:
    def __init__(self,env):self.env=env;self.steps=0
    def tick(self):
        self.steps+=1
        if self.steps>2000:raise ValueError('Evaluation step limit exceeded')
    def expr(self,n):
        self.tick()
        if isinstance(n,ast.Constant):return bounded(n.value)
        if isinstance(n,ast.Name):return bounded(self.env[n.id])
        if isinstance(n,(ast.List,ast.Tuple)):
            v=[self.expr(x) for x in n.elts]
            return bounded(tuple(v) if isinstance(n,ast.Tuple) else v)
        if isinstance(n,ast.Subscript):return bounded(self.expr(n.value)[self.expr(n.slice)])
        if isinstance(n,ast.BinOp):
            a,b=self.expr(n.left),self.expr(n.right)
            if isinstance(n.op,ast.Add):
                if type(a) in (str,list,tuple) and type(a) is type(b):
                    limit=1024 if type(a) is str else 128
                    if len(a)+len(b)>limit:raise ValueError('Concatenation exceeds sandbox limit')
                return bounded(a+b)
            if isinstance(n.op,ast.Sub):return bounded(a-b)
            raise ValueError('Unsupported operator')
        if isinstance(n,ast.UnaryOp):
            a=self.expr(n.operand)
            if isinstance(n.op,ast.Not):return not a
            if isinstance(n.op,ast.USub):return bounded(-a)
            raise ValueError('Unsupported unary operator')
        if isinstance(n,ast.BoolOp):
            val=None
            for part in n.values:
                val=self.expr(part)
                if isinstance(n.op,ast.And) and not val:return val
                if isinstance(n.op,ast.Or) and val:return val
            return val
        if isinstance(n,ast.Compare):
            prev=self.expr(n.left)
            for op,rhs in zip(n.ops,n.comparators):
                nxt=self.expr(rhs)
                if type(op) not in CMP:raise ValueError('Unsupported comparison')
                if not CMP[type(op)](prev,nxt):return False
                prev=nxt
            return True
        if isinstance(n,ast.IfExp):return self.expr(n.body if self.expr(n.test) else n.orelse)
        if isinstance(n,ast.Call):
            args=[self.expr(x) for x in n.args]
            if n.keywords:raise ValueError('Unsupported keyword call')
            if isinstance(n.func,ast.Name) and n.func.id in BUILTINS:
                return bounded(BUILTINS[n.func.id](*args))
            if isinstance(n.func,ast.Attribute) and n.func.attr=='get':
                obj=self.expr(n.func.value)
                if type(obj) is not dict:raise ValueError('get receiver must be a dictionary')
                return bounded(obj.get(*args))
            raise ValueError('Unsupported call')
        raise ValueError('Unsupported expression '+type(n).__name__)
    def statements(self,nodes):
        for n in nodes:
            self.tick()
            if isinstance(n,ast.Return):raise Returned(self.expr(n.value) if n.value is not None else None)
            if isinstance(n,ast.Assign):
                if len(n.targets)!=1 or not isinstance(n.targets[0],ast.Name):raise ValueError('Unsupported assignment')
                self.env[n.targets[0].id]=self.expr(n.value)
            elif isinstance(n,ast.If):self.statements(n.body if self.expr(n.test) else n.orelse)
            else:raise ValueError('Unsupported statement '+type(n).__name__)


def load_validated_source(source):
    """Called only AFTER blindbench.validate_source; validates again on entry."""
    from .blindbench import validate_source
    validate_source(source)
    tree=ast.parse(source)
    functions={}
    for node in tree.body:
        def call(*args,_function=node):
            names=[arg.arg for arg in _function.args.args]
            if len(args)!=len(names):raise ValueError('Wrong number of arguments')
            env={k:bounded(v) for k,v in zip(names,args)}
            evaluator=Evaluator(env)
            try:evaluator.statements(_function.body)
            except Returned as done:return bounded(done.value)
            return None
        functions[node.name]=call
    return functions
