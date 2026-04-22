"""實習分類定義。

一份來源、多處消費：
  - scrape_internships.py 依 keywords 分類每筆職缺
  - notify_discord.py 依分類分組 + emoji/color 建 embed
  - internships.json 內嵌分類 metadata，前端 index.html 讀取渲染 tab

分類按「大學生投遞熱度」由高到低排序；排在前面的優先 match，
且 Discord 會分配較多名額。
"""

from __future__ import annotations

# 排序代表 (a) 前端分類 tab 顯示順序、(b) 分類判斷優先順序 (first match wins)、(c) Discord 優先。
# top_n 是 Discord 每日前 50 的名額分配（總和 50；實際少於此數會自動 shrink）。

CATEGORIES: list[dict] = [
    {
        "key": "tech",
        "label": "科技／軟體",
        "emoji": "💻",
        "color": "#2563eb",
        "top_n": 10,
        "keywords_exact": [" ai ", "ai實習", "ai工程", "ai應用", "ml實習", "ml工程",
                           " ios ", " android ", " ml "],
        "keywords_contain": [
            "工程師", "engineer", "developer", "開發者", "程式", "軟體", "software",
            "前端", "frontend", "front-end",
            "後端", "backend", "back-end",
            "全端", "full stack", "full-stack", "fullstack",
            "devops", "sre", "雲端", "cloud",
            "資安", "cybersecurity", "information security",
            "演算法", "algorithm",
            "android開發", "ios開發", "mobile開發", "app開發",
            "機器學習", "深度學習", "人工智慧",
            "machine learning", "deep learning",
            "r&d", "research and development",
            "網路工程", "network engineer",
            "韌體", "firmware", "嵌入式", "embedded",
            "技術", "technology engineer",
            "qa", "testing", "test automation", "自動化測試",
            "high-tech", "hightech",
        ],
    },
    {
        "key": "data",
        "label": "資料分析",
        "emoji": "📊",
        "color": "#14b8a6",
        "top_n": 4,
        "keywords_contain": [
            "資料分析", "data analyst", "data analysis",
            "數據分析", "business analyst", "商業分析",
            "analytics", "data scientist", "資料科學",
            "data engineer", "資料工程", "數據工程",
            "商業智慧", "business intelligence", "bi分析",
            "報表分析",
        ],
    },
    {
        "key": "pm",
        "label": "產品",
        "emoji": "🎯",
        "color": "#8b5cf6",
        "top_n": 3,
        "keywords_contain": [
            "產品經理", "product manager", "product management",
            "產品企劃", "產品助理", "產品營運",
            "產品實習", "product intern", "產品實習生",
            "associate product manager", "apm",
        ],
    },
    {
        "key": "finance",
        "label": "金融",
        "emoji": "💰",
        "color": "#f59e0b",
        "top_n": 5,
        "keywords_contain": [
            "金融", "financial", "finance",
            "銀行", "bank", "banking",
            "投資", "investment",
            "證券", "securities",
            "基金", "fund", "asset management",
            "保險", "insurance", "精算",
            "量化", "quant", "quantitative",
            "交易員", "trading", "trader",
            "理財", "信貸", "credit",
            "風控", "risk management",
            "外匯", "forex",
            "投資銀行", "ib實習", "ibd",
            "財務分析", "treasury",
            "資本市場", "capital market",
            "私募", "private equity", "venture capital", " vc ",
        ],
    },
    {
        "key": "consulting",
        "label": "管顧／策略",
        "emoji": "🧭",
        "color": "#ec4899",
        "top_n": 4,
        "keywords_contain": [
            "管顧", "consulting", "consultant", "顧問",
            "策略", "strategy", "strategic",
            "商業顧問", "business consultant",
            "企管", "企業管理顧問",
        ],
    },
    {
        "key": "marketing",
        "label": "行銷／品牌",
        "emoji": "📣",
        "color": "#dc2626",
        "top_n": 5,
        "keywords_contain": [
            "行銷", "marketing", "marketer",
            "品牌", "brand",
            "社群", "social media",
            "數位行銷", "digital marketing", "performance marketing",
            "廣告", "advertising", "ad operations",
            "媒體企劃", "media planning", "media buyer",
            "成長", "growth",
            " seo ", " sem ", "搜尋引擎",
            "投放", "廣編",
            "市場研究", "market research",
            "活動企劃", "公關", "pr ",
            "kol", "網紅",
        ],
    },
    {
        "key": "content",
        "label": "內容／媒體",
        "emoji": "✍️",
        "color": "#10b981",
        "top_n": 3,
        "keywords_contain": [
            "內容", "content",
            "編輯", "editor", "editorial",
            "文案", "copywriter", "copywriting",
            "記者", "journalist", "採訪",
            "撰稿", "writer",
            "影音", "video production",
            "攝影", "photographer",
            "剪輯", "video editor",
            "podcast", "直播", "主持",
            "編導", "節目",
            "自媒體",
        ],
    },
    {
        "key": "design",
        "label": "設計／UIUX",
        "emoji": "🎨",
        "color": "#f472b6",
        "top_n": 3,
        "keywords_contain": [
            "設計師", "designer", "design intern",
            "視覺", "visual",
            "ui/ux", "uiux", " ux ", " ui ",
            "user experience", "user interface",
            "平面設計", "graphic design",
            "插畫", "illustration",
            "美術", "art director",
            "動畫", "motion graphics",
            "工業設計", "industrial design",
        ],
    },
    {
        "key": "bd_sales",
        "label": "BD／業務",
        "emoji": "🤝",
        "color": "#0ea5e9",
        "top_n": 3,
        "keywords_contain": [
            "business development", "bd實習", "bd intern",
            "商務開發", "商業開發",
            "銷售", "sales",
            "account manager", "key account",
            "業務", "業務開發",
            "客戶經理", "客戶關係",
            "合作夥伴", "partnership",
            "channel manager", "通路",
        ],
    },
    {
        "key": "hr",
        "label": "人資",
        "emoji": "👥",
        "color": "#6366f1",
        "top_n": 3,
        "keywords_contain": [
            "人資", "hr intern", "hr實習",
            "human resources",
            "招募", "recruiter", "recruiting", "talent acquisition",
            "人才發展", "talent development",
            "employer branding", "雇主品牌",
            "organizational development", "組織發展",
            "people operations", "people ops",
            "薪酬", "compensation", "benefits",
            "訓練發展", "learning and development",
        ],
    },
    {
        "key": "accounting",
        "label": "會計／審計",
        "emoji": "📒",
        "color": "#a16207",
        "top_n": 2,
        "keywords_contain": [
            "會計", "accounting", "accountant",
            "審計", "audit", "auditor",
            "財會",
            "稅務", "tax",
            "內控", "內部稽核", "internal control", "internal audit",
            "帳務", "出納",
        ],
    },
    {
        "key": "operations",
        "label": "營運／專案",
        "emoji": "🗂️",
        "color": "#71717a",
        "top_n": 2,
        "keywords_contain": [
            "營運", "operation intern", "operations",
            "專案管理", "project management", "pmo",
            "project coordinator", "project assistant",
            "行政", "administrative",
            "助理", "assistant",
            "行政實習",
            "客戶成功", "customer success", "客戶支援", "customer support",
        ],
    },
    {
        "key": "legal",
        "label": "法務",
        "emoji": "⚖️",
        "color": "#64748b",
        "top_n": 1,
        "keywords_contain": [
            "法務", "legal",
            "律師", "lawyer", "paralegal",
            "合規", "compliance",
            "智慧財產", "智財", "專利", "patent",
            "契約", "contract review",
        ],
    },
    {
        "key": "supply_chain",
        "label": "供應鏈",
        "emoji": "📦",
        "color": "#84cc16",
        "top_n": 1,
        "keywords_contain": [
            "採購", "procurement", "purchasing", "buyer",
            "供應鏈", "supply chain",
            "物流", "logistics",
            "倉儲", "warehouse",
            "貿易", "trade operation",
            "空運", "海運", "air freight", "sea freight",
            "進出口", "出口", "報關", "customs",
        ],
    },
    {
        "key": "research",
        "label": "研究",
        "emoji": "🔬",
        "color": "#059669",
        "top_n": 1,
        "keywords_contain": [
            "研究助理", "research assistant", "ra實習",
            "實驗室", "laboratory",
            "研究員", "researcher",
            "學術研究",
            "市場調查研究",
        ],
    },
    {
        "key": "other",
        "label": "其他",
        "emoji": "📋",
        "color": "#94a3b8",
        "top_n": 0,
        "keywords_contain": [],
    },
]


CATEGORY_BY_KEY: dict[str, dict] = {c["key"]: c for c in CATEGORIES}


def categorize(title: str, company: str, description: str) -> str:
    """判定分類。

    Title 是最可靠訊號（職務名稱），優先用 title 判斷；
    title 無法命中時才退到 title+description（不看公司名，因為公司名
    常含「顧問」「法律」等誤導性字詞）。
    """
    def match(hay: str) -> str | None:
        padded = f" {hay} "
        for cat in CATEGORIES:
            if cat["key"] == "other":
                continue
            if any(k in hay for k in cat.get("keywords_contain", [])):
                return cat["key"]
            if any(k in padded for k in cat.get("keywords_exact", [])):
                return cat["key"]
        return None

    t = (title or "").lower()
    hit = match(t)
    if hit:
        return hit
    # 退一步：title + description
    hit = match(f"{t} {(description or '').lower()}")
    return hit or "other"


def hex_to_int(hex_color: str) -> int:
    """Discord embed color 要整數 (0xRRGGBB)。"""
    return int(hex_color.lstrip("#"), 16)


def color_int(category_key: str) -> int:
    return hex_to_int(CATEGORY_BY_KEY.get(category_key, CATEGORY_BY_KEY["other"])["color"])
