"""Read-only market data clients. Fail closed on missing quotes; never fabricate prices."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import json
import math
from urllib.parse import urlparse
import pandas as pd
import requests

KALSHI = "https://external-api.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
TIMEOUT = 12


def get_json(base, path, params=None):
    # fixed trusted base to avoid allowing arbitrary host requests from input
    if base not in {KALSHI,GAMMA,CLOB}: raise ValueError("Unapproved data host")
    r = requests.get(base+path,params=params,timeout=TIMEOUT,headers={"User-Agent":"ActionNetwork-ResearchDashboard/1.0","Accept":"application/json"})
    r.raise_for_status()
    return r.json()


def float_or_none(x):
    try:
        f = float(x)
        return f if math.isfinite(f) else None
    except (TypeError,ValueError): return None


def probability(x):
    v = float_or_none(x)
    return v if v is not None and 0 <= v <= 1 else None


def as_list(value):
    if isinstance(value,list):return value
    if isinstance(value,str):
        try:
            x=json.loads(value)
            return x if isinstance(x,list) else []
        except (TypeError,ValueError): return []
    return []


def quote_from_bid_ask(bid,ask,last=None,max_spread=0.15):
    b,a = probability(bid),probability(ask)
    if b is not None and a is not None and b<=a and a-b <= max_spread and a>0 and b<1:
        return round((a+b)/2,6),"bid/ask midpoint",round(a-b,6)
    last = probability(last)
    if last is not None and 0<last<1:
        return last,"last traded (spread unavailable or wide)",None if b is None or a is None else round(a-b,6)
    return None,"no usable quote",None


def kalshi_quote(m):
    b= m.get("yes_bid_dollars")
    a= m.get("yes_ask_dollars")
    last= m.get("last_price_dollars")
    if b is None and float_or_none(m.get("yes_bid")) is not None: b=float(m["yes_bid"])/100
    if a is None and float_or_none(m.get("yes_ask")) is not None: a=float(m["yes_ask"])/100
    if last is None and float_or_none(m.get("last_price")) is not None: last=float(m["last_price"])/100
    return quote_from_bid_ask(b,a,last)


def poly_quote(m):
    prices=as_list(m.get("outcomePrices"))
    outcomes=as_list(m.get("outcomes"))
    yes_index=next((i for i,v in enumerate(outcomes) if str(v).lower().strip()=="yes"),None)
    if yes_index is None:
        # For an explicitly selected candidate in a multi-outcome market, use its
        # selected outcome only if Gamma supplies a single candidate outcome.
        return None,"no binary YES token",None
    price = probability(prices[yes_index]) if yes_index<len(prices) else None
    bid=probability(m.get("bestBid")); ask=probability(m.get("bestAsk"))
    # Gamma's bestBid / bestAsk refer to the YES side on normal binary markets.
    return quote_from_bid_ask(bid,ask,price)


def kalshi_market_list(event_ticker):
    result=get_json(KALSHI,"/markets",{"event_ticker":event_ticker,"limit":200})
    return result.get("markets",[])


def kalshi_market(ticker):
    return get_json(KALSHI,"/markets/"+ticker).get("market",{})


def discover_polymarket(query):
    d=get_json(GAMMA,"/public-search",{"q":query,"limit_per_type":15})
    return d.get("events",[]) if isinstance(d,dict) else []


def polymarket_event(slug):
    rows=get_json(GAMMA,"/events",{"slug":slug,"limit":1})
    return rows[0] if rows else None


def polymarket_market(market_id):
    return get_json(GAMMA,"/markets/"+str(market_id))


def poly_yes_token(m):
    outcomes=as_list(m.get("outcomes"));tokens=as_list(m.get("clobTokenIds"))
    i=next((i for i,o in enumerate(outcomes) if str(o).lower().strip()=="yes"),None)
    return str(tokens[i]) if i is not None and i<len(tokens) else None


def kalshi_candles(ticker,series,start_ts,end_ts,interval=60):
    try:
        d=get_json(KALSHI,f"/series/{series}/markets/{ticker}/candlesticks",{"start_ts":start_ts,"end_ts":end_ts,"period_interval":interval})
    except requests.HTTPError as e:
        # Older settled markets are moved to the historical API. Try it only if the
        # public live route specifically returns not-found.
        if e.response is None or e.response.status_code != 404: raise
        d=get_json(KALSHI,f"/historical/markets/{ticker}/candlesticks",{"start_ts":start_ts,"end_ts":end_ts,"period_interval":interval})
    rows=[]
    for v in d.get("candlesticks",[]):
        bid=probability(v.get("yes_bid",{}).get("close_dollars"))
        ask=probability(v.get("yes_ask",{}).get("close_dollars"))
        last=probability(v.get("price",{}).get("close_dollars"))
        px,method,_=quote_from_bid_ask(bid,ask,last)
        if px is not None:
            rows.append({"time":pd.to_datetime(v["end_period_ts"],unit="s",utc=True),"Kalshi":px})
    return pd.DataFrame(rows,columns=["time","Kalshi"]).drop_duplicates("time").sort_values("time")


def polymarket_history(token,start_ts,end_ts,fidelity=60):
    d=get_json(CLOB,"/prices-history",{"market":token,"startTs":start_ts,"endTs":end_ts,"fidelity":fidelity})
    rows=[]
    for x in d.get("history",[]):
        p=probability(x.get("p"))
        if p is not None: rows.append({"time":pd.to_datetime(x["t"],unit="s",utc=True),"Polymarket":p})
    return pd.DataFrame(rows,columns=["time","Polymarket"]).drop_duplicates("time").sort_values("time")


def at_or_before(df,name,target,allowed_hours):
    if df is None or df.empty:return None
    x=df.loc[(df.time<=target)&(df.time>=target-pd.Timedelta(hours=allowed_hours))]
    return float(x.iloc[-1][name]) if not x.empty else None


def merge_histories(k,p,wk=0.5,tolerance="2h"):
    if k is None or p is None or k.empty or p.empty:
        return pd.DataFrame(columns=["time","Kalshi","Polymarket","AN composite"])
    x=pd.merge_asof(k.sort_values("time"),p.sort_values("time"),on="time",direction="nearest",tolerance=pd.Timedelta(tolerance))
    x=x.dropna(subset=["Kalshi","Polymarket"])
    x["AN composite"]=wk*x["Kalshi"]+(1-wk)*x["Polymarket"]
    return x
