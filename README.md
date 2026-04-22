# 實習雷達 · Internship Radar

即時彙整 **104、CakeResume、Yourator** 最新實習職缺，過濾「7 天內上架 + 有薪資」，
GitHub Actions 每天自動抓 3 次，網站前端直接讀最新 JSON。

## 專案結構

```
internship-radar/
├── index.html                 # 公開檢視頁面
├── scrape_internships.py      # 爬蟲主腳本
├── requirements.txt
├── data/
│   └── internships.json       # 爬下來的結果 (Action 會自動更新這個檔)
├── .github/workflows/
│   └── scrape.yml             # cron workflow
├── zeabur.json                # Zeabur 部署設定
└── .gitignore
```

## 部署方式

### 路線 A：GitHub Pages（最簡單）

1. 在 GitHub 建一個新 repo（例：`internship-radar`），把這整個資料夾的內容 push 上去。
2. repo Settings → Pages → Source 選 **Deploy from a branch**，branch 選 `main` / root。
3. repo Settings → Actions → General → Workflow permissions 選 **Read and write permissions**（讓 Action 能 commit 回 repo）。
4. Actions 分頁找到 `Update Internship Data`，按 **Run workflow** 手動跑一次，確認產生 `data/internships.json`。
5. 打開 `https://<你的帳號>.github.io/internship-radar/` 就能看到。

預設 cron 是每天 UTC 00:00 / 06:00 / 12:00（台灣時間 08:00、14:00、20:00），
想改頻率就編輯 `.github/workflows/scrape.yml` 最上方的 `cron:`。

### 路線 B：Zeabur

Zeabur 負責網頁靜態部署，GitHub Actions 還是負責 cron 抓資料。

1. 一樣先把 repo push 到 GitHub。
2. Zeabur Dashboard → Create Project → **Deploy from GitHub** → 選這個 repo。
3. Zeabur 會讀 `zeabur.json`，把它當靜態網站部署。
4. 綁自訂網域或用 Zeabur 給的 URL 分享。
5. 資料更新仍靠 GH Actions：它 commit 新的 `data/internships.json` 回 main，Zeabur 偵測到 push 會自動重新部署。

如果不想走 GitHub Actions，也能改用 Zeabur 的 **Cron Service**：
新增一個 Service 類型選 Cron，Runtime 用 Python，command 設 `python scrape_internships.py --output data/internships.json` —— 但這樣資料要另外推回 repo，比較麻煩，建議還是用 GH Actions。

## 本機開發

```bash
pip install -r requirements.txt
python scrape_internships.py --output data/internships.json

# 本機起簡單 server（Python 3 內建）
python -m http.server 8000
# 打開 http://localhost:8000
```

## 自訂選項

`scrape_internships.py` 支援的 CLI 參數：

| 參數 | 預設 | 說明 |
|---|---|---|
| `--days N` | 7 | 只保留 N 天內上架的職缺 |
| `--keyword KW` | 實習 | 搜尋關鍵字（想找 "UI/UX" 就設成 UI/UX） |
| `--no-salary-filter` | (off) | 不過濾面議職缺 |
| `--output PATH` | internships.json | 輸出檔位置 |

想改 workflow 的抓取條件，編輯 `.github/workflows/scrape.yml` 裡 `python scrape_internships.py ...` 那行即可。

## 常見狀況

**網站顯示「無法載入資料」**
→ 第一次部署 Action 還沒跑，去 Actions 分頁手動觸發 `Update Internship Data`。

**某個平台永遠抓 0 筆**
→ 平台可能改了 API。看 Actions log 是哪個平台報錯，進 `scrape_internships.py` 的 `fetch_104 / fetch_cakeresume / fetch_yourator` 三個 function 調整 endpoint 或 query 參數。

**想加 LinkedIn**
→ LinkedIn 需要登入才能看職缺清單，不建議用爬蟲（會被封）。要的話改用付費的 LinkedIn Jobs API 或第三方 Proxycurl。

## 資料欄位

每筆職缺包含：

```json
{
  "platform": "104",
  "title": "軟體工程實習生",
  "company": "某某科技",
  "location": "台北市信義區",
  "salary": "月薪 35,000~45,000 元",
  "salary_min": 35000,
  "salary_type": "monthly",
  "posted_at": "2026-04-21",
  "url": "https://www.104.com.tw/job/...",
  "description": "..."
}
```

`salary_min` 是月薪下限（NTD）；時薪會自動換算成 `時薪 × 176 小時`，方便同尺度比較。

---

授權：MIT · 請合理使用爬蟲，勿高頻打擊原站 API。
