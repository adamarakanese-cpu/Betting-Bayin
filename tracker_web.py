import os
import json
from urllib.parse import urlparse, parse_qs
from testing_tracker import get_dashboard_data, list_predictions, settle_prediction, export_csv

TRACKER_ADMIN_KEY = os.getenv("TRACKER_ADMIN_KEY", "").strip()


def _authorized(handler, query):
    if not TRACKER_ADMIN_KEY:
        return True
    key = (query.get("key") or [""])[0]
    header = handler.headers.get("X-Tracker-Key", "")
    return key == TRACKER_ADMIN_KEY or header == TRACKER_ADMIN_KEY


def _send(handler, code, body, ctype="application/json; charset=utf-8"):
    if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False, default=str)
    data = body.encode("utf-8") if isinstance(body, str) else body
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def _dashboard_html(key=""):
    safe_key = json.dumps(key)
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SHWE OHH Testing Dashboard</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0d1117;color:#e6edf3;margin:0}}main{{max-width:1320px;margin:auto;padding:20px}}h1{{margin:0 0 5px}}.muted{{color:#8b949e}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}}.card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:14px}}.big{{font-size:26px;font-weight:700;margin-top:7px}}.bar{{height:9px;background:#30363d;border-radius:8px;overflow:hidden;margin-top:8px}}.fill{{height:100%;background:#2f81f7}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:9px;border-bottom:1px solid #30363d;text-align:left;vertical-align:top}}th{{color:#8b949e;position:sticky;top:0;background:#161b22}}.wrap{{overflow:auto;max-height:520px;background:#161b22;border:1px solid #30363d;border-radius:12px}}button{{background:#238636;color:white;border:0;border-radius:7px;padding:6px 9px;margin:2px;cursor:pointer}}button.loss{{background:#da3633}}button.push{{background:#6e7681}}button.half{{background:#9e6a03}}select,input{{background:#0d1117;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px}}h2{{margin-top:28px}}.good{{color:#3fb950}}.bad{{color:#f85149}}.tag{{padding:2px 6px;border-radius:8px;background:#30363d;white-space:nowrap}}</style></head><body><main>
<h1>👑 SHWE OHH Testing Dashboard</h1><div class="muted">Prediction model is frozen while this dashboard measures real forward-test performance.</div>
<div style="margin-top:14px">Filter: <select id="source"><option value="">All</option><option value="prebet">PreBet</option><option value="livebet">LiveBet</option></select> <button onclick="load()">Refresh</button> <a id="csv" style="color:#58a6ff;margin-left:12px">Export CSV</a></div>
<div class="grid" id="cards"></div><div class="grid" id="progress"></div>
<h2>Market performance</h2><div class="wrap"><table id="markets"></table></div>
<h2>League performance</h2><div class="wrap"><table id="leagues"></table></div>
<h2>Odds & confidence calibration</h2><div class="grid"><div class="wrap"><table id="odds"></table></div><div class="wrap"><table id="confidence"></table></div></div>
<h2>Tips</h2><div class="wrap"><table id="tips"></table></div>
<script>
const KEY={safe_key}; const qp=()=>KEY?'?key='+encodeURIComponent(KEY):''; const pct=x=>(100*(x||0)).toFixed(1)+'%'; const n=x=>x==null?'—':Number(x).toFixed(2);
function tbl(id,rows){{let h='<tr><th>Group</th><th>N</th><th>Settled</th><th>Hit</th><th>ROI</th><th>Profit</th></tr>'; for(const r of rows||[])h+=`<tr><td>${{r.name}}</td><td>${{r.total}}</td><td>${{r.settled}}</td><td>${{pct(r.hit_rate)}}</td><td>${{pct(r.roi)}}</td><td>${{n(r.profit)}}</td></tr>`;document.getElementById(id).innerHTML=h}}
async function settle(id,outcome){{let actual=prompt('Actual placed odds (blank = stored odds):','');let score=prompt('Final score / note (optional):','');let body={{id,outcome,actual_odds:actual||null,final_score:score||null}};let r=await fetch('/api/testing/settle'+qp(),{{method:'POST',headers:{{'Content-Type':'application/json','X-Tracker-Key':KEY}},body:JSON.stringify(body)}});if(!r.ok)alert(await r.text());else load()}}
async function load(){{const s=document.getElementById('source').value;const u='/api/testing/summary'+qp()+(KEY?'&':'?')+'source='+encodeURIComponent(s);const r=await fetch(u,{{headers:{{'X-Tracker-Key':KEY}}}});if(!r.ok){{document.body.innerHTML='<pre>'+await r.text()+'</pre>';return}}const d=await r.json(),x=d.summary;document.getElementById('csv').href='/api/testing/export.csv'+qp()+(KEY?'&':'?')+'source='+encodeURIComponent(s);
const cards=[['Total',x.total],['Settled',x.settled],['Pending',x.pending],['Hit Rate',pct(x.hit_rate)],['ROI',pct(x.roi)],['Profit '+(d.recent[0]?.currency||'MMK'),n(x.profit)],['Avg Odds',n(x.avg_odds)],['Brier',n(x.brier)]];document.getElementById('cards').innerHTML=cards.map(c=>`<div class="card"><div class="muted">${{c[0]}}</div><div class="big">${{c[1]}}</div></div>`).join('');
let p=d.progress;document.getElementById('progress').innerHTML=[['PreBet 50',p.prebet],['LiveBet 50',p.livebet]].map(c=>`<div class="card"><b>${{c[0]}}</b><div class="big">${{c[1]}} / 50</div><div class="bar"><div class="fill" style="width:${{Math.min(100,c[1]*2)}}%"></div></div></div>`).join('');tbl('markets',d.by_market);tbl('leagues',d.by_league);tbl('odds',d.by_odds);tbl('confidence',d.by_confidence);
let h='<tr><th>ID</th><th>Time</th><th>Match</th><th>Tip</th><th>Odds</th><th>Chance</th><th>Trap</th><th>Status</th><th>Settle</th></tr>';for(const t of d.recent||[]){{let price=t.odds!=null?n(t.odds):(t.target_odds!=null?'Take '+n(t.target_odds)+'+':'—');h+=`<tr><td>#${{t.id}}</td><td>${{(t.created_at||'').replace('T',' ').slice(0,16)}}</td><td>${{t.home_team||'?'}} vs ${{t.away_team||'?'}}<br><span class="muted">${{t.competition||''}} ${{t.minute!=null?'· '+t.minute+"'":''}}</span></td><td>${{t.market||''}} — ${{t.selection||''}}<br><span class="tag">${{t.family||''}}</span></td><td>${{price}}</td><td>${{t.model_probability==null?'—':pct(t.model_probability)}}</td><td>${{t.trap_level||'—'}}</td><td>${{t.status}}</td><td>${{t.status==='pending'?`<button onclick="settle(${{t.id}},'win')">Win</button><button class="loss" onclick="settle(${{t.id}},'loss')">Loss</button><button class="half" onclick="settle(${{t.id}},'half_win')">½W</button><button class="half" onclick="settle(${{t.id}},'half_loss')">½L</button><button class="push" onclick="settle(${{t.id}},'push')">Push</button>`:''}}</td></tr>`}}document.getElementById('tips').innerHTML=h}}
load();</script></main></body></html>'''


def handle_tracker_get(handler):
    parsed = urlparse(handler.path)
    if not parsed.path.startswith("/testing") and not parsed.path.startswith("/api/testing"):
        return False
    query = parse_qs(parsed.query)
    if not _authorized(handler, query):
        _send(handler, 401, {"error":"unauthorized"})
        return True
    source = (query.get("source") or [None])[0] or None
    if parsed.path == "/testing":
        _send(handler, 200, _dashboard_html((query.get("key") or [""])[0]), "text/html; charset=utf-8")
    elif parsed.path == "/api/testing/summary":
        _send(handler, 200, get_dashboard_data(source))
    elif parsed.path == "/api/testing/tips":
        status = (query.get("status") or [None])[0]
        _send(handler, 200, list_predictions(source=source, status=status, limit=500))
    elif parsed.path == "/api/testing/export.csv":
        _send(handler, 200, export_csv(source), "text/csv; charset=utf-8")
    else:
        _send(handler, 404, {"error":"not found"})
    return True


def handle_tracker_post(handler):
    parsed = urlparse(handler.path)
    if parsed.path != "/api/testing/settle":
        return False
    query = parse_qs(parsed.query)
    if not _authorized(handler, query):
        _send(handler, 401, {"error":"unauthorized"})
        return True
    try:
        n = int(handler.headers.get("Content-Length", "0") or 0)
        body = json.loads(handler.rfile.read(n) or b"{}")
        row = settle_prediction(body.get("id"), body.get("outcome"), body.get("actual_odds"), body.get("final_score"), body.get("notes"))
        if not row:
            _send(handler, 404, {"error":"prediction not found"})
        else:
            _send(handler, 200, {"ok":True,"prediction":row})
    except Exception as e:
        _send(handler, 400, {"error":str(e)})
    return True
