#!/usr/bin/env python3
"""
SLS PerplexityBot 流量分析 — SLS Dashboard 风格 HTML 报告
"""
import os, sys, json, argparse
from datetime import datetime, timedelta, timezone
from collections import Counter
from dotenv import load_dotenv
from aliyun.log import LogClient, GetLogsRequest, GetHistogramsRequest

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

PROJECT = os.getenv("SLS_PROJECT", "")
LOGSTORE = os.getenv("SLS_LOGSTORE", "")
CST = timezone(timedelta(hours=8))
SLS_ENDPOINT = os.getenv("SLS_ENDPOINT", "")
SLS_AK_ID = os.getenv("SLS_ACCESS_KEY_ID", "")
SLS_AK_SECRET = os.getenv("SLS_ACCESS_KEY_SECRET", "")
UA_KEYWORD = "PerplexityBot"
REPORT_TOKEN = os.getenv("REPORT_TOKEN", "")

# ═══════════════════ 时间范围 ═══════════════════
def get_time_range(days_ago=0):
    now_cst = datetime.now(CST)
    today_5pm = now_cst.replace(hour=17, minute=0, second=0, microsecond=0)
    to_time = today_5pm + timedelta(days=1) if now_cst >= today_5pm else today_5pm
    to_time -= timedelta(days=days_ago)
    from_time = to_time - timedelta(days=1)
    return int(from_time.timestamp()), int(to_time.timestamp())

# ═══════════════════ SLS ═══════════════════
def get_client():
    if not SLS_AK_ID or not SLS_AK_SECRET:
        print("❌ 请设置 SLS_ACCESS_KEY_ID / SLS_ACCESS_KEY_SECRET")
        sys.exit(1)
    return LogClient(SLS_ENDPOINT, SLS_AK_ID, SLS_AK_SECRET)

def query_logs(client, query, from_ts, to_ts, limit=100, offset=0):
    req = GetLogsRequest(project=PROJECT, logstore=LOGSTORE,
                         fromTime=from_ts, toTime=to_ts,
                         query=query, line=limit, offset=offset, reverse=False)
    return [dict(l.get_contents()) for l in client.get_logs(req).get_logs()]

def fetch_all(client, from_ts, to_ts, page_size=100):
    all_logs, offset = [], 0
    q = f'* and http_user_agent : "{UA_KEYWORD}"'
    while True:
        batch = query_logs(client, q, from_ts, to_ts, page_size, offset)
        if not batch: break
        all_logs.extend(batch)
        if len(batch) < page_size: break
        offset += page_size
    return all_logs

def get_count(client, from_ts, to_ts):
    req = GetHistogramsRequest(project=PROJECT, logstore=LOGSTORE,
                                fromTime=from_ts, toTime=to_ts,
                                query=f'http_user_agent : "{UA_KEYWORD}"', topic="")
    return sum(h.get_count() for h in client.get_histograms(req).get_histograms())

# ═══════════════════ 本地分析 ═══════════════════
def fmt_bytes(b):
    if b < 1024: return f"{b} B"
    if b < 1048576: return f"{b/1024:.1f} KB"
    if b < 1073741824: return f"{b/1048576:.1f} MB"
    return f"{b/1073741824:.1f} GB"

def top_urls(logs, n=20):
    c = Counter()
    for l in logs: c[l.get("request_uri") or l.get("uri") or "?"] += 1
    return c.most_common(n)

def status_dist(logs):
    c = Counter()
    for l in logs: c[l.get("status", "0")] += 1
    return c.most_common(20)

def hourly(logs, from_ts, to_ts):
    c = Counter()
    for l in logs:
        try: dt = datetime.fromisoformat(l.get("@timestamp","")); c[dt.strftime("%m-%d %H:00")] += 1
        except: pass
    result, cur = [], datetime.fromtimestamp(from_ts, CST)
    end = datetime.fromtimestamp(to_ts, CST)
    while cur < end:
        hk = cur.strftime("%m-%d %H:00"); result.append({"hour": hk, "cnt": c.get(hk,0)}); cur += timedelta(hours=1)
    return result

def top_ips(logs, n=10):
    c = Counter()
    for l in logs: c[l.get("remote_addr","?")] += 1
    return c.most_common(n)

def total_bytes(logs):
    return sum(int(float(l.get("bytes_sent",0))) for l in logs)

# ═══════════════════ HTML ═══════════════════
def generate(from_ts, to_ts, total_cnt, urls, statuses, hours, ips, tbytes, logs, path):
    fs = datetime.fromtimestamp(from_ts, CST).strftime("%Y-%m-%d %H:%M")
    ts = datetime.fromtimestamp(to_ts, CST).strftime("%Y-%m-%d %H:%M")

    uv = len(set(l.get("remote_addr","") for l in logs))
    succ = sum(1 for l in logs if 200 <= int(l.get("status","0") or 0) < 400)
    avail = f"{(succ/total_cnt*100):.2f}" if total_cnt else "0"
    rts = [float(l.get("request_time",0)) for l in logs if l.get("request_time")]
    avg_rt = sum(rts)/len(rts) if rts else 0
    avg_qps = f"{total_cnt/86400:.2f}" if total_cnt else "0"
    s2xx = sum(c for s,c in statuses if 200 <= int(s) < 300)
    s3xx = sum(c for s,c in statuses if 300 <= int(s) < 400)
    s4xx = sum(c for s,c in statuses if 400 <= int(s) < 500)
    s5xx = sum(c for s,c in statuses if 500 <= int(s) < 600)
    errs = [l for l in logs if int(l.get("status","0") or 0) >= 400]
    anum = float(avail)
    ac = "#52c41a" if anum >= 99.9 else ("#faad14" if anum >= 99 else "#ff4d4f")

    # URL 表格
    ur = ""
    for i,(u,c) in enumerate(urls[:20],1):
        pct = f"{(c/total_cnt*100):.1f}%" if total_cnt else "0%"
        ul = [l for l in logs if (l.get("request_uri") or l.get("uri","")) == u]
        us = sum(1 for l in ul if 200 <= int(l.get("status","0") or 0) < 400)
        ua = f"{(us/c*100):.1f}%" if c else "0%"
        rl = [float(l.get("request_time",0)) for l in ul if l.get("request_time")]
        urt = sum(rl)/len(rl) if rl else 0
        ur += f"<tr><td>{i}</td><td class='mono' style='max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{u}</td><td>{c}</td><td>{pct}</td><td>{ua}</td><td>{urt*1000:.0f}ms</td></tr>"

    # IP 表格
    ir = ""
    for i,(ip,c) in enumerate(ips[:10],1):
        pct = f"{(c/total_cnt*100):.1f}%" if total_cnt else "0%"
        il = [l for l in logs if l.get("remote_addr","") == ip]
        isucc = sum(1 for l in il if 200 <= int(l.get("status","0") or 0) < 400)
        ifail = f"{((c-isucc)/c*100):.1f}%" if c else "0%"
        ir += f"<tr><td>{i}</td><td class='mono'>{ip}</td><td>{c}</td><td>{pct}</td><td>{ifail}</td></tr>"

    # 错误明细
    er = ""
    for i,l in enumerate(errs[:50],1):
        er += f"<tr><td>{i}</td><td><span class='tag err'>{l.get('status','?')}</span></td><td class='mono'>{l.get('host','?')}</td><td class='mono' style='max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>{l.get('request_uri') or l.get('uri','?')}</td><td class='mono'>{l.get('upstream_addr', l.get('server_addr','?'))}</td></tr>"

    over = f"<tr><td>PerplexityBot</td><td>{total_cnt}</td><td>{uv}</td><td>{avail}%</td><td>{avg_rt*1000:.0f}ms</td><td>{fmt_bytes(tbytes)}</td></tr>"

    hl = json.dumps([h["hour"] for h in hours])
    hc = json.dumps([int(h["cnt"]) for h in hours])
    pie = [d for d in [
        ({"name":"2xx","cnt":s2xx,"color":"#52c41a"} if s2xx else None),
        ({"name":"3xx","cnt":s3xx,"color":"#1890ff"} if s3xx else None),
        ({"name":"4xx","cnt":s4xx,"color":"#faad14"} if s4xx else None),
        ({"name":"5xx","cnt":s5xx,"color":"#ff4d4f"} if s5xx else None),
    ] if d]
    pj = json.dumps(pie)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PerplexityBot 流量报告 — {fs} ~ {ts}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:#f0f2f5;color:#333;line-height:1.5;min-height:100vh}}
.top-nav{{background:#fff;border-bottom:1px solid #e8e8e8;padding:10px 24px;display:flex;align-items:center;justify-content:space-between}}
.top-nav h1{{font-size:1rem;font-weight:600;color:#262626}}
.top-nav .meta{{font-size:.75rem;color:#8c8c8c}}
.top-nav .meta span{{margin-left:16px}}
.container{{max-width:1480px;margin:0 auto;padding:16px 20px 40px}}
.section-hdr{{display:flex;align-items:center;gap:8px;font-size:.88rem;font-weight:600;color:#1d39c4;padding:8px 14px;margin:20px 0 12px;background:linear-gradient(90deg,#e6f0ff,transparent);border-left:3px solid #1d39c4;border-radius:0 4px 4px 0}}
.section-hdr .dot{{width:8px;height:8px;border-radius:50%;background:#52c41a}}
.grid-24{{display:grid;grid-template-columns:repeat(24,1fr);gap:10px;margin-top:4px}}
.card{{background:#fff;border-radius:6px;border:1px solid #e8e8e8;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
.card-title{{font-size:.78rem;font-weight:600;color:#595959;margin-bottom:8px;display:flex;align-items:center;gap:6px}}
.card-body{{position:relative}}
.stat{{text-align:center;padding:10px 8px}}
.stat .label{{font-size:.7rem;color:#8c8c8c;margin-bottom:4px}}
.stat .val{{font-size:1.5rem;font-weight:700}}
.tag{{display:inline-block;padding:1px 8px;border-radius:3px;font-size:.72rem;font-weight:500}}
.tag.err{{background:#fff2f0;color:#ff4d4f;border:1px solid #ffccc7}}
.tbl-tight{{width:100%;border-collapse:collapse;font-size:.76rem}}
.tbl-tight th{{text-align:left;color:#8c8c8c;font-weight:500;padding:6px 8px;border-bottom:2px solid #f0f0f0;font-size:.7rem}}
.tbl-tight td{{padding:5px 8px;border-bottom:1px solid #fafafa}}
.tbl-tight tr:hover td{{background:#fafafa}}
.mono{{font-family:"SF Mono","Fira Code","Cascadia Code",monospace;font-size:.74rem}}
.footer{{text-align:center;padding:16px 0 8px;font-size:.72rem;color:#bfbfbf;border-top:1px solid #f0f0f0;margin-top:24px}}
.no-data{{text-align:center;color:#bfbfbf;padding:24px;font-size:.82rem}}
.scroll-x{{overflow-x:auto}}
@media(max-width:900px){{.grid-24{{display:flex;flex-direction:column;gap:10px}}}}
</style>
</head>
<body>
<div id="login" style="display:none;align-items:center;justify-content:center;min-height:100vh;background:#f0f2f5">
<div style="background:#fff;border-radius:6px;box-shadow:0 2px 12px rgba(0,0,0,.08);padding:44px;text-align:center;max-width:400px;width:90%">
<div style="font-size:2.5rem;margin-bottom:12px">&#128274;</div>
<h2 style="color:#262626;font-size:1rem;margin:0 0 8px">需要访问密钥</h2>
<p style="color:#8c8c8c;font-size:.82rem;margin:0 0 20px">在 URL 后添加 <code style="background:#f5f5f5;padding:2px 8px;border-radius:3px;color:#1d39c4">#token=密钥</code> 访问</p>
<form onsubmit="var t=document.getElementById('tk').value;if(t)location.hash='token='+encodeURIComponent(t);return false" style="display:flex;gap:8px">
<input id="tk" type="password" placeholder="输入访问密钥" style="flex:1;padding:8px 12px;border:1px solid #d9d9d9;border-radius:4px;font-size:.9rem;outline:none" autofocus>
<button type="submit" style="padding:8px 20px;background:#1d39c4;border:none;border-radius:4px;color:#fff;font-size:.9rem;cursor:pointer;font-weight:500">访问</button>
</form></div></div>

<div id="app" style="display:none">
<div class="top-nav"><div><h1>PerplexityBot 流量监控</h1><div class="meta"><span>📦 {PROJECT}</span><span>📋 {LOGSTORE}</span><span>🕐 {fs} ~ {ts}</span></div></div><div style="font-size:.72rem;color:#bfbfbf">生成: {datetime.now(CST).strftime("%Y-%m-%d %H:%M")}</div></div>
<div class="container">

<div class="section-hdr"><div class="dot"></div>PerplexityBot 爬虫流量</div>
<div class="grid-24">
<div class="card stat" style="grid-column:span 6"><div class="label">访问成功率</div><div class="val" style="color:{ac}">{avail}%</div><div style="font-size:.7rem;color:#8c8c8c">{succ}/{total_cnt}</div></div>
<div class="card stat" style="grid-column:span 3"><div class="label">PV</div><div class="val" style="color:#1d39c4">{total_cnt:,}</div><div style="font-size:.7rem;color:#8c8c8c">avg QPS: {avg_qps}</div></div>
<div class="card stat" style="grid-column:span 3"><div class="label">UV</div><div class="val" style="color:#262626">{uv}</div><div style="font-size:.7rem;color:#8c8c8c">独立来源IP</div></div>
<div class="card stat" style="grid-column:span 3"><div class="label">平均响应时间</div><div class="val" style="color:#262626">{avg_rt*1000:.0f}ms</div><div style="font-size:.7rem;color:#8c8c8c">&nbsp;</div></div>
<div class="card stat" style="grid-column:span 3"><div class="label">流量消耗</div><div class="val" style="color:#262626;font-size:1.2rem">{fmt_bytes(tbytes)}</div><div style="font-size:.7rem;color:#8c8c8c">&nbsp;</div></div>
<div class="card stat" style="grid-column:span 2"><div class="label">2xx</div><div class="val" style="color:#52c41a;font-size:1.1rem">{s2xx}</div></div>
<div class="card stat" style="grid-column:span 2"><div class="label">3xx</div><div class="val" style="color:#1890ff;font-size:1.1rem">{s3xx}</div></div>
<div class="card stat" style="grid-column:span 2"><div class="label">4xx</div><div class="val" style="color:#faad14;font-size:1.1rem">{s4xx}</div></div>
</div>

<div class="grid-24" style="margin-top:10px">
<div class="card" style="grid-column:span 12"><div class="card-title">🥧 状态码分布</div><div class="card-body"><canvas id="statusPie" style="max-height:260px"></canvas></div></div>
<div class="card" style="grid-column:span 12"><div class="card-title">📈 请求趋势 (小时级)</div><div class="card-body"><canvas id="hourlyBar" style="max-height:260px"></canvas></div></div>
</div>

<div class="grid-24" style="margin-top:10px">
<div class="card" style="grid-column:span 24"><div class="card-title">⚠️ 请求异常明细 (status ≥ 400)</div><div class="scroll-x">
{('<table class="tbl-tight"><thead><tr><th>#</th><th>状态码</th><th>域名</th><th>URI</th><th>Upstream</th></tr></thead><tbody>'+er+'</tbody></table>') if er else '<div class="no-data">无异常请求 🎉</div>'}
</div></div></div>

<div class="section-hdr"><div class="dot"></div>URL 与来源 IP 分析</div>
<div class="grid-24">
<div class="card" style="grid-column:span 14"><div class="card-title">🔗 URL 按 PV 排序</div><div class="scroll-x">
{('<table class="tbl-tight"><thead><tr><th>#</th><th>URL</th><th>PV</th><th>占比</th><th>成功率</th><th>平均RT</th></tr></thead><tbody>'+ur+'</tbody></table>') if ur else '<div class="no-data">暂无数据</div>'}
</div></div>
<div class="card" style="grid-column:span 10"><div class="card-title">🌐 来源 IP 按 PV 排序</div><div class="scroll-x">
{('<table class="tbl-tight"><thead><tr><th>#</th><th>IP</th><th>PV</th><th>占比</th><th>失败率</th></tr></thead><tbody>'+ir+'</tbody></table>') if ir else '<div class="no-data">暂无数据</div>'}
</div></div></div>

<div class="section-hdr"><div class="dot"></div>流量汇总</div>
<div class="grid-24">
<div class="card" style="grid-column:span 24"><div class="card-title">📋 概览</div><div class="scroll-x">
<table class="tbl-tight"><thead><tr><th>目标</th><th>PV</th><th>UV</th><th>成功率</th><th>平均RT</th><th>流量</th></tr></thead><tbody>{over}</tbody></table>
</div></div></div>

<div class="footer">数据源: SLS {PROJECT}/{LOGSTORE} &nbsp;·&nbsp; {fs} ~ {ts}</div>

</div></div>

<script>
// Token 验证 (放在 DOM 末尾确保元素已加载)
(function(){{
var T="{REPORT_TOKEN}";if(!T){{document.getElementById('app').style.display='block';return}}
var i='',h=window.location.hash;
if(h){{var x=h.indexOf('token=');if(x>=0)i=h.substring(x+6).split('&')[0]}}
if(!i){{var m=window.location.search.match(/[?&]token=([^&]+)/);if(m)i=m[1]}}
if(i===T){{document.getElementById('app').style.display='block';if(window.history&&window.history.replaceState)window.history.replaceState({{}},'',window.location.pathname)}}
else{{document.getElementById('login').style.display='flex'}}
}})();
</script>

<script>
// Chart.js 图表
(function(){{
var p={pj};if(p.length>0){{new Chart(document.getElementById('statusPie'),{{type:'doughnut',data:{{labels:p.map(function(d){{return d.name}}),datasets:[{{data:p.map(function(d){{return d.cnt}}),backgroundColor:p.map(function(d){{return d.color}}),borderColor:'#fff',borderWidth:2}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'bottom',labels:{{color:'#595959',padding:12,font:{{size:11}},usePointStyle:true}}}}}}}}}})}};
var l={hl},c={hc};if(l.length>0){{new Chart(document.getElementById('hourlyBar'),{{type:'bar',data:{{labels:l,datasets:[{{label:'请求数',data:c,backgroundColor:'#85a5ff',borderColor:'#597ef7',borderWidth:1,borderRadius:2}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{color:'#8c8c8c',maxRotation:45,font:{{size:9}}}},grid:{{display:false}}}},y:{{ticks:{{color:'#8c8c8c',stepSize:1}},grid:{{color:'#f0f0f0'}}}}}}}})}};
}})();
</script>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"✅ HTML 报告已生成: {path}")


# ═══════════════════ Main ═══════════════════
def main():
    parser = argparse.ArgumentParser(description="SLS PerplexityBot 流量分析")
    parser.add_argument("--days", type=int, default=0)
    parser.add_argument("--output", "-o", default="perplexitybot-report.html")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    fts, tts = get_time_range(days_ago=args.days)
    print(f"📅 {datetime.fromtimestamp(fts,CST).strftime('%Y-%m-%d %H:%M')} → {datetime.fromtimestamp(tts,CST).strftime('%Y-%m-%d %H:%M')} (CST)")
    print(f"📦 Project: {PROJECT}  📋 Logstore: {LOGSTORE}  🔍 UA: {UA_KEYWORD}")
    if args.dry_run: return

    client = get_client()
    print("⏳ 查询中...")
    total = get_count(client, fts, tts)
    print(f"  请求总数: {total:,}")
    if total == 0:
        generate(fts, tts, 0, [], [], [], [], 0, [], args.output)
        return

    logs = fetch_all(client, fts, tts)
    print(f"  获取 {len(logs)} 条日志")
    urls = top_urls(logs)
    st = status_dist(logs)
    hr = hourly(logs, fts, tts)
    ips = top_ips(logs)
    tb = total_bytes(logs)
    print(f"  状态码: {len(st)}种  URL: {len(urls)}个  IP: {len(ips)}个  流量: {fmt_bytes(tb)}")

    generate(fts, tts, total, urls, st, hr, ips, tb, logs,
             os.path.join(os.path.dirname(os.path.abspath(__file__)), args.output))


if __name__ == "__main__":
    main()