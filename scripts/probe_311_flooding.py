#!/usr/bin/env python3
"""Probe New Orleans 311 open data for flood-related requests during archive gap."""
from __future__ import annotations
import json, urllib.parse, urllib.request
from pathlib import Path

OUT=Path('data/discovery/311_flood_probe.json')
BASE='https://data.nola.gov/resource/2jgv-pqrq.json'
START='2026-07-12T00:00:00.000'
END='2026-09-11T23:59:59.999'

def get(params):
    url=BASE+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={'User-Agent':'Streetwise-NOLA-Forensics/1.0'})
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.loads(r.read().decode('utf-8','replace'))

def main()->int:
    # First enumerate all flood-related type/reason pairs in the gap.
    where=(f"date_created between '{START}' and '{END}' and "
           "(lower(request_type) like '%flood%' or lower(request_reason) like '%flood%')")
    groups=get({
        '$select':'request_type,request_reason,count(*) as n,min(date_created) as first,max(date_created) as last',
        '$where':where,
        '$group':'request_type,request_reason',
        '$order':'n desc',
        '$limit':'500'
    })
    # Retrieve actual matching rows; this is diagnostic and capped generously.
    rows=get({
        '$select':'service_request,request_type,request_reason,date_created,date_modified,case_close_date,request_status,responsible_agency,final_address,address_councildis,final_x,final_y,latitude,longitude',
        '$where':where,
        '$order':'date_created asc',
        '$limit':'5000'
    })
    # Also inspect drainage requests, because local flooding is often classified
    # as drainage rather than literally containing the word "flood".
    drainage_where=(f"date_created between '{START}' and '{END}' and "
                    "(lower(request_type) like '%drain%' or lower(request_reason) like '%drain%')")
    drainage_groups=get({
        '$select':'request_type,request_reason,count(*) as n,min(date_created) as first,max(date_created) as last',
        '$where':drainage_where,
        '$group':'request_type,request_reason',
        '$order':'n desc',
        '$limit':'500'
    })
    out={
        'dataset':'311 OPCD Calls (2012-Present)',
        'dataset_id':'2jgv-pqrq',
        'period':{'start':START,'end':END},
        'flood_group_count':len(groups),
        'flood_groups':groups,
        'flood_row_count':len(rows),
        'flood_rows':rows,
        'drainage_group_count':len(drainage_groups),
        'drainage_groups':drainage_groups,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print('flood rows',len(rows),'drainage groups',len(drainage_groups))
    return 0
if __name__=='__main__': raise SystemExit(main())
