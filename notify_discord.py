"""將每日實習資料推到 Discord 頻道。

讀取 scrape_internships.py 產生的 JSON，分類後發送：
  1. 科技業（優先）
  2. 金融／管顧
  3. 其他

Webhook URL 必須放在環境變數 DISCORD_WEBHOOK_URL，絕不寫在程式碼中。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

import requests


TECH_KEYWORDS = [
    # 職務
    "工程師", "engineer", "developer", "開發", "程式", "軟體", "software",
    "資料", "data", "人工智慧", "機器學習", "深度學習",
    "研發", "r&d", "前端", "frontend", "後端", "backend",
    "full stack", "full-stack", "全端", "devops", "sre", "qa",
    "測試工程", "自動化", "ux", "ui",
    "技術", "tech", "資訊", "演算法", "algorithm",
    "雲端", "cloud", "資安", "security", "網路工程",
    "ios", "android", "mobile", "app開發",
    "數據", "database",
]

TECH_KEYWORDS_EXACT = [" ai ", "ai實習", "ai工程", "ml實習", "ml工程"]

FINANCE_CONSULTING_KEYWORDS = [
    "金融", "finance", "financial", "銀行", "bank",
    "投資", "investment", "證券", "securities", "基金", "fund",
    "保險", "insurance", "管顧", "consulting", "consultant", "顧問",
    "策略", "strategy", "會計", "accounting", "審計", "audit",
    "m&a", "併購", "財務", "treasury", "精算", "actuarial",
    "交易員", "trading", "trader", "風控", "信貸", "理財",
]


def categorize(job: dict) -> str:
    hay = " ".join([
        (job.get("title") or "").lower(),
        (job.get("company") or "").lower(),
        (job.get("description") or "").lower(),
    ])
    padded = f" {hay} "
    if any(k in hay for k in TECH_KEYWORDS) or any(k in padded for k in TECH_KEYWORDS_EXACT):
        return "tech"
    if any(k in hay for k in FINANCE_CONSULTING_KEYWORDS):
        return "finance"
    return "other"


def format_job_line(j: dict) -> str:
    title = j.get("title") or "—"
    url = j.get("url") or ""
    head = f"[**{title}**](<{url}>)" if url else f"**{title}**"
    head += f" · {j.get('company') or '—'}"

    meta_parts = []
    if j.get("salary"):
        meta_parts.append(f"💰 {j['salary']}")
    if j.get("location"):
        meta_parts.append(f"📍 {j['location']}")
    if j.get("posted_at"):
        meta_parts.append(f"🗓 {j['posted_at']}")
    meta_parts.append(f"_{j.get('platform', '?')}_")
    return f"• {head}\n  {' · '.join(meta_parts)}"


def chunk_messages(
    header: str,
    sections: list[tuple[str, list[dict]]],
    max_len: int = 1900,
) -> list[str]:
    """將 header + 多個 section 切成 <=max_len 字的訊息陣列。"""
    messages: list[str] = []
    current = header
    for section_title, jobs in sections:
        block = f"\n\n━━━━━━━━━━━━━━━━\n{section_title}"
        if len(current) + len(block) > max_len:
            messages.append(current)
            current = block.lstrip()
        else:
            current += block
        for j in jobs:
            line = "\n" + format_job_line(j)
            if len(current) + len(line) > max_len:
                messages.append(current)
                current = line.lstrip()
            else:
                current += line
    if current.strip():
        messages.append(current)
    return messages


def post(webhook: str, content: str) -> None:
    payload = {"content": content, "allowed_mentions": {"parse": []}}
    for attempt in range(3):
        r = requests.post(webhook, json=payload, timeout=15)
        if r.status_code == 429:
            try:
                wait = float(r.json().get("retry_after", 1))
            except Exception:
                wait = 1.0
            time.sleep(wait + 0.3)
            continue
        r.raise_for_status()
        return
    raise RuntimeError("Discord rate limited after retries")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", default="data/internships.json")
    args = ap.parse_args()

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("ERROR: DISCORD_WEBHOOK_URL 未設定", file=sys.stderr)
        return 2

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs = data.get("jobs", [])
    today = dt.date.today().isoformat()
    days = (data.get("params") or {}).get("days", 7)

    if not jobs:
        post(
            webhook,
            f"🎯 **實習雷達 · {today}**\n"
            f"今天沒有符合條件的新職缺（過去 {days} 天內上架、有明確薪資）。",
        )
        return 0

    buckets: dict[str, list[dict]] = {"tech": [], "finance": [], "other": []}
    for j in jobs:
        buckets[categorize(j)].append(j)

    header = (
        f"🎯 **實習雷達 · {today}**\n"
        f"來源：104 / CakeResume / Yourator · 過去 {days} 天上架 · 有明確薪資\n"
        f"共 **{len(jobs)}** 筆 · "
        f"科技 {len(buckets['tech'])} / 金融管顧 {len(buckets['finance'])} / 其他 {len(buckets['other'])}"
    )

    sections = [
        (f"💻 **科技業（{len(buckets['tech'])} 筆）**", buckets["tech"]),
        (f"💰 **金融／管顧（{len(buckets['finance'])} 筆）**", buckets["finance"]),
        (f"📋 **其他（{len(buckets['other'])} 筆）**", buckets["other"]),
    ]
    sections = [(t, js) for t, js in sections if js]

    messages = chunk_messages(header, sections)
    for i, msg in enumerate(messages):
        post(webhook, msg)
        if i < len(messages) - 1:
            time.sleep(0.6)
    print(f"Posted {len(messages)} message(s), {len(jobs)} jobs total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
