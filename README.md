# 台股開盤前晨報 — 自動化部署說明

這份文件說明如何把這個專案變成「每天早上打開網址就自動是最新資料」的網站，
不需要你手動執行任何東西，也不需要 Claude 或任何人「開啟」它。

運作原理：GitHub Actions 每天固定時間自動執行 `read_news.py`，抓新聞、
呼叫 Gemini 分析、抓報價，輸出 `data.json`，再自動部署到 GitHub Pages。
你每天早上打開網址時，看到的就已經是當天早上排程跑好的資料。

---

## 0. 先做這件事：更換 API 金鑰

你原本的 `read_news.py` 裡有一組寫死的 Gemini API 金鑰。這組金鑰已經出現在
上傳的檔案與對話紀錄中，等同於外洩，**請先去 [Google AI Studio](https://aistudio.google.com/apikey)
刪除舊金鑰、產生一把新的**，之後只會透過 GitHub Secrets 使用，不會再寫在程式碼裡。

---

## 1. 建立 GitHub Repository

1. 到 GitHub 建立一個新的 repository（Public 或 Private 皆可；若用免費方案的
   Private repo 跑 GitHub Pages 需確認方案支援，不確定的話建議先用 Public）
2. 把這個資料夾裡的所有檔案上傳 / push 上去，結構應該長這樣：

```
your-repo/
├── .github/workflows/daily-report.yml
├── index.html
├── styles.css
├── app.js
├── read_news.py
├── config.json
├── requirements.txt
└── .gitignore
```

## 2. 設定 API 金鑰（GitHub Secrets）

1. 進入 repo 的 **Settings → Secrets and variables → Actions**
2. 點 **New repository secret**
3. Name 填 `GEMINI_API_KEY`，Value 貼上你剛剛重新產生的金鑰
4. 儲存

## 3. 開啟 GitHub Pages

1. 進入 repo 的 **Settings → Pages**
2. Source 選擇 **GitHub Actions**（不是選 branch 那個選項）

## 4. 手動觸發第一次執行，確認一切正常

1. 進入 repo 的 **Actions** 分頁
2. 左側選 **Daily Pre-Market Report**
3. 點右側的 **Run workflow** 按鈕手動跑一次（不用等明天排程）
4. 等它跑完（大約 1~3 分鐘，視新聞與 AI 回應速度），確認：
   - 沒有紅色錯誤（若有，通常是金鑰沒設對，或 `config.json` 格式錯誤）
   - repo 裡多了一個 `data.json` 檔案（自動 commit 回來的）
5. 回到 **Settings → Pages**，會看到部署好的網址，例如：
   `https://你的帳號.github.io/repo名稱/`
6. 打開網址，確認畫面上方「示範資料」字樣變成「自動產出」，且持股表、新聞、
   報價都是今天的內容

## 5. 之後就不用管了

排程設定為週一到週五（台灣時間約早上 8 點，實際以 `daily-report.yml` 裡的
cron 為準）自動執行，之後你每天打開同一個網址，看到的就是當天早上更新過
的內容。收藏這個網址、或加到手機主畫面即可當作每天的晨報入口。

---

## 日常維護

### 增減追蹤的股票或大盤主題

直接編輯 `config.json`，不用動 `read_news.py`：

```json
{
  "companies": [
    { "symbol": "2887", "name": "台新金" }
  ],
  "market_topics": {
    "台股 大盤 加權指數": "台股焦點"
  }
}
```

改完後 push 上去，下次排程執行就會套用新的清單。`symbol` 是給網頁版「持股
表」比對用的股票代號，目前四家公司的代號是我依常見對照表填入的，第一次使用
請自行核對是否正確。

### 想改排程時間

編輯 `.github/workflows/daily-report.yml` 裡的 `cron` 設定。cron 是 UTC
時間，台灣是 UTC+8，換算時記得減 8 小時（例如想要台灣時間 08:30 執行，
就是 UTC 00:30 → `30 0 * * 1-5`）。

### 本機測試

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=你的金鑰      # Windows 用 set GEMINI_API_KEY=你的金鑰
python read_news.py
```

本機執行時行為和你原本的版本一樣：跑完會產生一份 `report_*.html` 並自動
用瀏覽器開啟；同時也會產生 `data.json`，你可以直接用瀏覽器打開這個資料夾
的 `index.html` 來預覽網頁版效果。

---

## 已知限制 / 之後可以再加強的地方

- **國定假日、颱風假**：目前只排除週六週日，沒有排除國定假日。遇到連假時，
  新聞擷取區間會自動變長（邏輯已處理），不會漏抓，但排程仍會在該日執行，
  只是可能沒有太多新內容。
- **族群動能（sectors）**：目前資料來源（新聞 + 報價 API）沒有現成的類股
  資金動能數據，所以晨報頁面上「今日焦點族群」目前是空的。如果之後想要
  這塊有真實資料，需要另外接產業類股的報價或籌碼資料來源。
- **股票代號對照**：`config.json` 裡的股票代號是我幫忙補上的常見對照，
  建議實際使用前自己核對一次。
- **本工具僅供資訊整理，不構成投資建議**——這點沿用你原本程式碼裡的免責
  聲明精神，網頁版的持股區塊也保留了同樣的提醒文字。
