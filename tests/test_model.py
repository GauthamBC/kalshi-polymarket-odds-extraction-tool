import pandas as pd
import numpy as np
import pytest
from model import combine,backtest,validate_history,brier
from feeds import kalshi_quote,poly_quote,quote_from_bid_ask,merge_histories,at_or_before,poly_yes_token


def fake_history(n=60, k_error=0.0, p_error=0.15):
    rows=[]
    for i in range(n):
        y=i%2
        rows.append(dict(race_id=f'R{i:03d}',election_date=f'2024-11-{i%28+1:02d}T00:00:00Z',horizon_hours=24,
                         kalshi_probability=0.85 if y else 0.15,polymarket_probability=(0.65 if y else 0.35),outcome=y))
    x=pd.DataFrame(rows)
    x['election_date']=pd.date_range('2024-09-01',periods=n,freq='D',tz='UTC')
    x['asof_utc']=(x['election_date']-pd.Timedelta(hours=24)).astype(str)
    return x

def test_composite():
    assert combine(.6,.4)==pytest.approx(.5)
    assert combine(.6,.4,.7)==pytest.approx(.54)
    assert combine(None,.4) is None

def test_quotes():
    assert kalshi_quote({'yes_bid_dollars':'0.60','yes_ask_dollars':'0.62'})[0]==pytest.approx(.61)
    assert poly_quote({'outcomes':'["Yes","No"]','outcomePrices':'["0.45","0.55"]'})[0]==pytest.approx(.45)
    assert poly_yes_token({'outcomes':'["No","Yes"]','clobTokenIds':'["1","2"]'})=='2'
    assert quote_from_bid_ask(.1,.9,None)[0] is None

def test_validation_reject_duplicate():
    x=fake_history(35)
    x.loc[1,'race_id']=x.loc[0,'race_id']
    with pytest.raises(ValueError):validate_history(x)

def test_sparse_blocked():
    with pytest.raises(ValueError):backtest(fake_history(20),24)

def test_historical_holdout_and_weight():
    x=fake_history(60)
    fit=backtest(x,24)
    assert fit.test_rows>=10
    assert .3<=fit.candidate_k_weight<=.7
    assert fit.brier_weighted < fit.brier_equal
    assert fit.status=='HOLDOUT-PASSED'

def test_history_with_missing_samples():
    x=pd.DataFrame({'time':pd.to_datetime(['2024-11-02T00:00:00Z']),'Kalshi':[0.7]})
    assert at_or_before(x,'Kalshi',pd.Timestamp('2024-11-04T00:00:00Z'),12) is None

def test_lookahead_rejected():
    x=fake_history(35)
    x.loc[0,'asof_utc']='2026-11-04T00:00:00Z'
    with pytest.raises(ValueError):validate_history(x)
