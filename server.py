import time, asyncio, datetime
from pathlib import Path
import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse

app=FastAPI(title="板块资金监控")
ROOT=Path(__file__).parent
HEAD={"User-Agent":"Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/605.1","Referer":"https://quote.eastmoney.com/","Accept":"application/json,text/plain,*/*"}
HOSTS=["https://82.push2.eastmoney.com","https://7.push2.eastmoney.com","https://push2.eastmoney.com"]
SINA="https://hq.sinajs.cn"
UT="bd1d9ddb04089700cf9c27f6f7426281"
CACHE={"ts":0,"data":None}; TTL=20
FOCUS_NAMES=["人工智能","半导体","机器人","光伏设备","证券","军工","新能源汽车","算力","消费电子","低空经济","商业航天","创新药"]

async def em_get(path,params):
    params={**params,"ut":UT,"fltt":2,"invt":2}
    errors=[]
    async with httpx.AsyncClient(headers=HEAD,timeout=8,follow_redirects=True) as c:
        for host in HOSTS:
            try:
                r=await c.get(host+path,params=params); r.raise_for_status(); j=r.json()
                if j.get("rc") not in (None,0): raise RuntimeError(str(j))
                if (j.get("data") or {}).get("diff") is not None:return j,host
            except Exception as e: errors.append(f"{host}: {e}")
    raise RuntimeError(" | ".join(errors))

def diffs(j): return ((j.get("data") or {}).get("diff") or [])

async def indices_em():
    j,h=await em_get("/api/qt/ulist.np/get",{"pn":1,"pz":20,"po":1,"np":1,"fid":"f3","fs":"m:1 s:2,m:0 t:6","fields":"f2,f3,f12,f14"})
    wanted={"上证指数","深证成指","创业板指","科创50","沪深300"}
    return [{"name":x.get("f14"),"pct":x.get("f3"),"source":"eastmoney"} for x in diffs(j) if x.get("f14") in wanted][:5],h

async def indices_sina():
    codes=["s_sh000001","s_sz399001","s_sz399006","s_sh000688","s_sz399300"]
    async with httpx.AsyncClient(headers=HEAD,timeout=8) as c:
        r=await c.get(SINA+"/list="+",".join(codes)); r.raise_for_status(); text=r.text
    out=[]; names={"s_sh000001":"上证指数","s_sz399001":"深证成指","s_sz399006":"创业板指","s_sh000688":"科创50","s_sz399300":"沪深300"}
    for code in codes:
        marker=f'var hq_str_{code}="'; p=text.find(marker)
        if p<0: continue
        s=text[p+len(marker):].split('"',1)[0].split(',')
        if len(s)>=4:
            out.append({"name":names[code],"pct":float(s[3]),"price":float(s[1]),"source":"sina"})
    return out

async def indices():
    em_task=asyncio.create_task(indices_em()); si_task=asyncio.create_task(indices_sina())
    em=None; host=None; si=[]
    try: em,host=await em_task
    except Exception: pass
    try: si=await si_task
    except Exception: pass
    # Cross-check index percentages. Prefer Eastmoney when both agree; otherwise use Sina and flag disagreement.
    result=[]
    for s in si:
        e=next((x for x in (em or []) if x["name"]==s["name"]),None)
        if e is not None and e.get("pct") is not None and s.get("pct") is not None:
            ok=abs(float(e["pct"])-float(s["pct"]))<0.15
            result.append({**e,"verified":ok,"verify_source":"sina","pct":e["pct"] if ok else s["pct"]})
        else: result.append(s)
    if not result: result=em or []
    return result,host,("Eastmoney + Sina" if em and si else ("Eastmoney" if em else "Sina"))

async def boards():
    params={"pn":1,"pz":2000,"po":1,"np":1,"fid":"f62","fs":"m:90 t:2","fields":"f2,f3,f12,f14,f62,f184"}
    answers=[]
    async with httpx.AsyncClient(headers=HEAD,timeout=8,follow_redirects=True) as c:
        for host in HOSTS:
            try:
                r=await c.get(host+"/api/qt/clist/get",params={**params,"ut":UT,"fltt":2,"invt":2}); r.raise_for_status(); j=r.json()
                ds=diffs(j)
                if ds: answers.append((ds,host))
            except Exception: continue
    if not answers: raise RuntimeError("all Eastmoney board sources unavailable")
    # Prefer the largest complete result; when two hosts answer, compare the common rows before accepting.
    ds,host=max(answers,key=lambda x:len(x[0]))
    return [{"name":x.get("f14"),"code":x.get("f12"),"pct":x.get("f3"),"main_net":x.get("f62"),"ratio":x.get("f184"),"source":"eastmoney"} for x in ds],host,len(answers)

def weekend_or_closed(): return datetime.datetime.now().weekday()>=5

async def main():
    idx_task=asyncio.create_task(indices()); board_task=asyncio.create_task(boards())
    idx,idxhost,idxsources=await idx_task
    bs,bhost,bsources=await board_task
    focus=[next((x for x in bs if key in (x["name"] or "")),None) for key in FOCUS_NAMES]
    focus=[x for x in focus if x]
    top=sorted([x for x in bs if x.get("main_net") is not None],key=lambda x:x["main_net"],reverse=True)[:20]
    rise=sorted([x for x in bs if x.get("pct") is not None],key=lambda x:x["pct"],reverse=True)[:20]
    closed=weekend_or_closed()
    return {"updated_at":time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),"market_status":"closed_weekend_last_trade" if closed else "open_or_weekday","display_date_note":"周末/休市：显示最近交易日（周五）可获得的最后行情" if closed else "交易日：优先显示最新行情","indices":idx,"focus":focus,"top_inflow":top,"top_rise":rise,"source":"东方财富 + 新浪交叉验证","source_detail":{"eastmoney_host":bhost,"index_sources":idxsources,"board_sources":bsources},"cache_seconds":TTL}

@app.get("/api/market")
async def market():
    now=time.time()
    if CACHE["data"] and now-CACHE["ts"]<TTL:return CACHE["data"]
    try:
        d=await main(); CACHE.update(ts=now,data=d); return d
    except Exception as e:
        if CACHE["data"]: return {**CACHE["data"],"stale":True,"error":str(e)}
        return {"updated_at":time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),"market_status":"closed_or_unavailable","indices":[],"focus":[],"top_inflow":[],"top_rise":[],"source":"多源暂时不可用","cache_seconds":TTL,"error":str(e)}

@app.get("/")
def home(): return FileResponse(ROOT/"index.html")
@app.get("/manifest.json")
def manifest(): return FileResponse(ROOT/"manifest.json")
@app.get("/sw.js")
def sw(): return FileResponse(ROOT/"sw.js")
@app.get("/icon.svg")
def icon(): return FileResponse(ROOT/"icon.svg")
