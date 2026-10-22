"""Deterministic incident correlation for the REARM lab. No remediation capability."""
import json,math,os,sqlite3,threading,time,urllib.request,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from datetime import datetime,timezone

RULES={
 'backend_down':('critical','backend','API et base indisponibles'),
 'auth_down':('critical','auth','Authentification indisponible'),
 'store_down':('critical','store','Boutique via WAF indisponible'),
 'remediation_down':('critical','remediation','Service de remédiation indisponible'),
 'monitoring_gap':('warning','monitoring','Mesures de disponibilité incomplètes'),
 'logging_gap':('warning','logging','Collecte des journaux incomplète'),
 'waf_burst':('warning','waf','Refus WAF répétés'),
 'access_burst':('warning','waf','Refus d’accès répétés'),
 'rate_burst':('warning','waf','Limitations HTTP 429 répétées'),
 'server_errors':('critical','store','Erreurs HTTP 5xx répétées'),
}
PROBES={
 ('rearm_http','http://backend:8000/health'):'backend_down',
 ('rearm_http','http://auth:8001/health'):'auth_down',
 ('rearm_http','http://remediation:9000/health'):'remediation_down',
 ('rearm_public','http://edge:8080/api/shop/products'):'store_down',
}
COUNTS={'waf_burst':('waf_block',5,2),'access_burst':('access_denied',5,2),
        'rate_burst':('rate_limited',3,1),'server_errors':('http_5xx',3,1)}
SERVICES=frozenset(('edge','waf','frontend','backend','auth','ai-engine','remediation','docker-guard'))
POLL_SECONDS=15

def fetch(url,data=None):
    body=None if data is None else json.dumps(data).encode()
    req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=4) as r:
        body=r.read(1024*1024+1)
        if len(body)>1024*1024:raise ValueError('Response too large')
        return json.loads(body) if body else None

def prom():
    labels='{job=~"rearm_http|rearm_public"}'
    expr=f'(probe_success{labels} and (timestamp(probe_success{labels}) > time()-45)) or on(__name__,job,instance) (up{labels} and (timestamp(up{labels}) > time()-45))'
    data=fetch('http://prometheus:9090/api/v1/query?'+urllib.parse.urlencode({'query':expr}))
    if data.get('status')!='success' or data['data']['resultType']!='vector':raise ValueError('Prometheus response')
    return data['data']['result']

def loki(expr,range_query=False):
    args={'query':expr}
    endpoint='query'
    if range_query:
        endpoint='query_range';args.update(start=str(time.time_ns()-60_000_000_000),end=str(time.time_ns()),limit=1,direction='backward')
    data=fetch('http://loki:3100/loki/api/v1/'+endpoint+'?'+urllib.parse.urlencode(args))
    if data.get('status')!='success':raise ValueError('Loki response')
    return data['data']

def probe_values(rows):
    series={}
    for row in rows:
        m=row.get('metric',{});key=(m.get('job'),m.get('instance'))
        if key not in PROBES or m.get('__name__') not in ('up','probe_success'):continue
        value=float(row['value'][1])
        if value not in (0,1):continue
        series[(key,m['__name__'])]=value
    result={}
    for key,rule in PROBES.items():
        if series.get((key,'up'))==1 and (key,'probe_success') in series:
            result[rule]=series[(key,'probe_success')]==0
        else:result[rule]=None
    return result

def logs_complete(data,now):
    if data.get('resultType')!='streams':return False
    values=[(int(stamp),line) for stream in data.get('result',[]) for stamp,line in stream.get('values',[])]
    if not values:return False
    stamp,line=max(values)
    if not 0<=now-stamp/1e9<=45:return False
    value=json.loads(line)
    return value.get('event')=='collection_status' and value.get('failed')==[] and value.get('missing')==[] and set(value.get('observed',[]))==SERVICES

def scalar_count(data):
    if data.get('resultType')!='vector':raise ValueError('Expected vector')
    rows=data['result']
    if not rows:return 0.0
    if len(rows)!=1:raise ValueError('Expected one aggregate')
    count=float(rows[0]['value'][1])
    if not math.isfinite(count) or not 0<=count<=1e9:raise ValueError('Invalid count')
    return count

def observe():
    values={};evidence={}
    try:
        values.update(probe_values(prom()))
        values['monitoring_gap']=any(values[k] is None for k in PROBES.values())
    except (OSError,ValueError,TypeError,KeyError):
        values.update({key:None for key in PROBES.values()});values['monitoring_gap']=True
    try:complete=logs_complete(loki('{job="rearm_logs",event="collection_status"}',True),time.time())
    except (OSError,ValueError,TypeError,KeyError):complete=False
    values['logging_gap']=not complete
    for rule,(event,high,low) in COUNTS.items():
        values[rule]=None
        if not complete:continue
        try:
            expr='sum(count_over_time({job="rearm_logs",service="waf",event="'+event+'"}[1m]))'
            count=scalar_count(loki(expr));evidence[rule]=count
            # Hysteresis: in-between values neither open nor resolve an incident.
            values[rule]=True if count>=high else False if count<=low else None
        except (OSError,ValueError,TypeError,KeyError):values['logging_gap']=True
    return values,evidence

class Store:
    def __init__(self,path):
        self.db=sqlite3.connect(path,check_same_thread=False);self.lock=threading.RLock()
        self.db.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY,rule TEXT NOT NULL,opened REAL NOT NULL,resolved REAL);
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_per_rule ON incidents(rule) WHERE resolved IS NULL;
        CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY,payload TEXT NOT NULL,stamp TEXT NOT NULL,sent INTEGER NOT NULL DEFAULT 0);
        ''');self.db.commit();self.streaks={};self.last_cycle=0
    def active(self,rule):
        return self.db.execute('SELECT id FROM incidents WHERE rule=? AND resolved IS NULL',(rule,)).fetchone()
    def transition(self,rule,bad,evidence,now):
        if rule not in RULES:raise ValueError('Unknown rule')
        if bad is not True and bad is not False and bad is not None:raise ValueError('Invalid observation')
        if bad is None:self.streaks[rule]=(None,0);return
        prior,count=self.streaks.get(rule,(None,0));count=count+1 if prior is bad else 1;self.streaks[rule]=(bad,count)
        if count<2:return
        with self.lock,self.db:
            active=self.active(rule)
            if bad and active is None:
                cur=self.db.execute('INSERT INTO incidents(rule,opened) VALUES (?,?)',(rule,now));ident=cur.lastrowid;state='opened'
            elif not bad and active is not None:
                ident=active[0];self.db.execute('UPDATE incidents SET resolved=? WHERE id=?',(now,ident));state='resolved'
            else:return
            severity,scope,title=RULES[rule]
            event={'event':'incident_'+state,'incident_id':ident,'rule':rule,'severity':severity,'scope':scope,
                   'observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),'confirmation_samples':2,'repair_executed':False}
            value=evidence.get(rule)
            if type(value) in (int,float) and math.isfinite(value):event['count_last_minute']=value
            self.db.execute('INSERT INTO outbox(payload,stamp) VALUES (?,?)',(json.dumps(event,ensure_ascii=True),str(int(now*1e9))))
            print(json.dumps({'event':event['event'],'rule':rule,'incident_id':ident,'repair_executed':False}),flush=True)
    def cycle(self,values,evidence,now):
        for rule in RULES:self.transition(rule,values.get(rule),evidence,now)
        with self.lock,self.db:
            self.last_cycle=now
            # Keep seven days of resolved history. Open incidents are never aged out.
            self.db.execute('DELETE FROM incidents WHERE resolved IS NOT NULL AND resolved<?',(now-7*86400,))
            self.db.execute('DELETE FROM outbox WHERE sent!=0 AND CAST(stamp AS INTEGER)<?',(int((now-7*86400)*1e9),))
    def flush(self):
        with self.lock:rows=self.db.execute('SELECT id,payload,stamp FROM outbox WHERE sent=0 ORDER BY id LIMIT 100').fetchall()
        if not rows:return
        # Loki rejects very old samples. Keep outbox history but mark stale events as expired;
        # authoritative open/resolved incident state remains in SQLite and Prometheus.
        fresh=[row for row in rows if int(row[2])>=time.time_ns()-3500_000_000_000]
        if fresh:
            values=[[stamp,payload] for ident,payload,stamp in fresh]
            fetch('http://loki:3100/loki/api/v1/push',{'streams':[{'stream':{'job':'rearm_incidents','service':'incident-engine'},'values':values}]})
        with self.lock,self.db:
            self.db.executemany('UPDATE outbox SET sent=? WHERE id=?',[(1 if row in fresh else 2,row[0]) for row in rows])
    def metrics(self):
        with self.lock:
            lines=['# TYPE rearm_incident_engine_last_cycle_seconds gauge',f'rearm_incident_engine_last_cycle_seconds {self.last_cycle}',
                   '# TYPE rearm_incident_active gauge','# TYPE rearm_incident_source_known gauge']
            for rule,(severity,scope,title) in RULES.items():
                active=int(self.active(rule) is not None)
                known=int(self.streaks.get(rule,(None,0))[0] is not None)
                labels=f'rule="{rule}",severity="{severity}",scope="{scope}"'
                lines.extend([f'rearm_incident_active{{{labels}}} {active}',f'rearm_incident_source_known{{rule="{rule}"}} {known}'])
            pending=self.db.execute('SELECT COUNT(*) FROM outbox WHERE sent=0').fetchone()[0]
            expired=self.db.execute('SELECT COUNT(*) FROM outbox WHERE sent=2').fetchone()[0]
            lines.extend(['# TYPE rearm_incident_outbox_pending gauge',f'rearm_incident_outbox_pending {pending}',
                          '# TYPE rearm_incident_outbox_expired gauge',f'rearm_incident_outbox_expired {expired}'])
            return '\n'.join(lines)+'\n'

def handler(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path=='/metrics':status=200;body=store.metrics().encode();kind='text/plain; version=0.0.4'
            elif self.path=='/health':
                recent=0<=time.time()-store.last_cycle<60;status=200 if recent else 503;body=json.dumps({'cycle_recent':recent}).encode();kind='application/json'
            else:status=404;body=b'not found';kind='text/plain'
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    return Handler

def main():
    store=Store('/state/incidents.sqlite3')
    server=ThreadingHTTPServer(('0.0.0.0',9108),handler(store));threading.Thread(target=server.serve_forever,daemon=True).start()
    while True:
        started=time.monotonic()
        try:
            values,evidence=observe();store.cycle(values,evidence,time.time());store.flush()
        except Exception as exc:
            print(json.dumps({'event':'incident_engine_error','error_type':type(exc).__name__}),flush=True)
        time.sleep(max(1,POLL_SECONDS-(time.monotonic()-started)))
if __name__=='__main__':main()
