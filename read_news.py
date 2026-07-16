"""
read_news.py — 台股開盤前 AI 新聞速報

本檔案是在使用者原本的桌面版腳本基礎上擴充而成，新聞抓取邏輯
（get_last_trading_close / get_news_text）與 AI 分析邏輯
（analyze_market / analyze_company）都沿用原本已經驗證過的版本，
新增的部分是：

  1. 追蹤清單與大盤主題移到 config.json，方便日後直接改設定檔
  2. 用 yfinance 抓取實際報價（加權指數、費半、美股三大指數等）
  3. 輸出 data.json，給網頁版晨報（index.html + app.js）讀取顯示
  4. API 金鑰改從環境變數 GEMINI_API_KEY 讀取，不再寫死在程式碼裡
  5. 在 GitHub Actions（CI）環境下執行時，會跳過互動輸入與
     webbrowser.open（CI 沒有畫面），但本機雙擊執行時行為不變，
     一樣會產生 HTML 報表並自動開啟瀏覽器

本機執行方式：
  設定環境變數 GEMINI_API_KEY 後直接執行，或執行時若偵測不到環境變數，
  會提示你手動輸入一次（只在本機互動情境下）。

GitHub Actions 排程執行方式：
  GEMINI_API_KEY 由 repo 的 Secrets 注入，詳見 README.md。
"""
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, time as dtime
from email.utils import parsedate_to_datetime
import math
import time
import json
import re
import os
import sys
import html
import webbrowser
import getpass

try:
    from google import genai
except ImportError:
    print("❌ 偵測到未安裝 AI 套件，請先執行：pip install google-genai")
    if sys.stdin.isatty():
        input("\n按下 Enter 鍵關閉...")
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    yf = None  # 報價功能為輔助功能，缺少套件時不影響新聞分析主流程

IS_CI = bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
DATA_JSON_PATH = os.path.join(SCRIPT_DIR, "data.json")

# ==========================================================
# ⚙️ 設定區
# ==========================================================


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg["companies"], cfg["market_topics"]


COMPANIES_CFG, MARKET_TOPICS = load_config()
COMPANIES = [c["name"] for c in COMPANIES_CFG]
COMPANY_SYMBOL_BY_NAME = {c["name"]: c["symbol"] for c in COMPANIES_CFG}


def resolve_api_key():
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    if not IS_CI and sys.stdin.isatty():
        print("⚠️ 未偵測到 GEMINI_API_KEY 環境變數。")
        return getpass.getpass("請貼上你的 Gemini API 金鑰（輸入時不會顯示）：").strip()
    return None


GEMINI_API_KEY = resolve_api_key()

# ==========================================================
# 📰 新聞抓取（沿用原始邏輯）
# ==========================================================


def get_last_trading_close(now=None, close_hour=13, close_minute=30):
    """計算「最近一個已經收盤的交易日」之收盤時間，只排除週六週日，
    不排除國定假日／颱風假等特殊休市日（遇到連假新聞區間會保守地變長）。"""
    if now is None:
        now = datetime.now()

    days_back = 0
    while True:
        candidate_date = (now - timedelta(days=days_back)).date()
        candidate_close = datetime.combine(candidate_date, dtime(close_hour, close_minute))
        is_weekday = candidate_date.weekday() < 5
        if is_weekday and candidate_close <= now:
            return candidate_close
        days_back += 1


def get_news_text(query_keyword, since_dt=None):
    """抓取「since_dt（通常是上一交易日收盤）到現在」這段時間內的新聞標題。"""
    now = datetime.now()
    if since_dt is None:
        since_dt = get_last_trading_close(now)

    hours_span = max(1, math.ceil((now - since_dt).total_seconds() / 3600))
    query = f"{query_keyword} when:{hours_span}h"
    encoded_query = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    window_desc = f"{since_dt.strftime('%m/%d %H:%M')}～{now.strftime('%m/%d %H:%M')}"

    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=20) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        items = root.findall('.//item')

        if not items:
            return f"{window_desc} 這段區間內暫無相關新聞。"

        news_list = []
        for item in items:
            title_el = item.find('title')
            pubdate_el = item.find('pubDate')
            if title_el is None or title_el.text is None:
                continue

            if pubdate_el is not None and pubdate_el.text:
                try:
                    pub_dt = parsedate_to_datetime(pubdate_el.text)
                    pub_dt_local = pub_dt.astimezone().replace(tzinfo=None) if pub_dt.tzinfo else pub_dt
                    if pub_dt_local < since_dt:
                        continue
                except Exception:
                    pass

            news_list.append(f"- {title_el.text}")
            if len(news_list) >= 10:
                break

        if not news_list:
            return f"{window_desc} 這段區間內暫無相關新聞。"
        return "\n".join(news_list)
    except Exception as e:
        return f"抓取新聞失敗: {e}"


# ==========================================================
# 💹 報價抓取（新增：供網頁版顯示數字用）
# ==========================================================

MARKET_TICKERS = [
    ("台股加權指數", "^TWII", "point"),
    ("費城半導體", "^SOX", "point"),
    ("NASDAQ", "^IXIC", "point"),
    ("S&P 500", "^GSPC", "point"),
    ("日經 225", "^N225", "point"),
    ("美元／台幣", "TWD=X", "fx"),
    ("台積電 ADR", "TSM", "price"),
    ("布蘭特原油", "BZ=F", "price"),
    ("美 10 年債", "^TNX", "yield"),
]


def fetch_quotes():
    quotes = {}
    if yf is None:
        print("[warn] 未安裝 yfinance，略過報價區塊", file=sys.stderr)
        return quotes
    for name, ticker, kind in MARKET_TICKERS:
        try:
            hist = yf.Ticker(ticker).history(period="5d", interval="1d")
            if hist.empty or len(hist) < 2:
                print(f"[warn] {name} ({ticker}) 資料不足", file=sys.stderr)
                continue
            last_close = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2])
            change = last_close - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0.0
            # 台股慣例：紅漲(positive) 綠跌(negative)。CSS 顏色已對應調整過。
            trend = "positive" if change > 0 else "negative" if change < 0 else "neutral-text"

            if kind == "yield":
                value_str, change_str = f"{last_close:.2f}%", f"{change:+.2f}"
            elif kind == "fx":
                value_str, change_str = f"{last_close:.2f}", f"{change_pct:+.2f}%"
            else:
                value_str, change_str = f"{last_close:,.2f}", f"{change_pct:+.2f}%"

            quotes[name] = {
                "value": value_str, "change": change_str, "trend": trend,
                "raw_close": last_close, "raw_change_pct": change_pct,
                "history": [float(x) for x in hist["Close"].tolist()],
            }
        except Exception as e:
            print(f"[warn] 抓取 {name} ({ticker}) 失敗：{e}", file=sys.stderr)
    return quotes


# ==========================================================
# 🤖 AI 分析（沿用原始邏輯，company 分析新增 direction 欄位）
# ==========================================================


def ask_gemini(prompt, max_retries=3, retry_delay=5):
    client = genai.Client(api_key=GEMINI_API_KEY)
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(model='gemini-3.5-flash', contents=prompt)
            return response.text
        except Exception as e:
            error_text = str(e)
            is_temporary = "503" in error_text or "UNAVAILABLE" in error_text
            if is_temporary and attempt < max_retries:
                print(f"  ⏳ Gemini 伺服器忙碌中，{retry_delay} 秒後進行第 {attempt + 1} 次重試...")
                time.sleep(retry_delay)
                continue
            raise


def parse_json_response(raw_text):
    if not raw_text:
        return None
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```json\s*|^```\s*|```$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def analyze_market(topic_name, news_content):
    if "暫無相關新聞" in news_content or "失敗" in news_content:
        print(f"  💡 {news_content}")
        return None
    if not GEMINI_API_KEY:
        print("  ❌ 錯誤：缺少 GEMINI_API_KEY！")
        return None

    prompt = f"""
    你是專業的總體經濟與台股策略分析師。以下是過去一段時間內關於【{topic_name}】的新聞標題。
    請仔細閱讀後，只回傳一個 JSON 物件，不要有任何其他文字、說明或 Markdown 符號。

    JSON 格式如下：
    {{
      "focus_points": ["焦點事件1", "焦點事件2", "焦點事件3"],
      "direction": "偏多 或 偏空 或 中性",
      "outlook": "1到2句話，說明對台股大盤短期走勢的看法",
      "suggestion": "2到3句話的具體觀察建議，須包含：(1) 近期需留意的關鍵事件或數據公布時間點 (2) 至少一個「若情境A發生→可考慮如何應對；若情境B發生→可考慮如何應對」的條件式情境說明 (3) 主要風險提醒。不要下達單一明確的買賣指令，最終判斷交由投資人自行決定"
    }}

    規則：
    1. focus_points 列出 2 到 4 個最關鍵的焦點事件，每點在 20 字以內。
    2. 過濾掉重複或與股市無關的雜訊。
    3. 使用台灣繁體中文。
    4. 絕對不要輸出 JSON 以外的任何文字。

    新聞標題列表：
    {news_content}
    """
    try:
        raw = ask_gemini(prompt)
        parsed = parse_json_response(raw)
        if parsed is None:
            print("  ⚠️ AI 回覆格式無法解析")
            return {"focus_points": [raw], "direction": "中性", "outlook": "-", "suggestion": "-"}
        for point in parsed.get("focus_points", []):
            print(f"  • {point}")
        print(f"  影響方向：{parsed.get('direction', '-')}")
        return parsed
    except Exception as e:
        print(f"  ❌ AI 統整失敗，錯誤原因: {e}")
        return None


def analyze_company(company_name, news_content):
    if "暫無相關新聞" in news_content or "失敗" in news_content:
        print(f"  💡 {news_content}")
        return None
    if not GEMINI_API_KEY:
        print("  ❌ 錯誤：缺少 GEMINI_API_KEY！")
        return None

    prompt = f"""
    你是專業的台股財經分析師。以下是過去一段時間內關於【{company_name}】的新聞標題。
    請仔細閱讀後，只回傳一個 JSON 物件，不要有任何其他文字、說明或 Markdown 符號。

    JSON 格式如下：
    {{
      "focus_points": ["焦點1", "焦點2", "焦點3"],
      "direction": "偏多 或 偏空 或 中性（根據新聞對這家公司股價的短期影響研判）",
      "outlook": "1到2句話，針對營收表現、重大合作、產業趨勢等，說明公司短期展望",
      "suggestion": "2到3句話的具體觀察建議，須包含：(1) 近期需留意的關鍵事件或數據公布時間點（如財報、法說會、月營收公布日） (2) 至少一個「若情境A發生→可考慮如何應對；若情境B發生→可考慮如何應對」的條件式情境說明 (3) 主要風險提醒。不要下達單一明確的買賣指令，最終判斷交由投資人自行決定"
    }}

    規則：
    1. focus_points 列出 2 到 3 個最關鍵的焦點，每點在 20 字以內。
    2. 過濾掉重複或無關的雜訊。
    3. 使用台灣繁體中文。
    4. 絕對不要輸出 JSON 以外的任何文字。

    新聞標題列表：
    {news_content}
    """
    try:
        raw = ask_gemini(prompt)
        parsed = parse_json_response(raw)
        if parsed is None:
            print("  ⚠️ AI 回覆格式無法解析")
            return {"focus_points": [raw], "direction": "中性", "outlook": "-", "suggestion": "-"}
        for point in parsed.get("focus_points", []):
            print(f"  • {point}")
        return parsed
    except Exception as e:
        print(f"  ❌ AI 統整失敗，錯誤原因: {e}")
        return None


# ==========================================================
# 📄 本機 HTML 報表（沿用原始邏輯，僅本機互動執行時使用）
# ==========================================================

DIRECTION_COLOR = {"偏多": "#d1242f", "偏空": "#1a7f37", "中性": "#6e7781"}  # 台股習慣：紅漲綠跌


def esc(text):
    return html.escape(str(text)) if text is not None else "-"


def build_market_rows(market_results):
    rows = []
    for topic_name, data in market_results:
        if not data:
            continue
        focus_html = "".join(f"<li>{esc(p)}</li>" for p in data.get("focus_points", []))
        direction = data.get("direction", "-")
        color = DIRECTION_COLOR.get(direction, "#6e7781")
        rows.append(f"""
        <tr>
          <td class="topic">{esc(topic_name)}</td>
          <td><ul>{focus_html}</ul></td>
          <td><span class="tag" style="background:{color}">{esc(direction)}</span></td>
          <td>{esc(data.get('outlook', '-'))}</td>
          <td>{esc(data.get('suggestion', '-'))}</td>
        </tr>""")
    return "\n".join(rows)


def build_company_rows(company_results):
    rows = []
    for company_name, data in company_results:
        if not data:
            continue
        focus_html = "".join(f"<li>{esc(p)}</li>" for p in data.get("focus_points", []))
        rows.append(f"""
        <tr>
          <td class="topic">{esc(company_name)}</td>
          <td><ul>{focus_html}</ul></td>
          <td>{esc(data.get('outlook', '-'))}</td>
          <td>{esc(data.get('suggestion', '-'))}</td>
        </tr>""")
    return "\n".join(rows)


def generate_html_report(current_time, market_results, company_results, since_dt=None):
    market_rows = build_market_rows(market_results)
    company_rows = build_company_rows(company_results)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<title>盤前台股 AI 新聞速報 - {esc(current_time)}</title>
<style>
  body {{ font-family: "Microsoft JhengHei", "PingFang TC", sans-serif; background:#f6f8fa; color:#1f2328; margin:0; padding:24px; }}
  h1 {{ font-size:20px; margin-bottom:4px; }}
  .timestamp {{ color:#6e7781; font-size:13px; margin-bottom:24px; }}
  h2 {{ font-size:16px; margin-top:32px; border-left:4px solid #0969da; padding-left:8px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,0.08); margin-top:8px; }}
  th, td {{ border:1px solid #d0d7de; padding:10px 12px; text-align:left; vertical-align:top; font-size:14px; }}
  th {{ background:#f0f3f6; font-weight:600; }}
  td.topic {{ font-weight:600; white-space:nowrap; }}
  ul {{ margin:0; padding-left:18px; }}
  li {{ margin-bottom:4px; }}
  .tag {{ display:inline-block; color:#fff; padding:2px 10px; border-radius:12px; font-size:12px; }}
  .disclaimer {{ margin-top:32px; padding:12px 16px; background:#fff8c5; border:1px solid #d4a72c; border-radius:6px; font-size:13px; color:#4d3800; }}
</style>
</head>
<body>
  <h1>🤖 盤前台股 AI 新聞大腦速報</h1>
  <div class="timestamp">彙整時間：{esc(current_time)}{f' ｜ 新聞擷取區間：{esc(since_dt.strftime("%Y-%m-%d %H:%M"))}（上一交易日收盤）～ 現在' if since_dt else ''}</div>

  <h2>📈 大盤焦點總覽（美股／台股）</h2>
  <table>
    <thead><tr><th style="width:110px;">焦點主題</th><th>焦點新聞</th><th style="width:90px;">影響方向</th><th>大盤展望</th><th>操作建議</th></tr></thead>
    <tbody>{market_rows if market_rows else '<tr><td colspan="5">今日無可用資料</td></tr>'}</tbody>
  </table>

  <h2>🏢 個股焦點</h2>
  <table>
    <thead><tr><th style="width:110px;">公司</th><th>焦點新聞</th><th>公司展望</th><th>操作建議</th></tr></thead>
    <tbody>{company_rows if company_rows else '<tr><td colspan="4">今日無可用資料</td></tr>'}</tbody>
  </table>

  <div class="disclaimer">
    ⚠️ 本報表內容由 AI 依據新聞標題自動彙整產生，僅供個人參考與輔助閱讀，不構成任何投資建議或買賣依據。
    新聞內容可能有誤、延遲或不完整，實際投資決策請自行查證並審慎評估風險。
  </div>
</body>
</html>
"""
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
    filepath = os.path.join(SCRIPT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
    return filepath


# ==========================================================
# 🌐 data.json 輸出（新增：供網頁版晨報使用）
# ==========================================================

TONE_MAP = {"偏多": "positive", "偏空": "negative", "中性": "neutral-text"}
HOLDING_TONE_MAP = {"偏多": "bull", "偏空": "bear", "中性": "watch"}
ARROW_MAP = {"偏多": "↑", "偏空": "↓", "中性": "→"}
WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def build_taiex_block(quotes):
    q = quotes.get("台股加權指數")
    if not q:
        return {"value": "－", "change": "－", "change_pct": "", "tone": "neutral-text", "chart_points": [50] * 8}
    history = q.get("history") or [q["raw_close"]] * 8
    return {
        "value": f"{q['raw_close']:,.0f}", "change": q["change"],
        "change_pct": f"{q['raw_change_pct']:+.2f}%", "tone": q["trend"], "chart_points": history,
    }


def build_markets_block(quotes):
    order = ["費城半導體", "NASDAQ", "S&P 500", "日經 225", "美元／台幣", "台積電 ADR", "布蘭特原油", "美 10 年債"]
    return [[name, quotes[name]["value"], quotes[name]["change"], quotes[name]["trend"]]
            for name in order if name in quotes]


def build_data_json(market_results, company_results, quotes, since_dt):
    valid_market = [(name, d) for name, d in market_results if d]

    signal_row = [
        {"label": name, "text": d.get("direction", "中性"),
         "arrow": ARROW_MAP.get(d.get("direction"), "→"),
         "tone": TONE_MAP.get(d.get("direction"), "neutral-text")}
        for name, d in valid_market
    ]

    overall_direction = valid_market[-1][1].get("direction", "中性") if valid_market else "中性"
    # 用「台股焦點」的展望當主摘要（若存在），否則退而求其次用第一個有效主題
    taiwan_topic = next((d for name, d in valid_market if "台股" in name), None)
    market_summary = (taiwan_topic or (valid_market[0][1] if valid_market else {})).get(
        "outlook", "今日尚無足夠新聞可供摘要，請留意開盤後市場實際反應。"
    )

    news_entries = []
    for name, d in valid_market:
        tone = TONE_MAP.get(d.get("direction"), "neutral-text")
        for point in d.get("focus_points", [])[:2]:
            news_entries.append([point, d.get("outlook", ""), d.get("direction", "中性"), tone, name])
    news_entries = news_entries[:4]

    watchlist_holdings = []
    for name, d in company_results:
        if not d:
            continue
        symbol = COMPANY_SYMBOL_BY_NAME.get(name, "")
        watchlist_holdings.append({
            "symbol": symbol, "name": name,
            "signal": d.get("direction", "中性"),
            "reason": d.get("outlook", "-"),
            "tone": HOLDING_TONE_MAP.get(d.get("direction"), "watch"),
        })

    now = datetime.now().astimezone()
    return {
        "generated_at": now.isoformat(),
        "report_date_text": now.strftime("%Y 年 %m 月 %d 日") + "，" + WEEKDAYS[now.weekday()],
        "news_window": since_dt.strftime("%m/%d %H:%M") if since_dt else "",
        "market_tone": overall_direction,
        "market_tone_class": TONE_MAP.get(overall_direction, "neutral-text"),
        "market_summary": market_summary,
        "signal_row": signal_row,
        "taiex": build_taiex_block(quotes),
        "markets": build_markets_block(quotes),
        "news": news_entries,
        "sectors": [],
        "watchlist_holdings": watchlist_holdings,
    }


# ==========================================================
# 🚀 主流程
# ==========================================================

if __name__ == "__main__":
    now = datetime.now()
    current_time = now.strftime('%Y-%m-%d %H:%M')
    since_dt = get_last_trading_close(now)
    print("=" * 60)
    print(f" 🤖 盤前台股 AI 新聞大腦速報 (彙整時間: {current_time})")
    print(f" 📅 新聞擷取區間：{since_dt.strftime('%Y-%m-%d %H:%M')}（上一交易日收盤）～ 現在")
    print("=" * 60)

    if not GEMINI_API_KEY:
        print("❌ 缺少 GEMINI_API_KEY，無法呼叫 AI 分析，程式結束。")
        sys.exit(1)

    market_results = []
    company_results = []

    print("\n📈 大盤焦點總覽")
    print("-" * 60)
    for query_keyword, topic_name in MARKET_TOPICS.items():
        print(f"\n🔍 正在分析 【{topic_name}】 的最新動態...")
        market_news = get_news_text(query_keyword, since_dt)
        result = analyze_market(topic_name, market_news)
        market_results.append((topic_name, result))
        print("-" * 60)

    print("\n🏢 個股焦點")
    print("-" * 60)
    for company in COMPANIES:
        print(f"\n🔍 正在分析 【{company}】 的最新動態...")
        news_text = get_news_text(company, since_dt)
        result = analyze_company(company, news_text)
        company_results.append((company, result))
        print("-" * 60)

    print("\n💹 抓取市場報價...")
    quotes = fetch_quotes()

    # 輸出 data.json，給網頁版晨報使用（本機與 CI 都會產生）
    data_output = build_data_json(market_results, company_results, quotes, since_dt)
    with open(DATA_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data_output, f, ensure_ascii=False, indent=2)
    print(f"\n📊 data.json 已產出：{DATA_JSON_PATH}")

    # 本機互動執行時，維持原本「產生 HTML 報表並自動開啟瀏覽器」的體驗
    if not IS_CI:
        try:
            report_path = generate_html_report(current_time, market_results, company_results, since_dt)
            print(f"📄 表格報表已產出：{report_path}")
            if sys.stdin.isatty():
                webbrowser.open(f"file://{report_path}")
        except Exception as e:
            print(f"⚠️ 報表產生或開啟失敗：{e}")

        if sys.stdin.isatty():
            input("\n👉 閱讀完畢，按下 Enter 鍵即可關閉視窗...")
