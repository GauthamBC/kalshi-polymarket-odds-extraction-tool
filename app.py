"""Action Network | Implied Chance Lab — read-only research dashboard.

Launch: streamlit run app.py
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import io
import json
import re
import time
import pandas as pd
import plotly.graph_objects as go
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import streamlit as st
from catalog import WATCHLIST
from model import backtest, combine, explain_weight, HORIZONS
from feeds import (
    KALSHI,GAMMA,CLOB, kalshi_market_list,kalshi_market,kalshi_quote,
    discover_polymarket,polymarket_event,polymarket_market,poly_quote,
    poly_yes_token,kalshi_candles,polymarket_history,merge_histories,at_or_before,
)

st.set_page_config(page_title="AN | Implied Chance Lab",page_icon="📊",layout="wide",initial_sidebar_state="expanded")
st.markdown("""<style>
.block-container{padding-top:1.5rem;max-width:1430px}
h1,h2,h3{letter-spacing:-.025em}
.an-kicker{font-size:.77rem;letter-spacing:.18em;color:#078B85;font-weight:750}
.an-note{border:1px solid #d7e5e8;border-radius:12px;padding:13px 16px;background:#f1f7f8;color:#193746;font-size:0.93rem}
.an-subtitle{color:#536e7b;font-size:1.04rem;margin-bottom:1.0rem}
[data-testid="stMetric"]{border:1px solid #d7e4e6;border-radius:13px;padding:13px;background:#ffffff}
[data-testid="stMetricLabel"]{font-size:.9rem}
</style>""",unsafe_allow_html=True)

for key,val in {"mappings":{},"search_results":{},"market_options":{},"p_events":{},"snapshots":[],"live":{},"series":{}}.items():
    if key not in st.session_state:st.session_state[key]=val

@st.cache_data(ttl=60,show_spinner=False)
def load_k_options(event): return kalshi_market_list(event)

@st.cache_data(ttl=120,show_spinner=False)
def load_poly_search(query): return discover_polymarket(query)

@st.cache_data(ttl=60,show_spinner=False)
def load_p_event(slug):return polymarket_event(slug)

@st.cache_data(ttl=30,show_spinner=False)
def load_k_market(ticker):return kalshi_market(ticker)

@st.cache_data(ttl=30,show_spinner=False)
def load_p_market(mid):return polymarket_market(mid)

@st.cache_data(ttl=120,show_spinner=False)
def load_history(k_ticker,series,p_token):
    now=int(datetime.now(timezone.utc).timestamp())
    start=now-9*86400
    k=kalshi_candles(k_ticker,series,start,now,60)
    p=polymarket_history(p_token,start,now,60)
    return k,p


def pretty_p(p):return "—" if p is None else f"{p:.1%}"
def pretty_change(v):return "Unavailable" if v is None else f"{v*100:+.1f} pp"
def preview_k(m):
    label=m.get('yes_sub_title') or m.get('subtitle') or m.get('title') or '?'
    q,method,spread=kalshi_quote(m)
    return f"{label} | {m.get('ticker','?')} | {pretty_p(q)}"
def preview_p(m):
    label=m.get('question') or m.get('groupItemTitle') or '?'
    q,method,spread=poly_quote(m)
    return f"{label[:110]} | {pretty_p(q)}"

def safer_error(prefix,e):
    # expose diagnostic HTTP errors without stack trace or credentials
    st.error(f"{prefix}: {type(e).__name__}: {str(e)[:230]}")


def get_mapping(name):return st.session_state['mappings'].get(name)


def graphic(race,candidate,k,p,an,asof,method):
    fig,ax=plt.subplots(figsize=(11,5.4),facecolor='#f7fafb')
    ax.set_facecolor('#f7fafb'); ax.set_xlim(0,100);ax.set_ylim(-.7,3.2);ax.axis('off')
    ax.text(0,3.1,"ACTION NETWORK  /  MARKET INTELLIGENCE",fontsize=12,color='#138e88',weight='bold')
    ax.text(0,2.57,race,fontsize=23,color='#142d3a',weight='bold')
    ax.text(0,2.20,candidate+' — implied chance of winning',fontsize=12,color='#496370')
    for j,(lab,v,c) in enumerate([('Kalshi',k,'#355879'),('Polymarket',p,'#6882a8'),('AN composite',an,'#078f89')]):
        y=1.66-j*.67
        ax.text(0,y+.25,lab,fontsize=13,color='#233b48',weight='bold' if j==2 else 'normal')
        ax.barh(y,100,height=.17,color='#e3e9ec',left=0)
        ax.barh(y,100*v,height=.17,color=c,left=0)
        ax.text(100,y+.05,f"{v:.1%}",fontsize=15,color=c,weight='bold',ha='right')
    ax.text(0,-.62,f"{asof} UTC  •  {method}  •  Market-derived; not a poll or vote-share projection",fontsize=10,color='#526875')
    output=io.BytesIO()
    fig.savefig(output,format='png',dpi=155,bbox_inches='tight',facecolor=fig.get_facecolor())
    plt.close(fig);return output.getvalue()

st.markdown('<div class="an-kicker">ACTION NETWORK  /  DIGITAL PR INTELLIGENCE</div>',unsafe_allow_html=True)
st.title('Implied Chance Lab')
st.markdown('<div class="an-subtitle">Compare verified election contracts, inspect last-minute price movements, and validate AN’s historical-accuracy weighting.</div>',unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Research controls")
    st.caption("Read-only market access · No trading accounts or API keys required")
    current_names=[x for x in WATCHLIST if x!='Kansas Senate']
    race=st.selectbox("Election watchlist",["Florida Governor","Maine Senate","Iowa Senate","Texas Senate","Michigan Senate","Georgia Governor","Texas Governor","Custom race"])
    if race == 'Custom race':
        custom_name=st.text_input('Race label','Custom 2026 election')
        race=custom_name.strip() or 'Custom race'
        seed={"state":"","office":"","candidate":"","kalshi_event":"","search":""}
    else:seed=WATCHLIST[race]
    candidate=st.text_input("Candidate / YES proposition",seed.get('candidate',''),key=f"candidate_{race}")
    st.markdown('---')
    st.markdown('**AN probability model**')
    st.caption("The 50/50 composite is available immediately. Accuracy-adjusted weights require a validated, held-out historical sample.")
    histfile=st.file_uploader('Resolved elections history CSV (optional)',type=['csv'],key='historic')
    selected_horizon=st.selectbox('Backtest horizon',list(HORIZONS),format_func=lambda h:HORIZONS[h])
    fit=None
    hist_error=None
    if histfile is not None:
        try:
            hist=pd.read_csv(histfile)
            fit=backtest(hist,selected_horizon)
            st.success(f"Backtest: {fit.status}")
        except Exception as e:
            hist_error=str(e);st.warning(f"Historical model inactive: {hist_error}")
    eligible=fit is not None and fit.status=='HOLDOUT-PASSED'
    if eligible:
        same_horizon=st.checkbox('I verified this live snapshot is at the selected pre-election horizon',value=False,help='Historical weights trained 7 days before elections should not silently be applied to quotes from election eve.')
    else:same_horizon=False
    wk=fit.selected_k_weight if eligible and same_horizon else 0.5
    model_label='Accuracy-adjusted' if eligible and same_horizon else 'Equal-weight baseline'
    st.metric('AN weight · Kalshi',f'{wk:.0%}')
    st.metric('AN weight · Polymarket',f'{1-wk:.0%}')
    if st.button('Clear cached API data',use_container_width=True):
        st.cache_data.clear();st.rerun()

tabs=st.tabs(["01  Live comparison","02  Match contracts","03  Accuracy backtest","04  Exports & methodology"])

with tabs[1]:
    st.subheader('Match the exact YES outcome')
    st.markdown('<div class="an-note">A market for <b>the Democratic candidate winning</b> is not automatically identical to a market for <b>the Democratic Party winning</b>. Review settlement rules, candidate names, election date, runoff rules, and the YES outcome before approval.</div>',unsafe_allow_html=True)
    st.write('')
    left,right=st.columns(2,gap='large')
    with left:
        st.markdown('#### Kalshi')
        k_event=st.text_input('Kalshi event ticker (search seed)',seed.get('kalshi_event',''),key=f'kt_{race}')
        if st.button('Find Kalshi contracts',use_container_width=True):
            if not re.fullmatch(r'[A-Za-z0-9_-]{2,100}',k_event):
                st.warning('Enter a valid market event ticker, e.g. GOVPARTYFL-26.')
            else:
                try:st.session_state['market_options'][race]=load_k_options(k_event)
                except Exception as e:safer_error('Kalshi lookup failed',e)
        k_options=st.session_state['market_options'].get(race,[])
        k_selected=None
        if k_options:
            if len(k_options)>40:st.info('This event contains more than 40 markets. Please verify the chosen contract carefully.')
            k_selected=st.selectbox('Select exact YES contract',list(range(len(k_options))),format_func=lambda i:preview_k(k_options[i]),key=f'kselect_{race}')
            km=k_options[k_selected]
            st.caption(f"Question: {km.get('title','')} | YES: {km.get('yes_sub_title','')} | Status: {km.get('status','')} ")
            st.caption(f"Rules: {str(km.get('rules_primary','Not supplied by API'))[:350]}")
            st.link_button('Open Kalshi market',f"https://kalshi.com/markets/{km.get('ticker','').lower()}")
        else:st.info('Search the event to display its individual markets. No candidate contract is preselected.')
    with right:
        st.markdown('#### Polymarket Global')
        p_query=st.text_input('Polymarket event search',seed.get('search',''),key=f'pquery_{race}')
        if st.button('Search Polymarket events',use_container_width=True):
            try:st.session_state['search_results'][race]=load_poly_search(p_query)
            except Exception as e:safer_error('Polymarket search failed',e)
        ps=st.session_state['search_results'].get(race,[])
        if ps:
            chosen=st.selectbox('Suggested events (not auto-approved)',list(range(len(ps))),format_func=lambda i:f"{ps[i].get('title','?')} | {ps[i].get('slug','?')}",key=f'eventselect_{race}')
            slug_seed=ps[chosen].get('slug','')
        else:slug_seed=''
        p_slug=st.text_input('Exact Polymarket event slug',value=slug_seed,key=f'polyslug_{race}',placeholder='florida-governor-winner-2026')
        if st.button('Load event and contracts',use_container_width=True):
            if not re.fullmatch(r'[a-zA-Z0-9_-]{2,180}',p_slug):
                st.warning('Enter a valid event slug from a polymarket.com/event/... URL.')
            else:
                try:st.session_state['p_events'][race]=load_p_event(p_slug)
                except Exception as e:safer_error('Polymarket event lookup failed',e)
        p_ev=st.session_state['p_events'].get(race)
        p_options=p_ev.get('markets',[]) if isinstance(p_ev,dict) else []
        p_selected=None
        if p_options:
            p_selected=st.selectbox('Select YES contract',list(range(len(p_options))),format_func=lambda i:preview_p(p_options[i]),key=f'pselect_{race}')
            pm=p_options[p_selected]
            st.caption(f"Question: {pm.get('question','')} | Outcomes: {pm.get('outcomes','')} | ID: {pm.get('id','')}")
            st.caption(f"Resolution rules: {str(pm.get('description','Not supplied by API'))[:350]}")
            if p_ev.get('slug'):st.link_button('Open Polymarket event',f"https://polymarket.com/event/{p_ev['slug']}")
        else:st.info('Find a matching Polymarket election event and select its candidate YES contract.')
    st.write('')
    # Approval must be repeated if either selected contract changes.
    selected_signature = (k_options[k_selected].get('ticker','') if k_selected is not None else '') + '|' + (str(p_options[p_selected].get('id','')) if p_selected is not None else '')
    choice_key = f'_last_choice_{race}'
    if st.session_state.get(choice_key) != selected_signature:
        st.session_state[f'confirmed_{race}'] = False
        st.session_state[choice_key] = selected_signature
    same=st.checkbox('I have verified that the selected YES contracts resolve on the same candidate/outcome, election, timing, and runoff rules.',key=f'confirmed_{race}')
    if st.button('Approve this pair for AN calculations',type='primary',use_container_width=True):
        if not (k_options and p_options and same):st.error('Select contracts on both exchanges and verify their settlement rules first.')
        else:
            km=k_options[k_selected];pm=p_options[p_selected]
            token=poly_yes_token(pm)
            if not token:st.error('The selected Polymarket market does not expose a binary YES token. Choose another contract.')
            elif not km.get('ticker') or not pm.get('id'):st.error('A contract identifier is missing.')
            else:
                st.session_state['mappings'][race]={
                    'race':race,'candidate':candidate,'kalshi_ticker':km['ticker'],
                    'kalshi_event':km.get('event_ticker',k_event),
                    'kalshi_yes':km.get('yes_sub_title') or km.get('title',''),
                    'polymarket_id':str(pm['id']),'polymarket_slug':p_ev.get('slug',''),
                    'polymarket_question':pm.get('question',''),
                    'polymarket_token_yes':token,'verified_at':datetime.now(timezone.utc).isoformat(),
                    'verification':'manual verified by operator',
                }
                st.session_state['live'].pop(race,None)
                st.session_state['series'].pop(race,None)
                st.success('Pair approved for this session. Open Live comparison to view the AN composite.')
    current=get_mapping(race)
    if current:
        st.success(f"Approved pair: {current['kalshi_ticker']}  ↔  Polymarket market {current['polymarket_id']}")
        if st.button('Revoke pairing approval'):
            del st.session_state['mappings'][race]
            st.session_state['live'].pop(race,None)
            st.session_state['series'].pop(race,None)
            st.rerun()

with tabs[0]:
    st.subheader('Election watchlist overview')
    existing=list(st.session_state['live'].values())
    if existing:
        overview=[]
        for one in existing:
            a=combine(one['kalshi_probability'],one['polymarket_probability'],wk)
            overview.append({'Race':one['race'],'Candidate / proposition':one['candidate'],
                             'Kalshi':f"{one['kalshi_probability']:.1%}",
                             'Polymarket':f"{one['polymarket_probability']:.1%}",
                             'AN implied chance':f"{a:.1%}",
                             'Platform gap':f"{abs(one['kalshi_probability']-one['polymarket_probability'])*100:.1f} pp",
                             'Source as of (UTC)':one['asof_utc'][:16]})
        st.dataframe(pd.DataFrame(overview),use_container_width=True,hide_index=True)
        st.download_button('Export watchlist summary CSV',pd.DataFrame(overview).to_csv(index=False).encode(),
                           file_name='AN_implied_chance_watchlist.csv',mime='text/csv')
    else:
        st.info('No market prices collected yet. Approve a verified pair and refresh it to populate this multi-race overview.')
    approved=st.session_state['mappings']
    if approved and st.button('Refresh odds for all approved races',help='Queries both exchanges for every approved pair, without downloading price history'):
        completed=0;problems=[]
        for race_name,rule in approved.items():
            try:
                mk=load_k_market(rule['kalshi_ticker']);mp=load_p_market(rule['polymarket_id'])
                k,kmeth,kspread=kalshi_quote(mk);p,pmeth,pspread=poly_quote(mp)
                if k is None or p is None:raise ValueError('unavailable or invalid source price')
                tt=datetime.now(timezone.utc)
                rec={'race':race_name,'candidate':rule['candidate'],'asof_utc':tt.isoformat(),
                     'kalshi_probability':k,'polymarket_probability':p,'an_probability':combine(k,p,wk),
                     'kalshi_weight':wk,'method':model_label,'kalshi_quote_method':kmeth,'polymarket_quote_method':pmeth,
                     'kalshi_spread':kspread,'polymarket_spread':pspread,
                     'kalshi_ticker':rule['kalshi_ticker'],'polymarket_market_id':rule['polymarket_id']}
                st.session_state['live'][race_name]=rec
                st.session_state['snapshots'].append(rec)
                completed+=1
            except Exception as e:problems.append(f'{race_name}: {str(e)[:95]}')
        if completed:st.success(f'Updated {completed} approved races. The table above updates on the next interaction.')
        if problems:st.warning('Could not refresh: '+'; '.join(problems))
    st.divider()
    st.subheader(race)
    mapping=get_mapping(race)
    if not mapping:
        st.warning('No verified market pair selected for this race. Open **Match contracts**, choose the exact YES propositions, and approve the pair. The app will not invent a match or a probability.')
    else:
        st.caption(f"Approved YES proposition: {mapping['candidate']} · Kalshi {mapping['kalshi_ticker']} · Polymarket #{mapping['polymarket_id']}")
        if st.button('Refresh prices & 9-day history',type='primary'):
            try:
                with st.spinner('Fetching current read-only market prices...'):
                    mk=load_k_market(mapping['kalshi_ticker'])
                    mp=load_p_market(mapping['polymarket_id'])
                    k,kmeth,kspread=kalshi_quote(mk);p,pmeth,pspread=poly_quote(mp)
                    if k is None or p is None:raise ValueError(f"Incomplete live quotes: Kalshi {kmeth}; Polymarket {pmeth}.")
                    composite=combine(k,p,wk)
                    ts=datetime.now(timezone.utc)
                    rec={"race":race,"candidate":mapping['candidate'],"asof_utc":ts.isoformat(),
                        "kalshi_probability":k,"polymarket_probability":p,"an_probability":composite,
                        "kalshi_weight":wk,"method":model_label,"kalshi_quote_method":kmeth,"polymarket_quote_method":pmeth,
                        "kalshi_spread":kspread,"polymarket_spread":pspread,
                        "kalshi_ticker":mapping['kalshi_ticker'],"polymarket_market_id":mapping['polymarket_id']}
                    st.session_state['live'][race]=rec
                    st.session_state['snapshots'].append(rec)
                try:
                    with st.spinner('Loading source price history...'):
                        k_series=mapping['kalshi_ticker'].split('-')[0]
                        h_k,h_p=load_history(mapping['kalshi_ticker'],k_series,mapping['polymarket_token_yes'])
                        st.session_state['series'][race]=(h_k,h_p)
                except Exception as e:
                    st.session_state['series'][race]=(pd.DataFrame(),pd.DataFrame())
                    st.warning(f"Current prices loaded; price history unavailable: {type(e).__name__}: {str(e)[:180]}")
            except Exception as e:safer_error('Could not refresh the selected pair',e)
        rec=st.session_state['live'].get(race)
        if not rec:st.info('Select **Refresh prices & 9-day history** to load current quotes. No demonstration numbers are displayed as real prices.')
        else:
            if rec['kalshi_weight']!=wk:
                rec=dict(rec);rec['kalshi_weight']=wk;rec['an_probability']=combine(rec['kalshi_probability'],rec['polymarket_probability'],wk);rec['method']=model_label
                st.info('AN displayed composite recalculated using the current model weight. Source prices are from the timestamp shown below.')
            st.caption('Source price retrieval: '+rec['asof_utc']+' · Market prices are not live-streaming. Click refresh again for newer data.')
            a,b,c=st.columns(3)
            a.metric('Kalshi implied chance',pretty_p(rec['kalshi_probability']))
            b.metric('Polymarket implied chance',pretty_p(rec['polymarket_probability']))
            c.metric('AN implied chance of winning',pretty_p(rec['an_probability']))
            st.caption(f"Method: {rec['method']} · {explain_weight(wk)} · Kalshi quote: {rec['kalshi_quote_method']} · Polymarket quote: {rec['polymarket_quote_method']}")
            sh=st.session_state['series'].get(race)
            if sh is not None and not sh[0].empty and not sh[1].empty:
                h_k,h_p=sh
                fig=go.Figure()
                fig.add_trace(go.Scatter(x=h_k.time,y=h_k.Kalshi*100,name='Kalshi',mode='lines',line=dict(color='#40668a',width=2)))
                fig.add_trace(go.Scatter(x=h_p.time,y=h_p.Polymarket*100,name='Polymarket',mode='lines',line=dict(color='#748ca7',width=2)))
                merged=merge_histories(h_k,h_p,wk)
                if not merged.empty:fig.add_trace(go.Scatter(x=merged.time,y=merged['AN composite']*100,name='AN composite',mode='lines',line=dict(color='#07958d',width=3)))
                fig.update_layout(title='Last nine days: source prices and aligned AN composite',yaxis_title='Implied probability (%)',xaxis_title='UTC',hovermode='x unified',height=420,margin=dict(l=10,r=20,t=52,b=10),legend=dict(orientation='h',y=1.08))
                st.plotly_chart(fig,use_container_width=True)
                now=pd.Timestamp(rec['asof_utc'])
                st.markdown('#### Observed price changes')
                rows=[]
                for hours,tol,tag in [(24,12,'24 hours'),(168,24,'7 days')]:
                    target=now-pd.Timedelta(hours=hours)
                    old_k=at_or_before(h_k,'Kalshi',target,tol)
                    old_p=at_or_before(h_p,'Polymarket',target,tol)
                    old_an=combine(old_k,old_p,wk)
                    rows.append({'Lookback':tag,'Kalshi change':pretty_change(rec['kalshi_probability']-old_k if old_k is not None else None),
                                 'Polymarket change':pretty_change(rec['polymarket_probability']-old_p if old_p is not None else None),
                                 'AN change':pretty_change(rec['an_probability']-old_an if old_an is not None else None),
                                 'Both sources available':old_an is not None})
                st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
                st.caption('Changes are in percentage points. Historical values must be observed at or before the target date within the allowable window; otherwise shown as unavailable. No missing prices are inferred.')
            else:st.info('Historical change figures are unavailable for at least one exchange. Current verified snapshot remains usable.')
            if rec.get('kalshi_spread') is not None and rec['kalshi_spread']>0.10:st.warning('Kalshi quoted bid–ask spread is unusually wide; review liquidity before publishing.')
            if rec.get('polymarket_spread') is not None and rec['polymarket_spread']>0.10:st.warning('Polymarket quoted bid–ask spread is unusually wide; review liquidity before publishing.')
            img=graphic(race,mapping['candidate'],rec['kalshi_probability'],rec['polymarket_probability'],rec['an_probability'],rec['asof_utc'][:16],rec['method'])
            st.download_button('Download branded comparison PNG',img,file_name=re.sub('[^a-z0-9]+','_',race.lower())+'_AN_odds.png',mime='image/png')
            st.markdown('#### Source contract checks')
            st.code(f"Kalshi: https://kalshi.com/markets/{mapping['kalshi_ticker'].lower()}\nPolymarket: https://polymarket.com/event/{mapping['polymarket_slug']}")

with tabs[2]:
    st.subheader('Historical election forecasting accuracy')
    st.markdown('This module only compares **resolved, matched YES contracts** at equivalent pre-election horizons. A long-run favourite hit rate is not an accuracy score: probability forecasts are evaluated using the Brier score.')
    if fit is None:
        st.info('Upload your matched resolved election CSV in the sidebar to test alternative weights. Until a rigorous holdout passes, the published AN probability is a transparent **50/50 market composite**.')
    else:
        st.markdown(f'**{fit.status}** — {fit.reason}')
        p,q,r=st.columns(3)
        p.metric('Unique resolved races',fit.rows)
        q.metric('Training races (earlier)',fit.train_rows)
        r.metric('Holdout races (later)',fit.test_rows)
        scores=pd.DataFrame([
            {'Forecast':'Kalshi','Brier score':fit.brier_kalshi},
            {'Forecast':'Polymarket','Brier score':fit.brier_polymarket},
            {'Forecast':'Equal-weight composite','Brier score':fit.brier_equal},
            {'Forecast':'Proposed accuracy-weighted blend','Brier score':fit.brier_weighted}
        ])
        st.dataframe(scores.style.format({'Brier score':'{:.4f}'}),use_container_width=True,hide_index=True)
        st.caption('Lower Brier is better. Holdout races occur after training races. This is a validation gate, not proof of future superiority; the same test should not be repeatedly tuned against.')
        st.write(f"**Candidate weights:** {explain_weight(fit.candidate_k_weight)} · **Deployed weights:** {explain_weight(fit.selected_k_weight)}")
        st.download_button('Download held-out forecasts CSV',fit.evaluation.to_csv(index=False).encode(),file_name='AN_backtest_holdout.csv',mime='text/csv')
    st.markdown('#### Required historical dataset')
    st.code('race_id,election_date,asof_utc,horizon_hours,kalshi_probability,polymarket_probability,outcome\nTEST-001,2024-11-05T23:00:00Z,2024-11-04T23:00:00Z,24,0.62,0.60,1\nTEST-002,2024-11-05T23:00:00Z,2024-11-04T23:00:00Z,24,0.44,0.48,0',language='csv')
    st.caption('Illustrative schema only — these TEST rows are invented examples, **not** historical research data. Do not use them to claim model accuracy.')
    st.markdown('`race_id` = unique election/YES proposition; `election_date` = event outcome date; `asof_utc` = timestamp of the archived quotes; `horizon_hours` = 24, 168 or 720; both probabilities as 0–1; `outcome` = eventual YES result (1 or 0). One row per race per horizon. To avoid hindsight leakage, the two historical quotes must be captured at the same point before the outcome was known.')

with tabs[3]:
    st.subheader('Publication exports & research controls')
    maprows=list(st.session_state['mappings'].values())
    if maprows:
        st.markdown('#### Approved mappings')
        st.dataframe(pd.DataFrame(maprows),use_container_width=True,hide_index=True)
        st.download_button('Download approved mappings JSON',json.dumps(maprows,indent=2).encode('utf-8'),file_name='an_approved_mappings.json',mime='application/json')
    saved=st.session_state['snapshots']
    if saved:
        st.markdown('#### Recorded source snapshots')
        snap_df=pd.DataFrame(saved)
        st.dataframe(snap_df,use_container_width=True,hide_index=True)
        st.download_button('Download snapshot audit CSV',snap_df.to_csv(index=False).encode(),file_name='an_election_snapshots.csv',mime='text/csv')
    else:st.info('Refresh an approved pair in Live comparison to create timestamped exportable research records.')
    st.markdown('#### Import previously approved mapping file')
    upload_map=st.file_uploader('JSON mapping export from this dashboard',type=['json'],key='map_restore')
    if upload_map is not None and st.button('Restore mapping approvals'):
        try:
            imported=json.load(upload_map)
            if not isinstance(imported,list) or not all(isinstance(x,dict) for x in imported):raise ValueError('Expected a list of mapping objects.')
            allow={'race','candidate','kalshi_ticker','kalshi_event','kalshi_yes','polymarket_id','polymarket_slug','polymarket_question','polymarket_token_yes','verified_at','verification'}
            new={}
            for m in imported:
                if not all(m.get(v) for v in ('race','kalshi_ticker','polymarket_id','polymarket_token_yes')):raise ValueError('Incomplete mapping row.')
                if not re.fullmatch('[A-Za-z0-9_-]{2,120}',str(m['kalshi_ticker'])):raise ValueError('Invalid ticker')
                if not re.fullmatch('[0-9]{1,30}',str(m['polymarket_id'])):raise ValueError('Invalid market ID')
                if not re.fullmatch('[0-9]{10,90}',str(m['polymarket_token_yes'])):raise ValueError('Invalid YES token')
                new[str(m['race'])]={k:v for k,v in m.items() if k in allow}
            st.session_state['mappings'].update(new)
            for name in new:
                st.session_state['live'].pop(name,None)
                st.session_state['series'].pop(name,None)
            st.success(f'Restored {len(new)} saved mappings. Re-verify contract rules if a market has changed.')
        except Exception as e:safer_error('Cannot restore mappings',e)
    st.markdown('#### Editorial rules')
    st.markdown('''
- Show source platform odds, the AN composite, exact time in UTC, and any available price movement. Never present price movement as vote-share change.
- Call the model **AN Market-Implied Chance of Winning** until independent historical testing validates accuracy weighting.
- Only call it **accuracy-adjusted** when the correct election-horizon holdout passes; the model never secretly uses one party or candidate as a preference.
- Do not imply that a midterm winner is known before the results are certified or reliably called.
- Do not aggregate market volumes from the two platforms as though their reported denominators are identical.
- Do not publish any pair until candidate, market-settlement terms, election date, and YES outcome are reviewed.
- A dashboard session is not durable storage; download mappings and research snapshots to preserve them. Refresh is manual, with 30–120s caching.
''')
    st.markdown('#### Research documentation')
    st.markdown('''[Kalshi public market API](https://docs.kalshi.com/api-reference/market/get-markets) · [Kalshi historical candlesticks](https://docs.kalshi.com/api-reference/market/get-market-candlesticks) · [Polymarket public market discovery](https://docs.polymarket.com/market-data/discover-markets) · [Polymarket price history](https://institute.polymarket.com/data)''')
    st.caption('Research prototype · Public, read-only APIs · Not a trading recommendation · Not independently live-tested against external network services in this build environment')
