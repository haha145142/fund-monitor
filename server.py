import time, asyncio
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse

app=FastAPI(title="板块资金监控")
ROOT=Path(__file__).parent
HEAD={"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/605.1","Referer":"https://quote.eastmoney.com/"}
EM="https://push2.eastmoney.com"
CACHE={"ts":0,"data":None}
TTL=20

FOCUS_NAMES=["人工智能","半导体","机器人","光伏设备","证券","军工","新能源汽车","算力","消费电子","低空经济","商业航天","创新药"]

async def get(path,params):
    last=None
    for i in range(3):
        try:
            async with httpx.AsyncClient(headers=HEAD,timeout=8,follow_redirects=True) as c:
                r=await c.get(EM+path,params=params); r.raise_for_status(); j=r.json()
                if j.get("rc") not in (None,0): raise RuntimeError(str(j))
                return j
        except Exception as e:
            last=e
            await asyncio.sleep(.4*(i+1))
    raise last

def diffs(j):
    return ((j.get("data") or {}).get("diff") or [])

async def indices():
    j=await get("/api/qt/ulist.np/get",{"pn":1,"pz":20,"po":1,"np":1,"fid":"f3","fs":"m:1 s:2,m:0 t:6","fields":"f2,f3,f12,f14"})
    wanted={"上证指数","深证成指","创业板指","科创50","沪深300"}
    return [{"name":x.get("f14"),"pct":x.get("f3")} for x in diffs(j) if x.get("f14") in wanted][:5]

async def boards():
    j=await get("/api/qt/clist/get",{"pn":1,"pz":100,"po":1,"np":1,"fid":"f62","fs":"m:90 t:2","fields":"f2,f3,f12,f14,f62,f184"})
    return [{"name":x.get("f14"),"code":x.get("f12"),"pct":x.get("f3"),"main_net":x.get("f62"),"ratio":x.get("f184")} for x in diffs(j)]

async def main():
    idx,bs=await asyncio.gather(indices(),boards())
    focus=[]
    for key in FOCUS_NAMES:
        hit=next((x for x in bs if key in (x["name"] or "")),None)
        if hit: focus.append(hit)
    top=sorted([x for x in bs if x.get("main_net") is not None],key=lambda x:x["main_net"],reverse=True)[:20]
    rise=sorted([x for x in bs if x.get("pct") is not None],key=lambda x:x["pct"],reverse=True)[:20]
    return {"updated_at":time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),"indices":idx,"focus":focus,"top_inflow":top,"top_rise":rise,"source":"东方财富公开行情接口","cache_seconds":TTL}

@app.get("/api/market")
async def market():
    now=time.time()
    if CACHE["data"] and now-CACHE["ts"]<TTL:return CACHE["data"]
    try:
        d=await main(); CACHE.update(ts=now,data=d); return d
    except Exception as e:
        if CACHE["data"]: return {**CACHE["data"],"stale":True,"error":str(e)}
        return {"updated_at":time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),"indices":[],"focus":[],"top_inflow":[],"top_rise":[],"source":"暂时无法连接行情源","cache_seconds":TTL,"error":str(e)}

@app.get("/")
def home(): return FileResponse(ROOT/"index.html")
@app.get("/manifest.json")
def manifest(): return FileResponse(ROOT/"manifest.json")
@app.get("/sw.js")
def sw(): return FileResponse(ROOT/"sw.js")
@app.get("/icon.svg")
def icon(): return FileResponse(ROOT/"icon.svg")
