"""Allowlisted telemetry. Never retain raw messages, actors, headers or request bodies."""
import json, re, math

SERVICES = frozenset(('edge','waf','frontend','backend','auth','ai-engine','remediation','docker-guard'))
EVENTS = frozenset(('lab_redos_armed','lab_redos_started','lab_safety_timeout','lab_regex_returned','observation','model_calibrated','recovery_request_failed','recovery_unconfirmed',
 'ansible_repair_completed','ansible_repair_failed','health_recovery_reported','business_recovery_reported','recovery_reported','recovery_business_verified','scoped_backend_restart','database_request_failed',
 'order_created','order_status','payment_confirmed','product_created','product_updated','customer_access'))
PATHS = frozenset(('/health','/metrics','/internal/metrics','/internal/business-probe',
 '/api/auth/login','/api/auth/logout','/api/auth/me','/api/shop/products',
 '/api/shop/payments/webhook','/api/device/led','/alerts'))
ACCESS = re.compile(r'"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) ([^\s"]+) HTTP/[0-9.]+" ([1-5][0-9]{2})(?:\s|$)')

def route(value):
    path = value.split('?',1)[0]
    if path in PATHS: return path
    if path.startswith('/api/'): return '/api/other'
    return '/other'

def http_event(service, method, path, status, upstream=None):
    if method not in ('GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS') or type(status) is not int or not 100<=status<=599:
        return None
    event = 'http_request'
    if status>=500: event='http_5xx'
    elif status==429: event='rate_limited'
    elif status in (401,403): event='access_denied'
    # A WAF 403 without upstream response is evidence of rejection before the app.
    if service=='waf' and status==403 and upstream in ('','-'): event='waf_block'
    return {'event':event,'method':method,'route':route(path),'status':status}

def sanitize(service, message):
    if service not in SERVICES or len(message)>16384: return None
    try: data=json.loads(message)
    except (ValueError,TypeError): data=None
    if isinstance(data,dict):
        if service=='waf' and data.get('event')=='waf_http':
            if not isinstance(data.get('path'),str): return None
            return http_event(service,data.get('method'),data['path'],data.get('status'),data.get('upstream_status'))
        event=data.get('event')
        if not isinstance(event,str) or event not in EVENTS: return None
        result={'event':event}
        if event in ('recovery_reported','recovery_business_verified') and re.fullmatch(r'INC-[a-f0-9]{12}',str(data.get('ref',''))):
            result['ref']=data['ref']
        # Only bounded numeric/boolean facts. NO arbitrary strings, reason, actor, target or container ID.
        for name in ('playbook_success','check_mode','healthy','ml_ready','ml_anomaly','business_recovery_verified','technical_recovery_verified'):
            if type(data.get(name)) is bool: result[name]=data[name]
        for name in ('probe_latency_ms','error_rate','health_failures','baseline_samples','samples','http_status'):
            value=data.get(name)
            if type(value) in (int,float) and math.isfinite(value) and 0<=value<=1e9: result[name]=value
        return result
    if service == 'waf':
        return None
    match=ACCESS.search(message)
    if match:
        method,path,status=match.groups()
        return http_event(service,method,path,int(status))
    return None
