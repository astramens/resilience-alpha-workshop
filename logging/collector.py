"""Push sanitized, deduplicated events. Checkpoint only after Loki acknowledges."""
import json,os,time,urllib.request
from collections import deque
from pathlib import Path
STATE=Path('/state/checkpoint.json')
def request(url,data=None):
    body=None if data is None else json.dumps(data).encode()
    req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=35) as response:
        raw=response.read(8*1024*1024)
        return json.loads(raw) if raw else None

def batch(snapshot,known,heartbeat):
    groups={};ids=[]
    for event in snapshot['events']:
        if event['id'] in known:continue
        service=event['service'];data=event['data'];kind=data['event']
        key=(service,kind)
        groups.setdefault(key,[]).append([event['timestamp'],json.dumps(data,separators=(',',':'))])
        ids.append(event['id'])
    if heartbeat:
        health={'event':'collection_status','observed':snapshot['observed'],'failed':snapshot['failed'],
                'missing':snapshot['missing'],'window_seconds':60,'tail_limit':1000}
        groups[('log-collector','collection_status')]=[[str(time.time_ns()),json.dumps(health)]]
    streams=[{'stream':{'job':'rearm_logs','service':service,'event':event},'values':sorted(values,key=lambda x:int(x[0]))}
             for (service,event),values in groups.items()]
    return {'streams':streams},ids

def main():
    try:history=deque(json.loads(STATE.read_text()),maxlen=20000)
    except (OSError,ValueError):history=deque(maxlen=20000)
    last_heartbeat=0
    while True:
        try:
            snapshot=request('http://log-gateway:9080/snapshot')
            heartbeat=time.monotonic()-last_heartbeat>=20
            payload,ids=batch(snapshot,set(history),heartbeat)
            if payload['streams']:request('http://loki:3100/loki/api/v1/push',payload)
            history.extend(ids)
            temporary=STATE.with_suffix('.tmp');temporary.write_text(json.dumps(list(history)));temporary.replace(STATE)
            if heartbeat:
                last_heartbeat=time.monotonic()
                print(json.dumps({'event':'collection_status','observed':len(snapshot['observed']),
                                  'failed':len(snapshot['failed']),'missing':len(snapshot['missing'])}),flush=True)
        except Exception as exc:
            # Do not print request bodies, URLs or remote exception messages.
            print(json.dumps({'event':'collection_failed','error_type':type(exc).__name__}),flush=True)
        time.sleep(5)
if __name__=='__main__':main()
