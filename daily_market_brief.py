# -*- coding: utf-8 -*-
"""
全球市場早報產生器
每次執行會抓取全球股市、匯率、原油、金屬價格與重點新聞標題，
輸出成 reports/ 資料夾內的 HTML 報告：
  - reports/2026-11-05.html  （當日存檔）
  - reports/index.html       （永遠是最新一份，書籤存這個就好）
"""

import datetime as dt
import html
import os
import logging
import sys
import time
import urllib.parse
from pathlib import Path
from zoneinfo import ZoneInfo

import feedparser
import yfinance as yf

# ============================================================
# 設定區：要增減項目，改這裡就好
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
# 輸出資料夾：本機預設 reports；GitHub 版由排程設定檔指定為 docs
OUTPUT_DIR = Path(os.environ.get("BRIEF_OUTPUT_DIR", BASE_DIR / "reports"))
LOG_FILE = BASE_DIR / "brief.log"
TZ = ZoneInfo("Asia/Taipei")
KEEP_DAYS = 90            # 報告保留天數，超過自動刪除
UP_IS_RED = True          # 台灣習慣：漲紅跌綠。改 False 變成國際慣例漲綠跌紅
NEWS_PER_SECTION = 6      # 每類新聞顯示幾則

# (Yahoo Finance 代號, 顯示名稱, 小數位數)
MARKETS = {
    "亞洲股市": [
        ("^TWII", "台灣加權指數", 2),
        ("^N225", "日經 225", 2),
        ("^KS11", "韓國 KOSPI", 2),
        ("^HSI", "香港恒生", 2),
        ("000001.SS", "上證綜合", 2),
    ],
    "美國股市": [
        ("^DJI", "道瓊工業", 2),
        ("^GSPC", "S&P 500", 2),
        ("^IXIC", "那斯達克", 2),
        ("^SOX", "費城半導體", 2),
        ("^VIX", "VIX 恐慌指數", 2),
    ],
    "歐洲股市": [
        ("^FTSE", "英國富時 100", 2),
        ("^GDAXI", "德國 DAX", 2),
        ("^FCHI", "法國 CAC 40", 2),
        ("^STOXX50E", "歐洲斯托克 50", 2),
    ],
    "匯率": [
        ("TWD=X", "美元／新台幣", 3),
        ("JPY=X", "美元／日圓", 2),
        ("CNY=X", "美元／人民幣", 4),
        ("KRW=X", "美元／韓元", 2),
        ("EURUSD=X", "歐元／美元", 4),
        ("DX-Y.NYB", "美元指數", 2),
    ],
    "原油與金屬": [
        ("CL=F", "WTI 原油（美元／桶）", 2),
        ("BZ=F", "布蘭特原油（美元／桶）", 2),
        ("GC=F", "黃金（美元／盎司）", 2),
        ("SI=F", "白銀（美元／盎司）", 3),
        ("HG=F", "銅（美元／磅）", 4),
    ],
    "債券殖利率": [
        ("^TNX", "美國 10 年期公債（%）", 3),
    ],
}

# 報告最上方大字顯示的重點項目
HEADLINE_SYMBOLS = ["^TWII", "^GSPC", "^SOX", "TWD=X", "CL=F", "GC=F"]


def google_news(query, lang="zh"):
    """組出 Google 新聞 RSS 網址（只取最近 24 小時）"""
    q = urllib.parse.quote(f"{query} when:1d")
    if lang == "zh":
        return f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


# (分類名稱, RSS 網址)
NEWS_FEEDS = [
    ("台股與總經", google_news("台股 OR 加權指數 OR 央行 OR 外資")),
    ("國際股市", google_news("美股 OR 華爾街 OR 日股 OR 歐股")),
    ("匯率", google_news("新台幣 OR 美元 OR 日圓 匯率")),
    ("原油與黃金", google_news("油價 OR 原油 OR 金價 OR 黃金")),
    ("Global markets (English)", google_news("stock market OR Federal Reserve OR oil prices", "en")),
]

# ============================================================
# 以下為程式本體，一般不需要修改
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("brief")


def fetch_quote(symbol):
    """抓單一商品近一個月日收盤，回傳最新價、漲跌與走勢資料；失敗回傳 None"""
    for attempt in range(1, 4):
        try:
            hist = yf.Ticker(symbol).history(period="1mo", interval="1d", auto_adjust=False)
            closes = hist["Close"].dropna()
            if len(closes) >= 2:
                last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
                return {
                    "last": last,
                    "change": last - prev,
                    "pct": (last - prev) / prev * 100 if prev else 0.0,
                    "date": closes.index[-1].strftime("%m/%d"),
                    "series": [float(v) for v in closes.tolist()],
                }
            log.warning("%s 資料筆數不足（第 %d 次）", symbol, attempt)
        except Exception as exc:  # 網路或資料源暫時錯誤
            log.warning("%s 抓取失敗（第 %d 次）：%s", symbol, attempt, exc)
        time.sleep(2 * attempt)
    log.error("%s 三次都失敗，報告中將標示為無資料", symbol)
    return None


def fetch_all_quotes():
    quotes = {}
    for items in MARKETS.values():
        for symbol, _name, _dec in items:
            quotes[symbol] = fetch_quote(symbol)
    ok = sum(1 for q in quotes.values() if q)
    log.info("行情抓取完成：%d / %d 成功", ok, len(quotes))
    return quotes


def fetch_news():
    sections, seen = [], set()
    for title, url in NEWS_FEEDS:
        items = []
        try:
            feed = feedparser.parse(url, agent="Mozilla/5.0 (market-brief)")
            for entry in feed.entries:
                headline = entry.get("title", "").strip()
                source = entry.get("source", {}).get("title", "")
                # Google 新聞標題尾端常帶「 - 來源」，拿掉避免重複
                if source and headline.endswith(f" - {source}"):
                    headline = headline[: -len(source) - 3]
                key = headline[:40]
                if not headline or key in seen:
                    continue
                seen.add(key)
                when = ""
                if entry.get("published_parsed"):
                    t = dt.datetime(*entry.published_parsed[:6], tzinfo=dt.timezone.utc).astimezone(TZ)
                    when = t.strftime("%m/%d %H:%M")
                items.append({"title": headline, "link": entry.get("link", "#"), "source": source, "when": when})
                if len(items) >= NEWS_PER_SECTION:
                    break
        except Exception as exc:
            log.warning("新聞來源「%s」失敗：%s", title, exc)
        log.info("新聞「%s」取得 %d 則", title, len(items))
        sections.append((title, items))
    return sections


# ---------------- HTML 產生 ----------------

def direction(q):
    if not q or q["change"] == 0:
        return "flat"
    return "up" if q["change"] > 0 else "down"


def fmt(value, dec, sign=False):
    text = f"{value:+,.{dec}f}" if sign else f"{value:,.{dec}f}"
    return text.replace("+", "▲").replace("-", "▼") if sign else text


def sparkline(series):
    if not series or len(series) < 2:
        return ""
    w, h, pad = 100, 30, 3
    lo, hi = min(series), max(series)
    rng = (hi - lo) or 1
    step = w / (len(series) - 1)
    pts = " ".join(f"{i * step:.1f},{h - pad - (v - lo) / rng * (h - 2 * pad):.1f}" for i, v in enumerate(series))
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline points="{pts}"/></svg>')


def name_of(symbol):
    for items in MARKETS.values():
        for s, n, d in items:
            if s == symbol:
                return n, d
    return symbol, 2


def render_headline(quotes):
    blocks = []
    for symbol in HEADLINE_SYMBOLS:
        q = quotes.get(symbol)
        name, dec = name_of(symbol)
        name = name.split("（")[0]
        if not q:
            blocks.append(f'<div class="hl flat"><div class="hl-name">{name}</div><div class="hl-val">—</div>'
                          f'<div class="hl-chg">無資料</div></div>')
            continue
        blocks.append(
            f'<div class="hl {direction(q)}"><div class="hl-name">{name}</div>'
            f'<div class="hl-val">{fmt(q["last"], dec)}</div>'
            f'<div class="hl-chg">{fmt(q["change"], dec, True)}　{fmt(q["pct"], 2, True)}%</div></div>')
    return "\n".join(blocks)


def render_tables(quotes):
    out = []
    for group, items in MARKETS.items():
        rows = []
        for symbol, name, dec in items:
            q = quotes.get(symbol)
            if not q:
                rows.append(f'<tr class="flat"><th scope="row">{name}</th><td colspan="5" class="na">無資料</td></tr>')
                continue
            rows.append(
                f'<tr class="{direction(q)}"><th scope="row">{name}</th>'
                f'<td class="num">{fmt(q["last"], dec)}</td>'
                f'<td class="num chg">{fmt(q["change"], dec, True)}</td>'
                f'<td class="num chg">{fmt(q["pct"], 2, True)}%</td>'
                f'<td class="trend">{sparkline(q["series"])}</td>'
                f'<td class="date">{q["date"]}</td></tr>')
        out.append(
            f'<section class="group"><h2>{group}</h2><div class="scroll"><table>'
            f'<thead><tr><th>項目</th><th class="num">收盤</th><th class="num">漲跌</th>'
            f'<th class="num">幅度</th><th>近一月走勢</th><th>資料日</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></section>')
    return "\n".join(out)


def render_news(sections):
    out = []
    for title, items in sections:
        if items:
            lis = "".join(
                f'<li><a href="{html.escape(i["link"])}" target="_blank" rel="noopener">{html.escape(i["title"])}</a>'
                f'<span class="meta">{html.escape(i["source"])}　{i["when"]}</span></li>' for i in items)
            body = f"<ul>{lis}</ul>"
        else:
            body = '<p class="na">這個來源今天沒有取得新聞，請查看 brief.log。</p>'
        out.append(f'<section class="news-sec"><h3>{html.escape(title)}</h3>{body}</section>')
    return "\n".join(out)


def render_archive(today_name):
    files = sorted(OUTPUT_DIR.glob("20??-??-??.html"), reverse=True)
    links = [f'<a href="{f.name}">{f.stem}</a>' for f in files if f.name != today_name][:15]
    return "　".join(links) if links else "尚無過去報告"


CSS = """
:root{--bg:#eef2f5;--panel:#ffffff;--ink:#17222d;--muted:#5d6b78;--rule:#d5dde4;
--navy:#1f3a5f;--up:%(up)s;--down:%(down)s;--flat:#6b7785;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#121a22;--panel:#18232e;--ink:#e6edf3;--muted:#93a1ae;
--rule:#2a3846;--navy:#8fb3dc;--up:%(up_d)s;--down:%(down_d)s;--flat:#8794a1;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:"Noto Sans TC","Microsoft JhengHei","PingFang TC",system-ui,sans-serif;
font-variant-numeric:tabular-nums;line-height:1.6}
.wrap{max-width:1100px;margin:0 auto;padding:28px 20px 60px}
header h1{font-size:1.9rem;margin:0;color:var(--navy);letter-spacing:.02em}
header p{margin:4px 0 0;color:var(--muted);font-size:.9rem}
.board{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1px;
background:var(--rule);border:1px solid var(--rule);margin:22px 0 34px}
.hl{background:var(--panel);padding:16px 18px}
.hl-name{font-size:.9rem;color:var(--muted)}
.hl-val{font-size:1.75rem;font-weight:700;line-height:1.25}
.hl-chg{font-size:.95rem;font-weight:600}
.up .hl-chg,.up .chg,.up .spark{color:var(--up)}
.down .hl-chg,.down .chg,.down .spark{color:var(--down)}
.flat .hl-chg,.flat .chg,.flat .spark{color:var(--flat)}
.up .hl-val{border-left:4px solid var(--up);padding-left:8px;margin-left:-12px}
.down .hl-val{border-left:4px solid var(--down);padding-left:8px;margin-left:-12px}
.flat .hl-val{border-left:4px solid var(--flat);padding-left:8px;margin-left:-12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:28px 32px}
@media (max-width:560px){.grid{grid-template-columns:1fr}}
h2{font-size:1.1rem;color:var(--navy);margin:0 0 6px;padding-bottom:4px;border-bottom:2px solid var(--navy)}
.scroll{overflow-x:auto}
table{width:100%%;border-collapse:collapse;font-size:.92rem}
thead th{font-weight:500;color:var(--muted);font-size:.8rem;text-align:left;padding:4px 6px}
tbody th{font-weight:500;text-align:left;padding:7px 6px;white-space:nowrap}
td{padding:7px 6px;border-top:1px solid var(--rule)}
tbody th{border-top:1px solid var(--rule)}
.num{text-align:right;white-space:nowrap}
td.num:first-of-type{font-weight:600}
.trend{width:110px}
.spark{width:100px;height:26px;display:block}
.spark polyline{fill:none;stroke:currentColor;stroke-width:1.6;vector-effect:non-scaling-stroke}
.date{color:var(--muted);font-size:.8rem;white-space:nowrap}
.na{color:var(--muted)}
.news{margin-top:44px}
.news>h2{margin-bottom:14px}
.news-cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px 32px}
h3{font-size:1rem;margin:0 0 6px;color:var(--ink)}
ul{list-style:none;margin:0;padding:0}
li{padding:7px 0;border-top:1px solid var(--rule)}
li a{color:var(--ink);text-decoration:none}
li a:hover,li a:focus-visible{color:var(--navy);text-decoration:underline}
.meta{display:block;font-size:.78rem;color:var(--muted)}
footer{margin-top:44px;font-size:.82rem;color:var(--muted);border-top:1px solid var(--rule);padding-top:12px}
footer a{color:var(--navy)}
"""


def build_html(quotes, news, now, today_name):
    up, down = ("#c62828", "#1e7d46") if UP_IS_RED else ("#1e7d46", "#c62828")
    up_d, down_d = ("#ff6b6b", "#4cc27a") if UP_IS_RED else ("#4cc27a", "#ff6b6b")
    css = CSS % {"up": up, "down": down, "up_d": up_d, "down_d": down_d}
    weekday = "一二三四五六日"[now.weekday()]
    title = f"{now.year}年{now.month}月{now.day}日（{weekday}）全球市場早報"
    return f"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;500;700&display=swap" rel="stylesheet">
<style>{css}</style></head>
<body><div class="wrap">
<header><h1>{title}</h1>
<p>產生時間 {now.strftime("%Y-%m-%d %H:%M")}（台北）　各市場以最近一個交易日收盤為準，休市市場請看「資料日」</p></header>
<div class="board">{render_headline(quotes)}</div>
<div class="grid">{render_tables(quotes)}</div>
<section class="news"><h2>重點新聞（過去 24 小時）</h2><div class="news-cols">{render_news(news)}</div></section>
<footer>過去報告：{render_archive(today_name)}<br>
資料來源：Yahoo Finance（行情，可能有延遲）、Google 新聞（標題）。本報告僅供參考，不構成投資建議。</footer>
</div></body></html>"""


def cleanup_old_reports(now):
    cutoff = (now - dt.timedelta(days=KEEP_DAYS)).date()
    for f in OUTPUT_DIR.glob("20??-??-??.html"):
        try:
            if dt.date.fromisoformat(f.stem) < cutoff:
                f.unlink()
                log.info("刪除舊報告 %s", f.name)
        except ValueError:
            pass


def main():
    now = dt.datetime.now(TZ)
    OUTPUT_DIR.mkdir(exist_ok=True)
    log.info("===== 開始產生 %s 早報 =====", now.date())
    quotes = fetch_all_quotes()
    news = fetch_news()
    today_name = f"{now.date().isoformat()}.html"
    page = build_html(quotes, news, now, today_name)
    (OUTPUT_DIR / today_name).write_text(page, encoding="utf-8")
    (OUTPUT_DIR / "index.html").write_text(page, encoding="utf-8")
    cleanup_old_reports(now)
    log.info("完成：%s", OUTPUT_DIR / today_name)
    if not any(quotes.values()):
        log.error("所有行情都抓取失敗，請檢查主機能否連上 Yahoo Finance")
        sys.exit(1)


if __name__ == "__main__":
    main()
