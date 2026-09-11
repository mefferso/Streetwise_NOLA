#!/usr/bin/env python3
"""Focused forensic probe of known/likely Streetwise flood endpoints."""
from __future__ import annotations
import json, ssl, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

ssl._create_default_https_context = ssl._create_unverified_context
OUT = Path('data/discovery/known_sources_probe.json')
CUTOFF = "2026-07-12 00:00:00"
SERVICES = [
    'https://gis.nola.gov/arcgis/rest/services/Staging/Flood_Events/MapServer',
    'https://gis.nola.gov/arcgis/rest/services/dev/WhereYaFloodin/MapServer',
    'https://eocgis.nola.gov:6443/arcgis/rest/services/Streetwise/Streetwise_Live/MapServer',
    'https://eocgis.nola.gov:6443/arcgis/rest/services/Rainwater/Flooding/MapServer',
]

def get(url:str)->dict[str,Any]:
    req=urllib.request.Request(url,headers={'User-Agent':'Streetwise-NOLA-Probe/1.0'})
    with urllib.request.urlopen(req,timeout=10) as r:
        d=json.loads(r.read().decode('utf-8','replace'))
    if isinstance(d,dict) and d.get('error'): raise RuntimeError(json.dumps(d['error']))
    return d

def qp(url:str, params:dict[str,Any])->dict[str,Any]:
    return get(url+'?'+urllib.parse.urlencode(params))

def q(layer:str, params:dict[str,Any])->dict[str,Any]:
    return qp(layer+'/query',params)

def inspect_service(url:str)->dict[str,Any]:
    o={'url':url,'errors':[],'layers':[]}
    try: meta=qp(url,{'f':'pjson'})
    except Exception as e: o['errors'].append(str(e)); return o
    o['mapName']=meta.get('mapName'); o['serviceDescription']=meta.get('serviceDescription')
    for ent in (meta.get('layers') or [])+(meta.get('tables') or []):
        lid=ent.get('id'); lu=f'{url}/{lid}'; lo={'id':lid,'name':ent.get('name'),'errors':[],'date_fields':[]}
        try: lm=qp(lu,{'f':'pjson'})
        except Exception as e: lo['errors'].append(str(e)); o['layers'].append(lo); continue
        fields=lm.get('fields') or []
        lo['fields']=[{'name':f.get('name'),'type':f.get('type')} for f in fields]
        try: lo['total_count']=q(lu,{'f':'json','where':'1=1','returnCountOnly':'true'}).get('count')
        except Exception as e: lo['errors'].append('count: '+str(e))
        candidates=[]
        for f in fields:
            n=str(f.get('name') or ''); l=n.lower()
            if f.get('type')=='esriFieldTypeDate' or any(k in l for k in ('time','date','open','close','create','update')): candidates.append(n)
        for fld in candidates[:8]:
            p={'field':fld}
            try:
                st=q(lu,{'f':'json','where':'1=1','returnGeometry':'false','outStatistics':json.dumps([
                    {'statisticType':'min','onStatisticField':fld,'outStatisticFieldName':'minv'},
                    {'statisticType':'max','onStatisticField':fld,'outStatisticFieldName':'maxv'}])})
                fs=st.get('features') or []
                if fs:
                    a=fs[0].get('attributes') or {}; p['min']=a.get('minv'); p['max']=a.get('maxv')
            except Exception as e: p['stats_error']=str(e)
            try:
                p['post_cutoff_count']=q(lu,{'f':'json','where':f"{fld} >= timestamp '{CUTOFF}'",'returnCountOnly':'true'}).get('count')
            except Exception as e: p['post_cutoff_error']=str(e)
            if p.get('post_cutoff_count'):
                try:
                    sm=q(lu,{'f':'json','where':f"{fld} >= timestamp '{CUTOFF}'",'outFields':'*','returnGeometry':'true','outSR':'4326','orderByFields':fld+' DESC','resultRecordCount':'10'})
                    p['sample']=sm.get('features') or []
                except Exception as e: p['sample_error']=str(e)
            lo['date_fields'].append(p)
        o['layers'].append(lo)
    return o

def main()->int:
    result={'cutoff':CUTOFF,'services':[]}
    for u in SERVICES:
        result['services'].append(inspect_service(u))
        if u.endswith('/MapServer'):
            result['services'].append(inspect_service(u[:-9]+'FeatureServer'))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print('wrote',OUT)
    return 0
if __name__=='__main__': raise SystemExit(main())
