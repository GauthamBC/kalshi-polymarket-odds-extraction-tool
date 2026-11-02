"""Transparent, horizon-specific historical accuracy blending for AN."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import numpy as np
import pandas as pd

REQUIRED = ["race_id", "election_date", "asof_utc", "horizon_hours", "kalshi_probability", "polymarket_probability", "outcome"]
HORIZONS = {24: "24 hours", 168: "7 days", 720: "30 days"}


def brier(p, y):
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    return float(np.mean((p - y)**2))


def validate_history(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError("Missing historical CSV columns: " + ", ".join(missing))
    x = df[REQUIRED].copy()
    x["election_date"] = pd.to_datetime(x["election_date"], utc=True, errors="coerce")
    x["asof_utc"] = pd.to_datetime(x["asof_utc"], utc=True, errors="coerce")
    for c in ("horizon_hours", "kalshi_probability", "polymarket_probability", "outcome"):
        x[c] = pd.to_numeric(x[c], errors="coerce")
    if x.isna().any().any():
        raise ValueError("Historical CSV has missing, nonnumeric, or invalid dates. No rows are silently discarded.")
    if not x["kalshi_probability"].between(0, 1).all() or not x["polymarket_probability"].between(0,1).all():
        raise ValueError("Probabilities must be fractions between 0 and 1 (0.62, not 62).")
    if not x["outcome"].isin([0,1]).all():
        raise ValueError("outcome must be 0 or 1 for the precisely matched YES proposition.")
    if not x["horizon_hours"].isin(HORIZONS).all():
        raise ValueError("horizon_hours must be 24, 168, or 720.")
    hours_ahead=(x["election_date"]-x["asof_utc"]).dt.total_seconds()/3600.0
    allowed=x["horizon_hours"].map({24:12,168:36,720:72})
    if ((hours_ahead <= 0) | ((hours_ahead - x["horizon_hours"]).abs() > allowed)).any():
        raise ValueError("Each asof_utc must PRECEDE election_date and be within the selected horizon tolerance (24h +/-12h, 168h +/-36h, 720h +/-72h).")
    if x.duplicated(["race_id", "horizon_hours"]).any():
        raise ValueError("Only one snapshot per race_id and horizon; otherwise repeated markets overweight elections.")
    if (x["race_id"].astype(str).str.strip() == "").any():
        raise ValueError("race_id may not be blank.")
    return x.sort_values(["election_date", "race_id"]).reset_index(drop=True)


def _weights(train: pd.DataFrame) -> tuple[float,float]:
    """Recency-weighted inverse-Brier; shrunk to equal, maximum +/-20pp.

    Historical forecasts receive exponentially decaying weight with a 730-day
    half-life. This is a stated modelling assumption, not a study-derived constant.
    """
    days=(train.election_date.max()-train.election_date).dt.total_seconds()/86400
    recency=np.exp(-np.log(2)*days/730.0)
    score_k=float(np.average((train.kalshi_probability-train.outcome)**2,weights=recency))
    score_p=float(np.average((train.polymarket_probability-train.outcome)**2,weights=recency))
    # A meaningful shrinkage constant reduces spurious deviations on tiny score differences.
    raw_k = (score_p + 0.05) / (score_k + score_p + 0.10)
    w_k = float(np.clip(0.5 + 0.6*(raw_k-0.5), 0.30, 0.70))
    return w_k, 1-w_k

@dataclass
class Backtest:
    rows: int
    train_rows: int
    test_rows: int
    horizon_hours: int
    brier_kalshi: float
    brier_polymarket: float
    brier_equal: float
    brier_weighted: float
    candidate_k_weight: float
    selected_k_weight: float
    status: str
    reason: str
    evaluation: pd.DataFrame


def backtest(history: pd.DataFrame, horizon_hours: int=24) -> Backtest:
    x = validate_history(history)
    x = x[x.horizon_hours == horizon_hours].sort_values(["election_date", "race_id"]).reset_index(drop=True)
    if len(x) < 30:
        raise ValueError(f"Need at least 30 distinct resolved election races at the selected horizon; found {len(x)}.")
    split = int(np.floor(len(x)*0.7))
    train, test = x.iloc[:split], x.iloc[split:]
    if len(test)<10 or train.outcome.nunique()<2 or test.outcome.nunique()<2:
        raise ValueError("Need at least 10 later holdout races and both outcomes in training and holdout; add broader representative history.")
    wk, wp = _weights(train)
    eq = (test.kalshi_probability+test.polymarket_probability)/2
    wt = wk*test.kalshi_probability+wp*test.polymarket_probability
    scores = {"kalshi":brier(test.kalshi_probability,test.outcome),
              "polymarket":brier(test.polymarket_probability,test.outcome),
              "equal":brier(eq,test.outcome),"weighted":brier(wt,test.outcome)}
    # Conservative evidence gate; a failure chooses the neutral baseline automatically.
    adopt = (scores["weighted"]+0.002 <= scores["equal"] and
             scores["weighted"] <= min(scores["kalshi"], scores["polymarket"])+0.03)
    final_w = wk if adopt else 0.5
    status = "HOLDOUT-PASSED" if adopt else "BASELINE-RETAINED"
    reason = ("Accuracy weights improve the later-date holdout Brier score versus equal blend."
              if adopt else "Weighted blend did not clear conservative holdout thresholds; use 50/50.")
    z = test[["race_id", "election_date", "outcome", "kalshi_probability", "polymarket_probability"]].copy()
    z["equal_blend"] = eq
    z["weighted_candidate"] = wt
    return Backtest(len(x),len(train),len(test),horizon_hours,*[scores[i] for i in ("kalshi","polymarket","equal","weighted")],wk,final_w,status,reason,z)


def combine(k: Optional[float], p: Optional[float], weight_k: float=0.5) -> Optional[float]:
    if k is None or p is None or not (0 <= k <= 1 and 0 <= p <= 1):
        return None
    if not 0 <= weight_k <= 1:
        raise ValueError("Invalid Kalshi weight")
    return float(weight_k*k+(1-weight_k)*p)


def explain_weight(wk: float) -> str:
    return f"{wk:.0%} Kalshi / {1-wk:.0%} Polymarket"
