# 全球市場早報 安裝說明

每個工作天早上自動產生一份 HTML 報告，內容包含：亞洲／美國／歐洲股市、主要匯率、原油、黃金、白銀、銅、美債殖利率，以及過去 24 小時的重點新聞標題。

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `daily_market_brief.py` | 主程式（最上方「設定區」可增減項目） |
| `requirements.txt` | 需要安裝的套件清單 |
| `run_brief.bat` | Windows 排程用的啟動檔 |
| `run_brief.sh` | Linux 排程用的啟動檔 |
| `reports/` | 執行後自動產生，`index.html` 永遠是最新一份 |
| `brief.log` | 執行紀錄，有問題先看這裡 |

---

## 一、主機是 Windows（例如公司內部伺服器）

### 1. 確認已安裝 Python
開啟「命令提示字元」（開始選單搜尋 `cmd`），輸入：
```
python --version
```
顯示 `Python 3.9` 以上即可。若顯示找不到指令，請到 https://www.python.org/downloads/ 下載安裝，**安裝第一個畫面務必勾選「Add python.exe to PATH」**。

### 2. 放置程式
把整個資料夾放到例如 `C:\market-brief\`。

### 3. 建立虛擬環境並安裝套件
在命令提示字元依序輸入（每行按 Enter，等它跑完再輸入下一行）：
```
cd C:\market-brief
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 4. 手動試跑一次
```
run_brief.bat
```
約 1～2 分鐘後看到「完成」字樣，打開 `C:\market-brief\reports\index.html` 確認內容。

### 5. 設定每個工作天自動執行
1. 開始選單搜尋「工作排程器」並開啟
2. 右側點「建立基本工作」
3. 名稱：`全球市場早報` → 下一步
4. 觸發程序選「每週」→ 時間設 **07:30**，勾選 **星期一～星期五** → 下一步
5. 動作選「啟動程式」→ 程式或指令碼選 `C:\market-brief\run_brief.bat`；「開始位置」填 `C:\market-brief` → 完成
6. 在工作清單中對這個工作按右鍵 →「內容」→ 勾選 **「不論使用者登入與否均執行」**（伺服器沒人登入也會跑）→ 確定，輸入該帳號密碼

---

## 二、主機是 Linux（例如雲端 VM）

```bash
# 1. 放置程式（以 /opt/market-brief 為例）
sudo mkdir -p /opt/market-brief && sudo chown $USER /opt/market-brief
# 把檔案上傳到這個資料夾後：
cd /opt/market-brief

# 2. 建立虛擬環境並安裝套件
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 3. 手動試跑
./run_brief.sh

# 4. 設定排程
crontab -e
```
在打開的編輯畫面最下方加入兩行（雲端主機時區常是 UTC，第一行讓排程用台北時間）：
```
CRON_TZ=Asia/Taipei
30 7 * * 1-5 /opt/market-brief/run_brief.sh
```
存檔離開即可。

---

## 三、怎麼在自己的電腦看報告

報告產生在主機上，二選一：

**做法 A：共用資料夾（Windows 主機最簡單）**
把 `reports` 資料夾設為網路共用，在自己電腦把 `\\主機名稱\reports\index.html` 加入書籤。

**做法 B：開一個小網頁伺服器（內網用）**
在主機上執行：
```
venv\Scripts\python.exe -m http.server 8080 --directory reports      (Windows)
./venv/bin/python -m http.server 8080 --directory reports            (Linux)
```
之後在自己電腦瀏覽器開 `http://主機IP:8080/`。要開機自動啟動的話，可以同樣用工作排程器（觸發程序選「電腦啟動時」）或 Linux 的 systemd。
⚠️ 這個伺服器沒有密碼保護，請只在公司內網使用，不要對外開放 8080 埠。

---

## 四、常見調整

- **增減商品**：編輯 `daily_market_brief.py` 最上方 `MARKETS`，代號可到 https://finance.yahoo.com 搜尋（例如台積電是 `2330.TW`）。
- **改新聞關鍵字**：編輯 `NEWS_FEEDS`，`OR` 代表任一關鍵字符合。
- **漲跌顏色**：`UP_IS_RED = True` 為台灣習慣漲紅跌綠。
- **執行時間建議 07:00～08:30**：此時美股已收盤、亞股尚未開盤，抓到的都是完整收盤價。若在亞股盤中執行，亞洲指數會顯示盤中即時價。

## 五、疑難排解

- **某項目顯示「無資料」**：偶發性網路問題，程式已自動重試 3 次；若每天都失敗，可能是 Yahoo 改了代號，查 `brief.log`。
- **全部無資料**：主機可能無法連外網，或公司防火牆擋了 `finance.yahoo.com`、`query1.finance.yahoo.com`、`query2.finance.yahoo.com`、`news.google.com`，請 IT 開放。
- **yfinance 突然失效**：Yahoo 偶爾改版，執行 `venv\Scripts\python.exe -m pip install -U yfinance` 更新套件通常就能解決。
