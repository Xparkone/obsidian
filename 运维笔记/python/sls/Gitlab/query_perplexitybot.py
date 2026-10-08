#!/usr/bin/env python3
"""从 SLS 拉取 openresty-szc 中 ai4s.itic-sci.com 的访问日志，按「前一天 17:00 ~ 运行时刻」生成仪表盘 HTML。

模版来源：scimaster 业务性能大盘（dashboard-1753251102794-253220）。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_VENV = ROOT / "venv"
_VENV_PY = _VENV / "bin" / "python"
if _VENV_PY.exists() and Path(sys.prefix).resolve() != _VENV.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), *sys.argv])

from aliyun.log import LogClient, GetLogsRequest
from aliyun.log.logexception import LogException
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

CST = timezone(timedelta(hours=8))
PROJECT = os.getenv("SLS_PROJECT", "")
LOGSTORE = os.getenv("SLS_LOGSTORE", "")
SLS_ENDPOINT = os.getenv("SLS_ENDPOINT", "")
SLS_AK_ID = os.getenv("SLS_ACCESS_KEY_ID", "")
SLS_AK_SECRET = os.getenv("SLS_ACCESS_KEY_SECRET", "")

TARGET_HOST = "ai4s.itic-sci.com"
BASE_FILTER = (
    os.getenv("SLS_QUERY") or f'host: "{TARGET_HOST}" and status: *'
).strip() or "*"

CST_HOUR = "date_format(from_unixtime(__time__ + 28800), '%H:00')"


def get_time_range(days_ago: int = 0, date: str | None = None) -> tuple[int, int]:
    """返回 [from, to)：前一天 17:00 → 程序触发时刻（东八区）。"""
    if date:
        end = datetime.strptime(date, "%Y-%m-%d").replace(
            tzinfo=CST, hour=17, minute=0, second=0, microsecond=0
        )
        start = end - timedelta(days=1)
    else:
        end = datetime.now(CST) - timedelta(days=days_ago)
        start = (end - timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
    return int(start.timestamp()), int(end.timestamp())


def get_client() -> LogClient:
    if not SLS_AK_ID or not SLS_AK_SECRET:
        raise RuntimeError("请在 .env 中设置 SLS_ACCESS_KEY_ID / SLS_ACCESS_KEY_SECRET")
    if not SLS_ENDPOINT or not PROJECT or not LOGSTORE:
        raise RuntimeError("请在 .env 中设置 SLS_ENDPOINT / SLS_PROJECT / SLS_LOGSTORE")
    return LogClient(SLS_ENDPOINT, SLS_AK_ID, SLS_AK_SECRET)


def stamp_now() -> str:
    return datetime.now(CST).strftime("%Y%m%d-%H%M%S")


def default_output_path(stamp: str | None = None) -> Path:
    reports = ROOT / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    stamp = stamp or stamp_now()
    path = reports / f"{stamp}.html"
    n = 1
    while path.exists():
        path = reports / f"{stamp}-{n}.html"
        n += 1
    return path


def run_sql(client: LogClient, sql: str, from_ts: int, to_ts: int, line: int = 1000) -> list[dict]:
    req = GetLogsRequest(
        project=PROJECT,
        logstore=LOGSTORE,
        fromTime=from_ts,
        toTime=to_ts,
        query=sql,
        line=line,
        offset=0,
        reverse=False,
        power_sql=True,
        accurate_query=True,
    )
    return [dict(item.get_contents()) for item in client.get_logs(req).get_logs()]


def build_queries(base: str) -> dict[str, str]:
    return {
        "availability": (
            f"{base} | select count(1) as pv, "
            f"round(sum(case when status < 500 then 1 else 0 end) * 100.0 / count(1), 2) as s_request_rate "
            f"from log"
        ),
        "pv": f"{base} | SELECT COUNT(*) as pv from log",
        "uv": f"{base} | SELECT COUNT(DISTINCT proxy_add_x_forwarded_for) as uv from log",
        "status_pie": (
            f"{base} | select status as request_status, count(*) as pv from log "
            f"group by request_status limit 10000"
        ),
        "status_4xx": (
            f"{base} and status >= 400 and status < 500 | "
            f"select status as request_status, count(*) as pv from log group by request_status limit 10000"
        ),
        "status_5xx": (
            f"{base} and status >= 500 and status < 600 | "
            f"select status as request_status, count(*) as pv from log group by request_status limit 10000"
        ),
        "compare_pv": (
            f"{base} | select t, diff[1] as today, diff[2] as yestoday, diff[3] as week, "
            f"diff[4] as percentage_day, diff[5] as percentage_week from ("
            f"select t, compare(pv, 86400, 604800) as diff from ("
            f"select count(1) as pv, {CST_HOUR} as t from log group by t limit 10000"
            f") group by t order by t limit 10000)"
        ),
        "compare_rt": (
            f"{base} | select t, diff[1] as today, diff[2] as yestoday, diff[3] as week, "
            f"diff[4] as percentage_day, diff[5] as percentage_week from ("
            f"select t, compare(rt, 86400, 604800) as diff from ("
            f"select avg(request_time) as rt, {CST_HOUR} as t from log group by t limit 10000"
            f") group by t order by t limit 10000)"
        ),
        "percentile": (
            f"{base} | SELECT approx_percentile(request_time, 0.90) AS percentile_90, "
            f"approx_percentile(request_time, 0.95) AS percentile_95, "
            f"approx_percentile(request_time, 0.99) AS percentile_99, "
            f"{CST_HOUR} AS t from log GROUP BY t ORDER BY t LIMIT 10000"
        ),
        "overview": (
            f"{base} | SELECT host, COUNT(1) AS pv, COUNT(DISTINCT proxy_add_x_forwarded_for) AS uv, "
            f'ROUND(SUM(CASE WHEN status < 500 THEN 1 ELSE 0 END) * 100.0 / COUNT(1), 2) AS "访问成功率(%)", '
            f'ROUND(AVG(request_time) * 1000, 3) AS "平均延迟(ms)", '
            f'ROUND(APPROX_PERCENTILE(request_time, 0.9) * 1000, 3) AS "P90延迟(ms)", '
            f'ROUND(APPROX_PERCENTILE(request_time, 0.99) * 1000, 3) AS "P99延迟(ms)" '
            f"from log WHERE host != '' GROUP BY host ORDER BY pv DESC LIMIT 100"
        ),
        "url_pv": (
            f"{base} | SELECT coalesce(url_extract_path(uri), uri) AS uri, count(1) AS pv, "
            f'round(sum(CASE WHEN status < 500 THEN 1 ELSE 0 END) * 100.0 / count(1), 2) AS "访问成功率(%)", '
            f'round(avg(request_time) * 1000, 3) AS "平均延迟(ms)", '
            f'round(sum(request_length) / 1024.0, 3) AS "入流量(KB)" '
            f"from log GROUP BY uri ORDER BY pv DESC LIMIT 100"
        ),
        "url_rt": (
            f"{base} | SELECT coalesce(url_extract_path(uri), uri) AS uri, count(1) AS pv, "
            f'round(sum(CASE WHEN status < 500 THEN 1 ELSE 0 END) * 100.0 / count(1), 2) AS "访问成功率(%)", '
            f'round(avg(request_time) * 1000, 3) AS "平均延迟(ms)", '
            f'round(sum(request_length) / 1024.0, 3) AS "入流量(KB)" '
            f'from log GROUP BY uri ORDER BY "平均延迟(ms)" DESC LIMIT 100'
        ),
        "errors": (
            f"{base} and status >= 500 | SELECT host AS \"域名\", status AS \"状态码\", "
            f"split_part(http_referer, '?', 1) AS \"请求来源\", split_part(uri, '?', 1) AS uri "
            f"from log LIMIT 1000"
        ),
        "error_agg": (
            f"{base} and status >= 500 | SELECT "
            f"coalesce(url_extract_path(uri), split_part(uri, '?', 1), uri) AS uri, "
            f"status, count(1) AS pv from log "
            f"group by uri, status order by pv desc limit 30"
        ),
        "err_5xx": (
            f"{base} and status >= 500 and status < 600 | SELECT "
            f"coalesce(url_extract_path(uri), uri) AS uri, status, count(1) AS pv from log "
            f"group by uri, status order by pv desc limit 20"
        ),
        "err_5xx_up": (
            f"{base} and status >= 500 and status < 600 | SELECT "
            f"upstream_addr AS addr, count(1) AS pv from log "
            f"group by addr order by pv desc limit 10"
        ),
        "up_pv": (
            f"{base} | SELECT upstream_addr AS addr, COUNT(1) AS pv, "
            f'ROUND(SUM(CASE WHEN status < 500 THEN 1 ELSE 0 END) * 100.0 / COUNT(1), 2) AS "访问成功率(%)", '
            f'ROUND(AVG(request_time) * 1000, 3) AS "平均延迟(ms)", '
            f'ROUND(SUM(request_length) / 1024.0, 3) AS "入流量(KB)" '
            f"from log GROUP BY addr HAVING LENGTH(addr) > 2 ORDER BY pv DESC LIMIT 100"
        ),
        "up_rt": (
            f"{base} | SELECT upstream_addr AS addr, COUNT(1) AS pv, "
            f'ROUND(SUM(CASE WHEN status < 500 THEN 1 ELSE 0 END) * 100.0 / COUNT(1), 2) AS "访问成功率(%)", '
            f'ROUND(AVG(request_time) * 1000, 3) AS "平均延迟(ms)", '
            f'ROUND(APPROX_PERCENTILE(request_time, 0.9) * 1000, 3) AS "P90延迟(ms)", '
            f'ROUND(APPROX_PERCENTILE(request_time, 0.99) * 1000, 3) AS "P99延迟(ms)" '
            f'from log GROUP BY addr HAVING LENGTH(addr) > 2 ORDER BY "平均延迟(ms)" DESC LIMIT 100'
        ),
        "up_fail": (
            f"{base} | SELECT upstream_addr AS addr, COUNT(1) AS pv, "
            f'ROUND(SUM(CASE WHEN status < 500 THEN 1 ELSE 0 END) * 100.0 / COUNT(1), 2) AS "访问成功率(%)", '
            f'ROUND(AVG(request_time) * 1000, 3) AS "平均延迟(ms)", '
            f'ROUND(APPROX_PERCENTILE(request_time, 0.9) * 1000, 3) AS "P90延迟(ms)", '
            f'ROUND(APPROX_PERCENTILE(request_time, 0.99) * 1000, 3) AS "P99延迟(ms)" '
            f'from log GROUP BY addr HAVING LENGTH(addr) > 2 ORDER BY "访问成功率(%)" ASC LIMIT 100'
        ),
    }


FALLBACK_SQL = {
    "compare_pv": (
        f"{BASE_FILTER} | select {CST_HOUR} as t, count(1) as today from log group by t order by t limit 10000"
    ),
    "compare_rt": (
        f"{BASE_FILTER} | select {CST_HOUR} as t, avg(request_time) as today from log group by t order by t limit 10000"
    ),
    "url_pv": (
        f"{BASE_FILTER} | SELECT uri, count(1) AS pv, "
        f'round(sum(CASE WHEN status < 500 THEN 1 ELSE 0 END) * 100.0 / count(1), 2) AS "访问成功率(%)", '
        f'round(avg(request_time) * 1000, 3) AS "平均延迟(ms)", '
        f'round(sum(request_length) / 1024.0, 3) AS "入流量(KB)" '
        f"from log GROUP BY uri ORDER BY pv DESC LIMIT 100"
    ),
}


def fetch_all(client: LogClient, from_ts: int, to_ts: int) -> dict[str, list[dict]]:
    sqls = build_queries(BASE_FILTER)
    results: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}

    def _one(name: str, sql: str) -> tuple[str, list[dict] | None, str | None]:
        try:
            return name, run_sql(client, sql, from_ts, to_ts), None
        except LogException as exc:
            return name, None, f"{exc.get_error_code()}: {exc.get_error_message()}"
        except Exception as exc:  # noqa: BLE001
            return name, None, str(exc)

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_one, name, sql) for name, sql in sqls.items()]
        for fut in as_completed(futs):
            name, rows, err = fut.result()
            if err:
                errors[name] = err
                results[name] = []
                print(f"  ! {name}: {err}")
            else:
                results[name] = rows or []
                print(f"  · {name}: {len(results[name])} 行")

    for name, sql in FALLBACK_SQL.items():
        if results.get(name):
            continue
        if name not in errors and name not in ("url_pv",):
            continue
        try:
            results[name] = run_sql(client, sql, from_ts, to_ts)
            print(f"  · {name} (fallback): {len(results[name])} 行")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {name} fallback: {exc}")
            results[name] = results.get(name) or []

    return results


def g(row: dict, *keys: str, default=""):
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    lower = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key.lower() in lower and lower[key.lower()] not in (None, ""):
            return lower[key.lower()]
    return default


def to_float(value, default=0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value, default=0) -> int:
    return int(to_float(value, default))


def fmt_num(value, digits=0) -> str:
    number = to_float(value, 0)
    if digits == 0:
        return f"{int(round(number)):,}"
    return f"{number:,.{digits}f}"


def rate_color(value) -> str:
    number = to_float(value, -1)
    if number < 0:
        return "#8c8c8c"
    if number >= 99.9:
        return "#52c41a"
    if number >= 99:
        return "#faad14"
    return "#ff4d4f"


def status_color(code) -> str:
    number = to_int(code, 0)
    if 200 <= number < 300:
        return "#52c41a"
    if 300 <= number < 400:
        return "#1890ff"
    if 400 <= number < 500:
        return "#faad14"
    return "#ff4d4f"


def js(data) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def cell(value, css="") -> str:
    text = html.escape("" if value is None else str(value))
    cls = f" class='{css}'" if css else ""
    return f"<td{cls}>{text}</td>"


def render_table(headers: list[str], rows: list[dict], keys: list[str], mono: set[str] | None = None) -> str:
    if not rows:
        return '<div class="no-data">暂无数据</div>'
    mono = mono or set()
    th = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = []
    for row in rows:
        tds = []
        for key in keys:
            raw = g(row, key)
            if key in {"pv", "uv"}:
                raw = fmt_num(raw)
            elif any(token in key for token in ("成功率", "延迟", "流量", "percentile", "today", "week")):
                try:
                    raw = fmt_num(raw, 2 if "成功率" in key or "流量" in key else 1)
                except Exception:
                    pass
            tds.append(cell(raw, "mono" if key in mono or key in {"uri", "addr", "域名"} else ""))
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="scroll-x"><table class="tbl"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def pie_payload(rows: list[dict]) -> list[dict]:
    items = []
    for row in rows:
        code = str(g(row, "request_status", "status") or "?")
        items.append({
            "name": code,
            "cnt": to_int(g(row, "pv")),
            "color": status_color(code),
        })
    items.sort(key=lambda x: x["cnt"], reverse=True)
    return items


def fill_cycle_hours(
    rows: list[dict],
    from_ts: int | None = None,
    to_ts: int | None = None,
) -> list[dict]:
    by_t = {str(g(r, "t")): r for r in rows}
    labels: list[str] = []
    if from_ts is not None and to_ts is not None:
        cur = datetime.fromtimestamp(from_ts, CST).replace(minute=0, second=0, microsecond=0)
        end = datetime.fromtimestamp(to_ts, CST)
        seen: set[str] = set()
        while cur < end:
            label = cur.strftime("%H:00")
            if label in seen:
                break
            seen.add(label)
            labels.append(label)
            cur += timedelta(hours=1)
    else:
        hour = 17
        for _ in range(24):
            labels.append(f"{hour:02d}:00")
            hour = (hour + 1) % 24
    filled = []
    for label in labels:
        row = dict(by_t.get(label) or {})
        row["t"] = label
        filled.append(row)
    return filled


def series_compare(
    rows: list[dict],
    value_scale: float = 1.0,
    from_ts: int | None = None,
    to_ts: int | None = None,
) -> dict:
    if not rows:
        return {"labels": [], "today": [], "yesterday": [], "week": []}
    ordered = fill_cycle_hours(rows, from_ts, to_ts)
    return {
        "labels": [str(g(r, "t")) for r in ordered],
        "today": [to_float(g(r, "today")) * value_scale for r in ordered],
        "yesterday": [to_float(g(r, "yestoday", "yesterday")) * value_scale for r in ordered],
        "week": [to_float(g(r, "week")) * value_scale for r in ordered],
    }


def series_percentile(
    rows: list[dict],
    from_ts: int | None = None,
    to_ts: int | None = None,
) -> dict:
    if not rows:
        return {"labels": [], "p90": [], "p95": [], "p99": []}
    ordered = fill_cycle_hours(rows, from_ts, to_ts)
    return {
        "labels": [str(g(r, "t")) for r in ordered],
        "p90": [to_float(g(r, "percentile_90")) * 1000 for r in ordered],
        "p95": [to_float(g(r, "percentile_95")) * 1000 for r in ordered],
        "p99": [to_float(g(r, "percentile_99")) * 1000 for r in ordered],
    }


def analyze(
    data: dict[str, list[dict]],
    pv: int,
    uv: int,
    rate,
    from_ts: int | None = None,
    to_ts: int | None = None,
) -> dict:
    """根据已查出的聚合结果做结论，不编造数据。"""
    findings: list[dict] = []
    rate_num = to_float(rate, -1) if pv else -1
    status_rows = data.get("status_pie") or []
    status_map = {str(g(r, "request_status", "status")): to_int(g(r, "pv")) for r in status_rows}

    s5 = sum(c for s, c in status_map.items() if s.isdigit() and 500 <= int(s) < 600)

    if pv == 0:
        findings.append({
            "level": "warn",
            "title": "本周期无访问日志",
            "detail": "请核对查询时间窗、Project 与 Logstore 配置。",
        })
    elif s5:
        findings.append({
            "level": "danger",
            "title": f"服务可用率下降：{rate_num:.2f}%（PV {fmt_num(pv)} / UV {fmt_num(uv)}）",
            "detail": f"统计周期内出现 HTTP 500 {fmt_num(s5)} 次，建议结合接口与 Upstream 定位。",
        })
    elif rate_num >= 0:
        findings.append({
            "level": "ok",
            "title": f"服务可用率正常：{rate_num:.2f}%（PV {fmt_num(pv)} / UV {fmt_num(uv)}）",
            "detail": "统计周期内未观测到 HTTP 500。",
        })

    err_agg = data.get("error_agg") or []
    top_err = err_agg[0] if err_agg else None

    skip_fail = {"null", "", "none"}
    if top_err:
        skip_fail.add(str(g(top_err, "uri") or ""))
    fail_urls = []
    for row in data.get("url_pv") or []:
        uri = str(g(row, "uri") or "")
        cnt = to_int(g(row, "pv"))
        succ = to_float(g(row, "访问成功率(%)"), 100)
        if uri.lower() in skip_fail or "favicon.ico" in uri:
            continue
        if cnt >= 50 and succ < 50:
            fail_urls.append((uri, cnt, succ))
    fail_urls.sort(key=lambda x: x[1], reverse=True)
    for uri, cnt, succ in fail_urls[:3]:
        findings.append({
            "level": "warn" if succ >= 10 else "danger",
            "title": f"接口成功率偏低：{uri}",
            "detail": f"请求量 {fmt_num(cnt)}，成功率 {succ:.2f}%。",
        })

    cmp_rows = fill_cycle_hours(data.get("compare_pv") or [], from_ts, to_ts)
    today_sum = sum(to_float(g(r, "today")) for r in cmp_rows)
    yest_sum = sum(to_float(g(r, "yestoday", "yesterday")) for r in cmp_rows)
    if yest_sum > 0:
        delta = (today_sum - yest_sum) / yest_sum * 100
        findings.append({
            "level": "ok",
            "title": f"环比昨日同时段 {delta:+.1f}%",
            "detail": f"本周期请求 {fmt_num(today_sum, 0)}，昨日同时段 {fmt_num(yest_sum, 0)}。",
        })
        peak = max(cmp_rows, key=lambda r: to_float(g(r, "today")))
        findings.append({
            "level": "ok",
            "title": f"流量峰值出现在 {g(peak, 't')}",
            "detail": f"该小时请求约 {fmt_num(g(peak, 'today'))} 次（东八区）。",
        })

    if not findings:
        findings.append({
            "level": "ok",
            "title": "服务运行正常",
            "detail": "统计周期内未观测到 HTTP 500。",
        })

    overall = "ok"
    if any(f["level"] == "danger" for f in findings):
        overall = "danger"
    elif any(f["level"] == "warn" for f in findings):
        overall = "warn"
    headline = findings[0]["title"] if findings else "分析完成"
    return {"overall": overall, "headline": headline, "findings": findings}


def _top_uri_line(rows: list[dict], n: int = 3) -> str:
    parts = []
    for row in (rows or [])[:n]:
        uri = str(g(row, "uri") or "（空）")
        parts.append(f"{uri} × {fmt_num(g(row, 'pv'))}")
    return "；".join(parts) if parts else "无"


def analyze_exceptions(data: dict[str, list[dict]], pv: int) -> dict:
    """只分析 HTTP 500（含 5xx）。"""
    items: list[dict] = []
    status_rows = data.get("status_pie") or []
    status_map = {str(g(r, "request_status", "status")): to_int(g(r, "pv")) for r in status_rows}
    n5 = sum(c for s, c in status_map.items() if s.isdigit() and 500 <= int(s) < 600)
    pie5 = data.get("status_5xx") or []
    rows5 = data.get("err_5xx") or []
    ups = data.get("err_5xx_up") or []

    if not n5:
        return {"overall": "ok", "items": []}

    codes = "、".join(
        f"{g(r, 'request_status', 'status')} × {fmt_num(g(r, 'pv'))}"
        for r in pie5
    ) or "暂无明细"
    items.append({
        "level": "danger",
        "title": f"HTTP 500：{fmt_num(n5)} 次"
        + (f"（占比 {n5 / pv * 100:.2f}%）" if pv else ""),
        "detail": f"状态码构成：{codes}。建议按接口与 Upstream 排查超时、连接失败及进程健康状况。",
    })
    if rows5:
        items.append({
            "level": "danger",
            "title": "HTTP 500 主要分布接口",
            "detail": _top_uri_line(rows5, 8) + "。",
        })
    if ups:
        up_line = "、".join(
            f"{g(r, 'addr') or '（空）'} × {fmt_num(g(r, 'pv'))}" for r in ups[:5]
        )
        items.append({
            "level": "warn",
            "title": "HTTP 500 关联 Upstream",
            "detail": up_line + "。",
        })

    overall = "danger" if any(x["level"] == "danger" for x in items) else "warn"
    return {"overall": overall, "items": items}


def render_exceptions(exc: dict) -> str:
    color = {"ok": "#52c41a", "warn": "#faad14", "danger": "#ff4d4f"}.get(exc["overall"], "#8c8c8c")
    blocks = []
    for i, f in enumerate(exc["items"], 1):
        lc = {"ok": "#52c41a", "warn": "#d48806", "danger": "#cf1322"}.get(f["level"], "#595959")
        tag = {"ok": "正常", "warn": "关注", "danger": "异常"}.get(f["level"], "")
        blocks.append(
            "<div class='finding'>"
            f"<div class='finding-hd'><span class='tag' style='background:{lc}'>{tag}</span>"
            f"<strong>{i}. {html.escape(str(f['title']))}</strong></div>"
            f"<p>{html.escape(str(f['detail']))}</p></div>"
        )
    return (
        f"<div class='card analysis' style='grid-column:span 24;border-left:4px solid {color}'>"
        f"<h3>HTTP 500 异常分析</h3>"
        f"{''.join(blocks)}</div>"
    )


def render_analysis(analysis: dict) -> str:
    color = {"ok": "#52c41a", "warn": "#faad14", "danger": "#ff4d4f"}.get(analysis["overall"], "#8c8c8c")
    items = []
    for i, f in enumerate(analysis["findings"], 1):
        lc = {"ok": "#52c41a", "warn": "#d48806", "danger": "#cf1322"}.get(f["level"], "#595959")
        tag = {"ok": "正常", "warn": "关注", "danger": "异常"}.get(f["level"], "")
        items.append(
            "<div class='finding'>"
            f"<div class='finding-hd'><span class='tag' style='background:{lc}'>{tag}</span>"
            f"<strong>{i}. {html.escape(str(f['title']))}</strong></div>"
            f"<p>{html.escape(str(f['detail']))}</p></div>"
        )
    return (
        f"<div class='card analysis' style='grid-column:span 24;border-left:4px solid {color}'>"
        f"<h3>数据分析结论</h3>"
        f"{''.join(items)}</div>"
    )


def generate_html(from_ts: int, to_ts: int, data: dict[str, list[dict]], path: Path) -> None:
    start = datetime.fromtimestamp(from_ts, CST).strftime("%Y-%m-%d %H:%M")
    end = datetime.fromtimestamp(to_ts, CST).strftime("%Y-%m-%d %H:%M")

    avail_row = (data.get("availability") or [{}])[0]
    pv = to_int(g(avail_row, "pv") or g((data.get("pv") or [{}])[0], "pv"))
    uv = to_int(g((data.get("uv") or [{}])[0], "uv"))
    rate = g(avail_row, "s_request_rate")
    rate_text = "-" if rate in ("", None) and pv == 0 else f"{to_float(rate):.2f}%"
    ac = rate_color(rate if pv else -1)
    analysis = analyze(data, pv, uv, rate, from_ts, to_ts)
    exceptions = analyze_exceptions(data, pv)
    analysis_section = f"<div class='grid'>{render_analysis(analysis)}</div>"
    exc_section = (
        f"<div class='grid'>{render_exceptions(exceptions)}</div>"
        if exceptions["items"]
        else ""
    )

    html_out = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>访问日志监控 — {start} ~ {end}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:#f0f2f5;color:#333;line-height:1.5}}
.wrap{{max-width:1480px;margin:0 auto;padding:16px 20px 40px}}
.banner{{background:rgba(102,187,85,.85);color:#fff;font-size:1.05rem;font-weight:700;text-align:center;padding:10px 16px;border:1px solid #666;margin:8px 0 12px}}
.grid{{display:grid;grid-template-columns:repeat(24,1fr);gap:10px;margin-bottom:10px}}
.card{{background:#fff;border:1px solid #e8e8e8;border-radius:4px;padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.04);min-height:0}}
.card h3{{font-size:.78rem;font-weight:600;color:#595959;margin-bottom:8px}}
.stat{{text-align:center;display:flex;flex-direction:column;justify-content:center;min-height:110px}}
.stat .label{{font-size:.72rem;color:#8c8c8c;margin-bottom:6px}}
.stat .val{{font-size:1.7rem;font-weight:700}}
.stat .sub{{font-size:.72rem;color:#8c8c8c;margin-top:4px}}
.stack{{display:flex;flex-direction:column;gap:10px}}
.tbl{{width:100%;border-collapse:collapse;font-size:.76rem}}
.tbl th{{text-align:left;color:#8c8c8c;font-weight:500;padding:6px 8px;border-bottom:2px solid #f0f0f0;font-size:.7rem;white-space:nowrap}}
.tbl td{{padding:5px 8px;border-bottom:1px solid #fafafa}}
.tbl tr:hover td{{background:#fafafa}}
.mono{{font-family:"SF Mono","Fira Code",monospace;font-size:.74rem;max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.scroll-x{{overflow:auto;max-height:280px}}
.no-data{{text-align:center;color:#bfbfbf;padding:28px 8px;font-size:.82rem}}
.chart-box{{position:relative;height:220px}}
.chart-box.tall{{height:260px}}
.banner .when{{font-size:1.05rem}}
.banner .host{{font-size:.82rem;font-weight:500;opacity:.92;margin-top:2px}}
.analysis .headline{{font-size:1rem;font-weight:600;margin:8px 0 12px}}
.finding{{padding:8px 0;border-bottom:1px solid #f0f0f0}}
.finding:last-child{{border-bottom:none}}
.finding-hd{{display:flex;align-items:center;gap:8px;margin-bottom:4px}}
.finding p{{color:#595959;font-size:.82rem;margin:0 0 0 52px}}
.tag{{display:inline-block;color:#fff;font-size:.7rem;padding:1px 8px;border-radius:3px;font-weight:500}}
@media(max-width:980px){{.grid{{display:flex;flex-direction:column}}}}
</style>
</head>
<body>
<div id="app">
  <div class="wrap">
    <div class="banner">
      <div class="when">{html.escape(start)} ～ {html.escape(end)}</div>
      <div class="host">{html.escape(TARGET_HOST)}</div>
    </div>

    {analysis_section}
    {exc_section}

    <div class="grid">
      <div class="card stat" style="grid-column:span 6">
        <div class="label">服务可用率</div>
        <div class="val" style="color:{ac}">{rate_text}</div>
        <div class="sub">{html.escape(TARGET_HOST)}</div>
      </div>
      <div class="stack" style="grid-column:span 6">
        <div class="card stat" style="min-height:90px">
          <div class="label">PV</div>
          <div class="val" style="color:#1d39c4">{fmt_num(pv)}</div>
        </div>
        <div class="card stat" style="min-height:90px">
          <div class="label">UV</div>
          <div class="val">{fmt_num(uv)}</div>
          <div class="sub">独立 proxy_add_x_forwarded_for</div>
        </div>
      </div>
      <div class="card" style="grid-column:span 6">
        <h3>状态码情况</h3>
        <div class="chart-box"><canvas id="pieStatus"></canvas></div>
      </div>
      <div class="stack" style="grid-column:span 6">
        <div class="card">
          <h3>客户端异常状态码</h3>
          <div class="chart-box" style="height:110px"><canvas id="pie4xx"></canvas></div>
        </div>
        <div class="card">
          <h3>服务端异常状态码</h3>
          <div class="chart-box" style="height:110px"><canvas id="pie5xx"></canvas></div>
        </div>
      </div>
    </div>

    <div class="grid">
      <div class="card" style="grid-column:span 12">
        <h3>请求环比</h3>
        <div class="chart-box tall"><canvas id="linePv"></canvas></div>
      </div>
      <div class="card" style="grid-column:span 12">
        <h3>平均响应时间</h3>
        <div class="chart-box tall"><canvas id="lineRt"></canvas></div>
      </div>
    </div>

    <div class="grid">
      <div class="card" style="grid-column:span 24">
        <h3>分位值 request_time</h3>
        <div class="chart-box"><canvas id="linePct"></canvas></div>
      </div>
    </div>

    <div class="grid">
      <div class="card" style="grid-column:span 24">
        <h3>整体概括</h3>
        {render_table(
            ["host", "PV", "UV", "访问成功率(%)", "平均延迟(ms)", "P90延迟(ms)", "P99延迟(ms)"],
            data.get("overview") or [],
            ["host", "pv", "uv", "访问成功率(%)", "平均延迟(ms)", "P90延迟(ms)", "P99延迟(ms)"],
            {"host"},
        )}
      </div>
    </div>

    <div class="grid">
      <div class="card" style="grid-column:span 7">
        <h3>HTTP 500 异常明细</h3>
        {render_table(
            ["域名", "状态码", "请求来源", "uri"],
            data.get("errors") or [],
            ["域名", "状态码", "请求来源", "uri"],
            {"域名", "uri", "请求来源"},
        )}
      </div>
      <div class="card" style="grid-column:span 8">
        <h3>URL 按照 PV 维度进行排序</h3>
        {render_table(
            ["uri", "PV", "访问成功率(%)", "平均延迟(ms)", "入流量(KB)"],
            data.get("url_pv") or [],
            ["uri", "pv", "访问成功率(%)", "平均延迟(ms)", "入流量(KB)"],
            {"uri"},
        )}
      </div>
      <div class="card" style="grid-column:span 9">
        <h3>URL 按照平均延迟进行排序</h3>
        {render_table(
            ["uri", "PV", "访问成功率(%)", "平均延迟(ms)", "入流量(KB)"],
            data.get("url_rt") or [],
            ["uri", "pv", "访问成功率(%)", "平均延迟(ms)", "入流量(KB)"],
            {"uri"},
        )}
      </div>
    </div>

    <div class="grid">
      <div class="card" style="grid-column:span 8">
        <h3>Upstream 按照 PV 维度进行排序</h3>
        {render_table(
            ["addr", "PV", "访问成功率(%)", "平均延迟(ms)", "入流量(KB)"],
            data.get("up_pv") or [],
            ["addr", "pv", "访问成功率(%)", "平均延迟(ms)", "入流量(KB)"],
            {"addr"},
        )}
      </div>
      <div class="card" style="grid-column:span 8">
        <h3>Upstream 按照延迟维度进行排序</h3>
        {render_table(
            ["addr", "PV", "访问成功率(%)", "平均延迟(ms)", "P90延迟(ms)", "P99延迟(ms)"],
            data.get("up_rt") or [],
            ["addr", "pv", "访问成功率(%)", "平均延迟(ms)", "P90延迟(ms)", "P99延迟(ms)"],
            {"addr"},
        )}
      </div>
      <div class="card" style="grid-column:span 8">
        <h3>Upstream 按照失败率维度进行排序</h3>
        {render_table(
            ["addr", "PV", "访问成功率(%)", "平均延迟(ms)", "P90延迟(ms)", "P99延迟(ms)"],
            data.get("up_fail") or [],
            ["addr", "pv", "访问成功率(%)", "平均延迟(ms)", "P90延迟(ms)", "P99延迟(ms)"],
            {"addr"},
        )}
      </div>
    </div>

  </div>
</div>

<script>
(function(){{
  function empty(id) {{
    var el = document.getElementById(id);
    if (!el) return;
    var box = el.parentNode;
    box.innerHTML = '<div class="no-data">暂无数据</div>';
  }}
  function pie(id, rows) {{
    if (!rows || !rows.length) {{ empty(id); return; }}
    new Chart(document.getElementById(id), {{
      type: 'doughnut',
      data: {{
        labels: rows.map(function(d){{ return d.name; }}),
        datasets: [{{ data: rows.map(function(d){{ return d.cnt; }}), backgroundColor: rows.map(function(d){{ return d.color; }}), borderWidth: 2, borderColor: '#fff' }}]
      }},
      options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'bottom', labels: {{ color: '#595959', padding: 10, font: {{ size: 11 }}, usePointStyle: true }} }} }} }}
    }});
  }}
  function line(id, payload, unit) {{
    if (!payload || !payload.labels || !payload.labels.length) {{ empty(id); return; }}
    var ds = [
      {{ label: '今日', data: payload.today, borderColor: '#2f54eb', backgroundColor: 'rgba(47,84,235,.12)', tension: .25, fill: false, pointRadius: 2 }}
    ];
    if (payload.yesterday && payload.yesterday.some(function(v){{ return v; }}))
      ds.push({{ label: '昨日', data: payload.yesterday, borderColor: '#fa8c16', backgroundColor: 'transparent', tension: .25, fill: false, pointRadius: 2 }});
    if (payload.week && payload.week.some(function(v){{ return v; }}))
      ds.push({{ label: '上周', data: payload.week, borderColor: '#52c41a', backgroundColor: 'transparent', tension: .25, fill: false, pointRadius: 2 }});
    new Chart(document.getElementById(id), {{
      type: 'line',
      data: {{ labels: payload.labels, datasets: ds }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ position: 'bottom', labels: {{ font: {{ size: 11 }} }} }} }},
        scales: {{
          x: {{ ticks: {{ color: '#8c8c8c', maxRotation: 45, font: {{ size: 9 }} }}, grid: {{ display: false }} }},
          y: {{ ticks: {{ color: '#8c8c8c', callback: function(v){{ return unit ? v + unit : v; }} }}, grid: {{ color: '#f0f0f0' }} }}
        }}
      }}
    }});
  }}
  function pct(id, payload) {{
    if (!payload || !payload.labels || !payload.labels.length) {{ empty(id); return; }}
    new Chart(document.getElementById(id), {{
      type: 'line',
      data: {{
        labels: payload.labels,
        datasets: [
          {{ label: 'P90', data: payload.p90, borderColor: '#13c2c2', tension: .25, fill: false, pointRadius: 2 }},
          {{ label: 'P95', data: payload.p95, borderColor: '#2f54eb', tension: .25, fill: false, pointRadius: 2 }},
          {{ label: 'P99', data: payload.p99, borderColor: '#f5222d', tension: .25, fill: false, pointRadius: 2 }}
        ]
      }},
      options: {{
        responsive: true, maintainAspectRatio: false,
        plugins: {{ legend: {{ position: 'bottom', labels: {{ font: {{ size: 11 }} }} }} }},
        scales: {{
          x: {{ ticks: {{ color: '#8c8c8c', maxRotation: 45, font: {{ size: 9 }} }}, grid: {{ display: false }} }},
          y: {{ ticks: {{ color: '#8c8c8c', callback: function(v){{ return v + 'ms'; }} }}, grid: {{ color: '#f0f0f0' }} }}
        }}
      }}
    }});
  }}
  pie('pieStatus', {js(pie_payload(data.get("status_pie") or []))});
  pie('pie4xx', {js(pie_payload(data.get("status_4xx") or []))});
  pie('pie5xx', {js(pie_payload(data.get("status_5xx") or []))});
  line('linePv', {js(series_compare(data.get("compare_pv") or [], from_ts=from_ts, to_ts=to_ts))}, '');
  line('lineRt', {js(series_compare(data.get("compare_rt") or [], 1000, from_ts, to_ts))}, 'ms');
  pct('linePct', {js(series_percentile(data.get("percentile") or [], from_ts, to_ts))});
}})();
</script>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_out, encoding="utf-8")
    print(f"HTML 已生成: {path}")
    return analysis, exceptions


def run_report(
    *,
    days: int = 0,
    date: str | None = None,
    output: Path | None = None,
) -> dict:
    from_ts, to_ts = get_time_range(days_ago=days, date=date)
    start = datetime.fromtimestamp(from_ts, CST).strftime("%Y-%m-%d %H:%M")
    end = datetime.fromtimestamp(to_ts, CST).strftime("%Y-%m-%d %H:%M")
    if output is None:
        output = default_output_path()
    elif not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    client = get_client()
    data = fetch_all(client, from_ts, to_ts)
    analysis, exceptions = generate_html(from_ts, to_ts, data, output)
    return {
        "output": output,
        "timestamp": output.stem,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "start": start,
        "end": end,
        "analysis": analysis,
        "exceptions": exceptions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="按前一天 17:00 到运行时刻拉取 ai4s.itic-sci.com 访问日志并生成仪表盘 HTML")
    parser.add_argument("--days", type=int, default=0, help="把运行时刻往前推几天")
    parser.add_argument("--date", help="指定结束日 YYYY-MM-DD，查询前一天 17:00 到该日 17:00")
    parser.add_argument("-o", "--output", help="输出 HTML 路径，默认 reports/时间戳.html")
    parser.add_argument("--dry-run", action="store_true", help="只打印时间范围，不查询")
    args = parser.parse_args()

    from_ts, to_ts = get_time_range(days_ago=args.days, date=args.date)
    start = datetime.fromtimestamp(from_ts, CST).strftime("%Y-%m-%d %H:%M")
    end = datetime.fromtimestamp(to_ts, CST).strftime("%Y-%m-%d %H:%M")
    print(f"时间: {start} → {end} (CST)")
    print(f"Project: {PROJECT}  Logstore: {LOGSTORE}")
    print(f"查询: {BASE_FILTER}")
    if args.dry_run:
        return

    output = Path(args.output) if args.output else None
    try:
        result = run_report(days=args.days, date=args.date, output=output)
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    analysis = result["analysis"]
    exceptions = result["exceptions"]
    if analysis["findings"]:
        print("分析结论:")
        for i, item in enumerate(analysis["findings"], 1):
            print(f"  [{item['level']}] {i}. {item['title']}")
            print(f"      {item['detail']}")
    if exceptions["items"]:
        print("异常分析:")
        for i, item in enumerate(exceptions["items"], 1):
            print(f"  [{item['level']}] {i}. {item['title']}")
            print(f"      {item['detail']}")


if __name__ == "__main__":
    main()
