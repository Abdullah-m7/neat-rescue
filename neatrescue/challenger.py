"""One-shot separate-context challenger. No access to repair templates or solver runs."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import time
from .blindbench import CONTRACT, validate_source, evaluate
from .investigator import canonical,load_local_environment

ROOT=Path(__file__).resolve().parents[1]
SYSTEM='''You are a red-team test author, not the repair agent. Create a NEW subtly broken
Python tool adapter from the public contract. Another isolated agent will attempt to repair it.
You are not given any existing fault templates, tests, reference solution, or repair transcript.
Return JSON with faulty_source and private_fault_notes. The source must define exactly eligible(order,policy),
refund_cents(order), operation_key(event), inventory_after(stock,qty,already_applied).
Inject plausible errors in at least TWO different functions. Keep functions short.
Do NOT use deliberately constant answers, hardcoded IDs, comments that identify the bugs, or a deny-all shortcut.
Supported Python only: if/else, return, up to 8 local assignments/function, comparisons/and/or,
+, -, unary -, not, dictionary subscripts/.get, tuples/lists, min/max/str/int/len/bool.
No annotations, decorators, imports, loops, comprehensions, lambda, globals, print, docstrings,
f-strings, multiplication, power, external calls or attribute access other than parameter.get.
Only alphanumeric user identifiers; integers in inputs; output operation_key must be a string.
The notes explain your intended defects but are NOT shared with the repair agent.
'''


def main():
    load_local_environment()
    import neatlogs,os
    key=os.environ.get('NEATLOGS_API_KEY','').strip()
    neatlogs.init(api_key=key or None,endpoint='https://ingest.neatlogs.com',
                  workflow_name='generate-blind-challenge',instrumentations=[],disable_export=not bool(key))
    out=ROOT/'.local/challenger_v1';out.mkdir(exist_ok=False)
    workspace=out/'empty_workspace';workspace.mkdir()
    subprocess.run(['git','init','-b','main',str(workspace)],check=True,capture_output=True)
    schema={'type':'object','properties':{'faulty_source':{'type':'string','maxLength':6000},
        'private_fault_notes':{'type':'array','items':{'type':'string'}}},
        'required':['faulty_source','private_fault_notes'],'additionalProperties':False}
    payload={'public_contract':CONTRACT,'task':'Invent plausible source-level faults; return only the required JSON.'}
    (out/'public_request.json').write_text(json.dumps(payload,indent=2))
    cmd=[str(Path.home()/'.npm-global/bin/claude'),'-p','--output-format','json','--json-schema',canonical(schema),
         '--tools','','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--setting-sources','project',
         '--permission-mode','dontAsk','--system-prompt',SYSTEM,'--effort','medium','--max-turns','3']
    started=time.monotonic()
    @neatlogs.span(kind='AGENT',name='isolated-challenger',capture_input=True,capture_output=True)
    def generate(request):
        r=subprocess.run(cmd,input=canonical(request),cwd=str(workspace),capture_output=True,text=True,timeout=100)
        (out/'provider_response.json').write_text(r.stdout)
        (out/'stderr.txt').write_text(r.stderr)
        if r.returncode:raise RuntimeError('Challenger CLI failed')
        envelope=json.loads(r.stdout)
        if envelope.get('is_error'):raise RuntimeError('Challenger model failed')
        result=envelope.get('structured_output')
        if result is None:result=json.loads(envelope['result'])
        return result
    try:
        with neatlogs.trace('generate-blind-challenge',kind='WORKFLOW'):
            result=generate(payload)
            validate_source(result['faulty_source'])
            check=evaluate(result['faulty_source'],seed=923171,count=80)
            (out/'challenger_source.py').write_text(result['faulty_source'])
            (out/'private_fault_notes.json').write_text(json.dumps(result['private_fault_notes'],indent=2))
            families=[k for k,v in check['by_family'].items() if v['failures']>0]
            report={'status':'CHALLENGE_READY' if len(families)>=2 else 'INADEQUATE_CHALLENGE',
                'source_sha256':hashlib.sha256(result['faulty_source'].encode()).hexdigest(),
                'failing_family_count':len(families),'baseline_check':check,
                'generation_seconds':round(time.monotonic()-started,3),
                'challenger_context':'Only public contract; no template bank, tests, reference, or solver transcript',
                'solver_must_not_receive_private_notes':True}
            (out/'report.json').write_text(json.dumps(report,indent=2));print(canonical(report),flush=True)
            return 0 if report['status']=='CHALLENGE_READY' else 2
    finally:neatlogs.flush(timeout_millis=5000);neatlogs.shutdown(timeout_millis=5000)

if __name__=='__main__':raise SystemExit(main())
