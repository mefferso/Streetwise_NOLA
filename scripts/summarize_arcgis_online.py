#!/usr/bin/env python3
from __future__ import annotations
import json,re
from pathlib import Path
from typing import Any
SRC=Path('data/discovery/arcgis_online_search.json')
OUT=Path('data/discovery/arcgis_online_summary.json')
URL_RE=re.compile(r'https?://[^\s\"\'<>]+',re.I)
TERMS=('mapserver','featureserver','streetwise','flood','hyfi','eocgis','gis.nola','21f','311')

def strings(x:Any):
    if isinstance(x,str): yield x
    elif isinstance(x,dict):
        for v in x.values(): yield from strings(v)
    elif isinstance(x,list):
        for v in x: yield from strings(v)

def main()->int:
    d=json.loads(SRC.read_text())
    items=[]; all_eps=set()
    for it in d.get('items',[]):
        eps=set()
        for s in strings(it):
            sl=s.lower()
            if any(t in sl for t in TERMS):
                for u in URL_RE.findall(s.replace('\\/','/')):
                    eps.add(u.rstrip('),];'))
        for u in eps: all_eps.add(u)
        items.append({k:it.get(k) for k in ('id','title','owner','type','url','modified','access')}|{'endpoints':sorted(eps)})
    out={'source_count':d.get('count'),'item_count':len(items),'items':items,'all_endpoints':sorted(all_eps)}
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print('items',len(items),'endpoints',len(all_eps))
    return 0
if __name__=='__main__':raise SystemExit(main())
