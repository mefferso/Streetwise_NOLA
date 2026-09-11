#!/usr/bin/env python3
"""Inspect the live streetwise.nola.gov app and extract public data endpoints."""
from __future__ import annotations
import html, json, re, ssl, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

BASE='https://streetwise.nola.gov/'
OUT=Path('data/discovery/live_streetwise_inspection.json')
URL_RE=re.compile(r'https?://[^\"\'<>\\\s]+',re.I)
SCRIPT_RE=re.compile(r'<script[^>]+src=[\"\']([^\"\']+)[\"\']',re.I)
INTEREST=('arcgis','mapserver','featureserver','hyfi','flood','streetwise','eocgis','gis.nola','api')
SSL_CONTEXT=ssl._create_unverified_context()

def fetch_text(url:str)->str:
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 Streetwise-NOLA-Forensics/1.1'})
    with urllib.request.urlopen(req,timeout=25,context=SSL_CONTEXT) as r:
        return r.read().decode('utf-8','replace')

def interesting_urls(text:str)->list[str]:
    vals=[]
    for raw in URL_RE.findall(text.replace('\\/','/')):
        u=html.unescape(raw).rstrip(');,]')
        if any(k in u.lower() for k in INTEREST): vals.append(u)
    for pat in (r'[\"\']([^\"\']*(?:MapServer|FeatureServer|arcgis|hyfi|flood)[^\"\']*)[\"\']',):
        for m in re.finditer(pat,text,re.I):
            v=m.group(1)
            if len(v)<500: vals.append(v)
    return sorted(set(vals))

def main()->int:
    out:dict[str,Any]={'base':BASE,'errors':[],'html_endpoints':[],'scripts':[]}
    try: page=fetch_text(BASE)
    except Exception as e:
        out['errors'].append('page: '+str(e)); page=''
    out['html_endpoints']=interesting_urls(page)
    srcs=[]
    for src in SCRIPT_RE.findall(page):
        srcs.append(urllib.parse.urljoin(BASE,html.unescape(src)))
    for x in ('app.js','main.js','js/app.js','scripts/app.js'):
        u=urllib.parse.urljoin(BASE,x)
        if u not in srcs: srcs.append(u)
    for u in srcs[:30]:
        rec={'url':u,'endpoints':[]}
        try:
            txt=fetch_text(u)
            rec['bytes']=len(txt.encode('utf-8'))
            rec['endpoints']=interesting_urls(txt)
            snippets=[]
            low=txt.lower()
            for term in ('mapserver','featureserver','hyfi','flood','streetwise_live','rainwater'):
                pos=0
                while True:
                    pos=low.find(term,pos)
                    if pos<0: break
                    snippets.append(txt[max(0,pos-180):min(len(txt),pos+300)])
                    pos+=len(term)
                    if len(snippets)>=40: break
                if len(snippets)>=40: break
            rec['snippets']=snippets
        except Exception as e: rec['error']=str(e)
        out['scripts'].append(rec)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print('scripts',len(out['scripts']),'html endpoints',len(out['html_endpoints']))
    return 0
if __name__=='__main__': raise SystemExit(main())
