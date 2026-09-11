#!/usr/bin/env python3
"""Probe alternate flood endpoints referenced by the live Streetwise application."""
from __future__ import annotations
import json, ssl, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

OUT=Path('data/discovery/live_app_endpoint_probe.json')
ssl._create_default_https_context=ssl._create_unverified_context
ENDPOINTS=[
 ('legacy_21f_12hours','http://cop.nola.gov:6080/arcgis/rest/services/21f_12hours/MapServer/0'),
 ('legacy_traffic','http://cop.nola.gov:6080/arcgis/rest/services/Traffic_Incident/MapServer/0'),
 ('hyfi','https://eocgis.nola.gov/server/rest/services/HYFI/MapServer/0'),
 ('flood_alerts','https://gis.nola.gov/apps/flood_alerts/api/get_alerts'),
 ('underpass','https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/FWS_WaterLevel/MapServer/0'),
]

def fetch(url:str,timeout:int=15)->tuple[int,str,str]:
    req=urllib.request.Request(url,headers={'User-Agent':'Streetwise-NOLA-Forensics/1.0'})
    ctx=ssl._create_unverified_context() if url.startswith('https://') else None
    try:
        with urllib.request.urlopen(req,timeout=timeout,context=ctx) as r:
            raw=r.read().decode('utf-8','replace')
            return int(getattr(r,'status',200)),str(r.headers.get('content-type','')),raw
    except Exception as e:
        return 0,'',repr(e)

def maybe_json(raw:str)->Any:
    try:return json.loads(raw)
    except:return None

def main()->int:
    result={'endpoints':[]}
    for name,url in ENDPOINTS:
        rec={'name':name,'url':url}
        target=url
        if 'MapServer/' in url:
            target=url+('?f=pjson' if '?' not in url else '&f=pjson')
        status,ctype,raw=fetch(target)
        rec['status']=status; rec['content_type']=ctype; rec['body_preview']=raw[:1500]
        data=maybe_json(raw)
        if isinstance(data,dict):
            rec['json_keys']=sorted(data.keys())
            for key in ('name','type','geometryType','maxRecordCount','displayField','fields','features','error'):
                if key in data: rec[key]=data[key]
        # If this is an ArcGIS layer and metadata succeeded, query rows and inspect dates.
        if status and isinstance(data,dict) and 'MapServer/' in url and not data.get('error'):
            qurl=url+'/query?'+urllib.parse.urlencode({'f':'json','where':'1=1','outFields':'*','returnGeometry':'true','outSR':'4326','resultRecordCount':'50'})
            qs,qc,qr=fetch(qurl)
            rec['query_status']=qs; rec['query_preview']=qr[:4000]
            qj=maybe_json(qr)
            if isinstance(qj,dict):
                rec['query_feature_count']=len(qj.get('features') or [])
                rec['query_exceededTransferLimit']=qj.get('exceededTransferLimit')
                rec['query_error']=qj.get('error')
        result['endpoints'].append(rec)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(OUT)
    return 0
if __name__=='__main__':raise SystemExit(main())
