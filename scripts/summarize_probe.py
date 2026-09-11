#!/usr/bin/env python3
import json
from pathlib import Path
src=Path('data/discovery/known_sources_probe.json')
out=Path('data/discovery/known_sources_summary.json')
data=json.loads(src.read_text())
summary={'cutoff':data.get('cutoff'),'services':[]}
for svc in data.get('services',[]):
    s={'url':svc.get('url'),'errors':svc.get('errors',[]),'layers':[]}
    for layer in svc.get('layers',[]):
        l={'id':layer.get('id'),'name':layer.get('name'),'total_count':layer.get('total_count'),'errors':layer.get('errors',[]),'date_fields':[]}
        for p in layer.get('date_fields',[]):
            l['date_fields'].append({k:p.get(k) for k in ('field','min','max','post_cutoff_count','stats_error','post_cutoff_error') if k in p})
        s['layers'].append(l)
    summary['services'].append(s)
out.write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print(out)
