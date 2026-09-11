#!/usr/bin/env python3
"""Search ArcGIS Online public items for New Orleans Streetwise/flood data sources."""
from __future__ import annotations
import json, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

OUT=Path('data/discovery/arcgis_online_search.json')
QUERIES=[
    'Streetwise New Orleans',
    'Streetwise NOLA',
    'New Orleans flood 21F',
    'New Orleans Flood Events',
    'New Orleans street flooding',
    'Hyfi New Orleans',
    'nola flood',
    'nola 311 flooding',
]

def get(url:str)->dict[str,Any]:
    req=urllib.request.Request(url,headers={'User-Agent':'Streetwise-NOLA-Forensics/1.0'})
    with urllib.request.urlopen(req,timeout=20) as r:
        return json.loads(r.read().decode('utf-8','replace'))

def search(q:str)->list[dict[str,Any]]:
    params={'f':'json','q':q,'num':100,'sortField':'modified','sortOrder':'desc'}
    d=get('https://www.arcgis.com/sharing/rest/search?'+urllib.parse.urlencode(params))
    keep=[]
    for x in d.get('results') or []:
        keep.append({k:x.get(k) for k in ('id','owner','title','type','url','access','created','modified','tags','description','snippet')})
    return keep

def item_data(item_id:str)->Any:
    try:
        return get(f'https://www.arcgis.com/sharing/rest/content/items/{item_id}/data?f=json')
    except Exception as e:
        return {'error':str(e)}

def main()->int:
    results=[]; seen=set()
    for q in QUERIES:
        for item in search(q):
            key=item.get('id')
            if key in seen: continue
            seen.add(key)
            blob=json.dumps(item,default=str).lower()
            if not any(k in blob for k in ('flood','streetwise','hyfi','21f','311','new orleans','nola')):
                continue
            # Pull data JSON for web maps/apps because it frequently exposes
            # underlying operational layer URLs even when the item itself does not.
            if item.get('type') in ('Web Map','Web Mapping Application','Dashboard','Experience Builder'):
                item['data']=item_data(str(key))
            results.append(item)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({'queries':QUERIES,'count':len(results),'items':results},indent=2,sort_keys=True)+'\n')
    print('found',len(results),'candidate items')
    return 0
if __name__=='__main__': raise SystemExit(main())
