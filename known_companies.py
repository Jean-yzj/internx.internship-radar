"""知名公司清單（台灣大學生辨識度高）。

用途：在 Discord Top 50 挑選時，知名公司額外加分 → 精準提升行銷素材品質。
鍵是大小寫不敏感的公司名「子字串」，命中就加 KNOWN_BONUS。

維護指引：
- 只放「大學生一看就知道在做什麼」的公司
- 子字串要夠特異（例如用「台積電」而不是「台積」，避免撞到「台積資」）
- 中英文別名都加，爬來的資料可能用其中一種
"""

from __future__ import annotations

KNOWN_BONUS = 15.0  # 分數加成，參見 notify_discord.py select_top

# 依產業分組，方便 review
KNOWN_COMPANIES: set[str] = {
    # 半導體 / 硬體科技
    "tsmc", "台積電", "台積",
    "mediatek", "聯發科",
    "foxconn", "鴻海", "富士康",
    "nvidia", "輝達",
    "asus", "華碩",
    "acer", "宏碁",
    "wistron", "緯創",
    "pegatron", "和碩",
    "quanta", "廣達",
    "compal", "仁寶",
    "delta", "台達電",
    "inventec", "英業達",
    "realtek", "瑞昱",
    "htc", "宏達電",
    # 外商科技
    "google", "meta", "facebook", "apple", "microsoft", "amazon",
    "intel", "amd", "ibm", "sap", "oracle", "cisco", "salesforce",
    "uber", "airbnb", "netflix",
    "dell", "hp",
    # 網路 / 新創 / App
    "line", "pchome", "shopee", "蝦皮", "17live",
    "91app", "dcard", "gogoro",
    "appier", "iKala",
    "kkday", "kktv", "kkbox",
    "klook",
    "carousell", "旋轉拍賣",
    "oneadvpn",
    "trend micro", "趨勢科技",
    # 金融
    "cathay", "國泰", "國泰金", "國泰人壽", "國泰世華",
    "fubon", "富邦金", "富邦人壽", "富邦銀行",
    "ctbc", "中信", "中國信託", "中信金",
    "esun", "玉山",
    "sinopac", "永豐",
    "mega", "兆豐",
    "yuanta", "元大",
    "shin kong", "新光",
    "taishin", "台新",
    "citi", "花旗",
    "hsbc", "匯豐",
    "standard chartered", "渣打",
    "jp morgan", "jpmorgan", "摩根大通",
    "goldman sachs", "高盛",
    "morgan stanley", "摩根士丹利",
    "ubs", "瑞銀",
    "barclays", "巴克萊",
    # 管顧 / 四大
    "mckinsey", "麥肯錫",
    " bcg ", "boston consulting", "波士頓顧問",
    "bain", "貝恩",
    "deloitte", "勤業眾信",
    "pwc", "資誠",
    " ey ", "ernst & young", "安永",
    "kpmg", "安侯",
    "accenture", "埃森哲",
    "booz", " atkearney",
    # 消費品 / 零售
    "unilever", "聯合利華",
    "p&g", "procter & gamble", "寶僑",
    "nestle", "雀巢",
    "coca-cola", "可口可樂",
    "pepsi", "百事",
    "l'oreal", "loreal", "萊雅",
    "uniqlo", "優衣庫",
    "7-eleven", "統一超",
    "uni-president", "統一企業",
    "momo", "富邦媒",
    "ikea", "宜家",
    # 傳產重量級
    "台塑", "formosa plastics",
    "中鋼",
    "中華電信", "chunghwa telecom",
    "台灣大哥大",
    "遠傳",
    # 媒體 / 內容
    "tvbs", "東森", "三立", "民視",
    "bloomberg", "thomson reuters", "路透",
    # 生技 / 醫療
    "中央研究院", "academia sinica",
    "台杉",
    "國家衛生研究院",
}


def is_known(company: str) -> bool:
    """大小寫不敏感，company 內任一 known 子字串命中就算。"""
    if not company:
        return False
    c = company.lower()
    return any(k.lower() in c for k in KNOWN_COMPANIES)
