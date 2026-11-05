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
import json
import os
import logging
import sys
import time
import urllib.parse
import urllib.request
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
PAGE_MAX_WIDTH = 1760     # 頁面最大寬度（像素）；設 0 = 滿版，大螢幕會撐滿整個視窗
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
        ("^BSESN", "印度 SENSEX", 2),
        ("^AXJO", "澳洲 ASX 200", 2),
    ],
    "美國股市": [
        ("^DJI", "道瓊工業", 2),
        ("^GSPC", "S&P 500", 2),
        ("^IXIC", "那斯達克", 2),
        ("^SOX", "費城半導體", 2),
        ("^VIX", "VIX 恐慌指數", 2),
    ],
    "美股重點個股": [
        ("TSM", "台積電 ADR", 2),
        ("NVDA", "輝達", 2),
        ("AAPL", "蘋果", 2),
        ("MSFT", "微軟", 2),
        ("GOOGL", "Alphabet", 2),
        ("AMZN", "亞馬遜", 2),
        ("META", "Meta", 2),
        ("TSLA", "特斯拉", 2),
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
    "能源與金屬": [
        ("CL=F", "WTI 原油（美元／桶）", 2),
        ("BZ=F", "布蘭特原油（美元／桶）", 2),
        ("NG=F", "天然氣（美元／百萬英熱）", 3),
        ("GC=F", "黃金（美元／盎司）", 2),
        ("SI=F", "白銀（美元／盎司）", 3),
        ("HG=F", "銅（美元／磅）", 4),
    ],
    "美國公債殖利率": [
        ("^IRX", "13 週國庫券（%）", 3),
        ("^FVX", "5 年期（%）", 3),
        ("^TNX", "10 年期（%）", 3),
        ("^TYX", "30 年期（%）", 3),
    ],
    "加密貨幣": [
        ("BTC-USD", "比特幣（美元）", 0),
        ("ETH-USD", "以太幣（美元）", 2),
    ],
}

# 財經行事曆：只列重要性「高」的數據，地區代碼 → 中文
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CALENDAR_COUNTRIES = {"USD": "美國", "CNY": "中國", "JPY": "日本", "EUR": "歐元區", "GBP": "英國"}
CALENDAR_ZH = {
    "Non-Farm Employment Change": "非農就業人數",
    "Unemployment Rate": "失業率",
    "CPI m/m": "CPI 月增率",
    "CPI y/y": "CPI 年增率",
    "Core CPI m/m": "核心 CPI 月增率",
    "Core PCE Price Index m/m": "核心 PCE 物價月增率",
    "PPI m/m": "PPI 月增率",
    "Core PPI m/m": "核心 PPI 月增率",
    "Retail Sales m/m": "零售銷售月增率",
    "Core Retail Sales m/m": "核心零售銷售月增率",
    "Federal Funds Rate": "聯準會利率決議",
    "FOMC Statement": "FOMC 聲明",
    "FOMC Press Conference": "FOMC 記者會",
    "FOMC Meeting Minutes": "FOMC 會議紀要",
    "Advance GDP q/q": "GDP 季增率（初值）",
    "Prelim GDP q/q": "GDP 季增率（修正值）",
    "Final GDP q/q": "GDP 季增率（終值）",
    "ISM Manufacturing PMI": "ISM 製造業 PMI",
    "ISM Services PMI": "ISM 服務業 PMI",
    "Unemployment Claims": "初領失業救濟金人數",
    "JOLTS Job Openings": "JOLTS 職位空缺",
    "ADP Non-Farm Employment Change": "ADP 就業人數",
    "Average Hourly Earnings m/m": "平均時薪月增率",
    "Main Refinancing Rate": "歐洲央行利率決議",
    "Monetary Policy Statement": "貨幣政策聲明",
    "BOJ Policy Rate": "日本央行利率決議",
    "Official Bank Rate": "英國央行利率決議",
    "Manufacturing PMI": "製造業 PMI",
    "Caixin Manufacturing PMI": "財新製造業 PMI",
    "Trade Balance": "貿易收支",
}

# 台股籌碼（證交所公開資料）
TWSE_INST_URL = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate={d}&response=json"
TWSE_MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={d}&selectType=MS&response=json"

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
    ("半導體與 AI", google_news("半導體 OR 台積電 OR 輝達 OR AI伺服器")),
    ("電力與能源", google_news("台電 OR 電網 OR 重電 OR 儲能 OR 再生能源 OR 電價")),
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


# ---------------- 台股籌碼與財經行事曆 ----------------

def http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (market-brief)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def to_num(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def recent_weekdays(now, days=10):
    """由近到遠列出最近的平日（早報時當天還沒收盤，會自動往前找到有資料的那天）"""
    for back in range(days):
        d = (now - dt.timedelta(days=back)).date()
        if d.weekday() < 5:
            yield d


def iter_rows(obj):
    """在證交所回傳的 JSON 裡找出所有表格列（不同年份格式略有差異，用搜尋的比較保險）"""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from iter_rows(v)
    elif isinstance(obj, list):
        if obj and all(isinstance(r, list) for r in obj):
            for r in obj:
                if r and isinstance(r[0], str):
                    yield r
        else:
            for v in obj:
                yield from iter_rows(v)


def fetch_institutional(now):
    """三大法人買賣金額（元），回傳 {'date', 'rows': [(名稱, 買進, 賣出, 買賣超)]}"""
    for d in recent_weekdays(now):
        try:
            data = http_json(TWSE_INST_URL.format(d=d.strftime("%Y%m%d")))
            if data.get("stat") == "OK" and data.get("data"):
                rows = []
                for r in data["data"]:
                    nums = [to_num(x) for x in r[1:4]]
                    if None not in nums:
                        rows.append((r[0].strip(), *nums))
                if rows:
                    log.info("三大法人：取得 %s 資料", d)
                    return {"date": d, "rows": rows}
        except Exception as exc:
            log.warning("三大法人 %s 抓取失敗：%s", d, exc)
        time.sleep(2)  # 證交所有頻率限制
    log.error("三大法人資料無法取得")
    return None


def fetch_margin(now):
    """融資融券餘額，回傳 {'date', 'fin_amt': (前日, 今日) 仟元, 'short': (前日, 今日) 張}"""
    for d in recent_weekdays(now):
        try:
            data = http_json(TWSE_MARGIN_URL.format(d=d.strftime("%Y%m%d")))
            if data.get("stat") == "OK":
                result = {"date": d}
                for r in iter_rows(data):
                    label = r[0].strip()
                    if len(r) >= 6:
                        prev, today = to_num(r[-2]), to_num(r[-1])
                        if prev is None or today is None:
                            continue
                        if label.startswith("融資金額"):
                            result["fin_amt"] = (prev, today)
                        elif label.startswith("融券") and "交易單位" in label:
                            result["short"] = (prev, today)
                if "fin_amt" in result or "short" in result:
                    log.info("融資融券：取得 %s 資料", d)
                    return result
        except Exception as exc:
            log.warning("融資融券 %s 抓取失敗：%s", d, exc)
        time.sleep(2)
    log.error("融資融券資料無法取得")
    return None


def fetch_calendar(now):
    """本週重要經濟數據（只取重要性高、主要經濟體），已轉成台北時間"""
    try:
        data = http_json(CALENDAR_URL)
    except Exception as exc:
        log.warning("財經行事曆抓取失敗：%s", exc)
        return None
    events = []
    start = now - dt.timedelta(hours=12)  # 前一晚剛公布的也保留
    for e in data:
        if e.get("impact") != "High" or e.get("country") not in CALENDAR_COUNTRIES:
            continue
        try:
            when = dt.datetime.fromisoformat(e["date"]).astimezone(TZ)
        except (KeyError, ValueError):
            continue
        if when < start:
            continue
        title = e.get("title", "")
        zh = CALENDAR_ZH.get(title)
        events.append({
            "when": when,
            "country": CALENDAR_COUNTRIES[e["country"]],
            "title": f"{zh}（{title}）" if zh else title,
            "forecast": e.get("forecast") or "—",
            "previous": e.get("previous") or "—",
        })
    events.sort(key=lambda x: x["when"])
    log.info("財經行事曆：%d 筆", len(events))
    return events


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
            f'<th class="num">幅度</th><th class="trend">近一月走勢</th><th class="date">資料日</th></tr></thead>'
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


def dir_of(value):
    if not value:
        return "flat"
    return "up" if value > 0 else "down"


def render_chips(inst, margin):
    """台股籌碼：三大法人買賣超（億元）＋融資融券餘額"""
    out = []
    if inst:
        rows = "".join(
            f'<tr class="{dir_of(net)}"><th scope="row">{html.escape(name)}</th>'
            f'<td class="num">{fmt(buy / 1e8, 2)}</td><td class="num">{fmt(sell / 1e8, 2)}</td>'
            f'<td class="num chg">{fmt(net / 1e8, 2, True)}</td></tr>'
            for name, buy, sell, net in inst["rows"])
        body = (f'<div class="scroll"><table><thead><tr><th>法人</th><th class="num">買進</th>'
                f'<th class="num">賣出</th><th class="num">買賣超</th></tr></thead><tbody>{rows}</tbody></table></div>'
                f'<p class="note">單位：億元，資料日 {inst["date"].strftime("%m/%d")}（上市）</p>')
    else:
        body = '<p class="na">今天無法取得三大法人資料。</p>'
    out.append(f'<section class="group"><h2>三大法人買賣超</h2>{body}</section>')

    if margin and ("fin_amt" in margin or "short" in margin):
        rows = []
        if "fin_amt" in margin:
            prev, today = margin["fin_amt"]
            chg = (today - prev) / 1e5
            rows.append(f'<tr class="{dir_of(chg)}"><th scope="row">融資餘額（億元）</th>'
                        f'<td class="num">{fmt(today / 1e5, 2)}</td><td class="num chg">{fmt(chg, 2, True)}</td></tr>')
        if "short" in margin:
            prev, today = margin["short"]
            chg = today - prev
            rows.append(f'<tr class="{dir_of(chg)}"><th scope="row">融券餘額（張）</th>'
                        f'<td class="num">{fmt(today, 0)}</td><td class="num chg">{fmt(chg, 0, True)}</td></tr>')
        body = (f'<div class="scroll"><table><thead><tr><th>項目</th><th class="num">餘額</th>'
                f'<th class="num">增減</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
                f'<p class="note">資料日 {margin["date"].strftime("%m/%d")}（上市）</p>')
    else:
        body = '<p class="na">今天無法取得融資融券資料。</p>'
    out.append(f'<section class="group"><h2>融資融券</h2>{body}</section>')
    return "\n".join(out)


def render_calendar(events, now):
    if events is None:
        body = '<p class="na">今天無法取得財經行事曆。</p>'
    elif not events:
        body = '<p class="na">本週接下來沒有重要經濟數據公布。</p>'
    else:
        rows = []
        for e in events:
            w = e["when"]
            is_today = w.date() == now.date()
            day = "今天" if is_today else f'{w.month}/{w.day}（{"一二三四五六日"[w.weekday()]}）'
            rows.append(
                f'<tr class="{"today" if is_today else ""}"><td class="date">{day} {w.strftime("%H:%M")}</td>'
                f'<td>{e["country"]}</td><th scope="row">{html.escape(e["title"])}</th>'
                f'<td class="num">{html.escape(e["forecast"])}</td><td class="num">{html.escape(e["previous"])}</td></tr>')
        body = (f'<div class="scroll"><table class="cal"><thead><tr><th>台北時間</th><th>地區</th><th>項目</th>'
                f'<th class="num">預測</th><th class="num">前值</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    return (f'<section class="calendar"><h2>本週重要經濟數據</h2>{body}'
            f'<p class="note">只列重要性高的項目；資料來源 Forex Factory，時間可能調整。</p></section>')


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
.wrap{max-width:%(maxw)s;margin:0 auto;padding:28px clamp(16px,3vw,40px) 60px}
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
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(520px,100%%),1fr));gap:28px 24px}
@media (max-width:560px){.grid{grid-template-columns:1fr}}
h2{font-size:1.1rem;color:var(--navy);margin:0 0 6px;padding-bottom:4px;border-bottom:2px solid var(--navy)}
.scroll{overflow-x:auto}
table{width:100%%;border-collapse:collapse;font-size:.92rem}
thead th{font-weight:500;color:var(--muted);font-size:.8rem;text-align:left;padding:4px 6px}
tbody th{font-weight:500;text-align:left;padding:7px 6px;min-width:6.5em}
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
.chips{margin-bottom:28px}
.grid>*,.news-cols>*{min-width:0}
.news-cols{grid-template-columns:repeat(auto-fit,minmax(min(320px,100%%),1fr))}
.note{margin:6px 0 0;font-size:.78rem;color:var(--muted)}
.calendar{margin-top:44px}
.cal tbody th{white-space:normal;font-weight:500}
@media (max-width:600px){
.wrap{padding-top:20px}
header h1{font-size:1.35rem}
.board{grid-template-columns:repeat(2,1fr);margin:16px 0 26px}
.hl{padding:12px 14px}
.hl-val{font-size:1.3rem}
.hl-chg{font-size:.85rem}
table{font-size:.82rem}
td,tbody th{padding:6px 3px}
.cal td{white-space:normal}
thead th{padding:4px}
.date:not(.cal .date){display:none}
.trend{width:50px}
.spark{width:48px}
}
.cal td{white-space:nowrap}
tr.today td,tr.today th{background:color-mix(in srgb,var(--navy) 10%%,transparent)}
footer{margin-top:44px;font-size:.82rem;color:var(--muted);border-top:1px solid var(--rule);padding-top:12px}
footer a{color:var(--navy)}
"""


def build_html(quotes, news, now, today_name, inst=None, margin=None, events=None):
    up, down = ("#c62828", "#1e7d46") if UP_IS_RED else ("#1e7d46", "#c62828")
    up_d, down_d = ("#ff6b6b", "#4cc27a") if UP_IS_RED else ("#4cc27a", "#ff6b6b")
    maxw = f"{PAGE_MAX_WIDTH}px" if PAGE_MAX_WIDTH > 0 else "none"
    css = CSS % {"up": up, "down": down, "up_d": up_d, "down_d": down_d, "maxw": maxw}
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
<div class="grid chips">{render_chips(inst, margin)}</div>
<div class="grid">{render_tables(quotes)}</div>
{render_calendar(events, now)}
<section class="news"><h2>重點新聞（過去 24 小時）</h2><div class="news-cols">{render_news(news)}</div></section>
<footer>過去報告：{render_archive(today_name)}<br>
資料來源：Yahoo Finance（行情，可能有延遲）、臺灣證券交易所（三大法人、融資融券）、Forex Factory（經濟數據）、Google 新聞（標題）。本報告僅供參考，不構成投資建議。</footer>
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
    inst = fetch_institutional(now)
    margin = fetch_margin(now)
    events = fetch_calendar(now)
    today_name = f"{now.date().isoformat()}.html"
    page = build_html(quotes, news, now, today_name, inst, margin, events)
    (OUTPUT_DIR / today_name).write_text(page, encoding="utf-8")
    (OUTPUT_DIR / "index.html").write_text(page, encoding="utf-8")
    cleanup_old_reports(now)
    log.info("完成：%s", OUTPUT_DIR / today_name)
    if not any(quotes.values()):
        log.error("所有行情都抓取失敗，請檢查主機能否連上 Yahoo Finance")
        sys.exit(1)


if __name__ == "__main__":
    main()
