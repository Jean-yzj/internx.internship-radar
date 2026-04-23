"""每週一早 9am 發 Discord 週報。

以 seen.json 的 first_seen 欄位為本源：
  - 本週新增：first_seen 落在最近 7 天的職缺
  - 新增公司：first_seen 落在 7 天內且該公司之前從沒在 seen 裡出現過
  - 各分類新增數
  - 知名公司的新職缺（挑最多 10 則）

Webhook URL 必須放 DISCORD_WEBHOOK_URL。
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import sys

import requests

from categories import CATEGORIES, CATEGORY_BY_KEY, color_int
from known_companies import is_known


def load_jobs(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("jobs", []) or []


def load_seen(path: str) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    urls = raw.get("urls") or {}
    out = {}
    for u, v in urls.items():
        if isinstance(v, dict):
            out[u] = v
        elif isinstance(v, str):
            out[u] = {"first_seen": v, "last_seen": v}
    return out


def post_discord(webhook: str, content: str, embeds: list[dict]) -> None:
    payload = {"allowed_mentions": {"parse": []}}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds
    r = requests.post(webhook, json=payload, timeout=20)
    r.raise_for_status()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--internships", default="data/internships.json")
    ap.add_argument("--seen", default="data/seen.json")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("ERROR: DISCORD_WEBHOOK_URL 未設定", file=sys.stderr)
        return 2

    today = dt.date.today()
    cutoff = today - dt.timedelta(days=args.days)
    cutoff_iso = cutoff.isoformat()
    today_iso = today.isoformat()

    jobs = load_jobs(args.internships)
    seen = load_seen(args.seen)

    # 本週新增 = first_seen >= cutoff
    new_jobs = [j for j in jobs if (j.get("first_seen") or "") >= cutoff_iso]
    # 本週新增的公司 = 公司的所有 URL 都是本週才第一次看到
    # （等同於：該公司沒有任何 URL first_seen < cutoff）
    company_first_seen: dict[str, str] = {}
    for url, meta in seen.items():
        # 找公司名 from current jobs only (seen.json 沒存公司名)
        pass
    # 簡化：用目前仍在列表的 job 計公司首見日 = min of first_seen of that company
    company_min: dict[str, str] = {}
    for j in jobs:
        c = (j.get("company") or "").strip()
        if not c:
            continue
        fs = j.get("first_seen") or today_iso
        if c not in company_min or fs < company_min[c]:
            company_min[c] = fs
    new_companies = sorted(
        [c for c, fs in company_min.items() if fs >= cutoff_iso]
    )

    # 各分類新增數
    cat_counts = collections.Counter(j.get("category", "other") for j in new_jobs)

    # 知名公司的新職缺（挑前 10）
    known_new = [j for j in new_jobs if is_known(j.get("company") or "")]
    known_new.sort(key=lambda j: (j.get("first_seen") or "", j.get("salary_min") or 0), reverse=True)
    known_new = known_new[:10]

    # ---- 組 embeds ----
    embeds: list[dict] = []

    # 主要數字 embed
    cat_lines = []
    for c in CATEGORIES:
        n = cat_counts.get(c["key"], 0)
        if n == 0:
            continue
        cat_lines.append(f"{c['emoji']} {c['label']}：**{n}**")
    stats_desc = (
        f"📊 本週新增 **{len(new_jobs)}** 筆職缺\n"
        f"🏢 新增公司 **{len(new_companies)}** 家\n\n"
        f"**分類分佈：**\n" + ("\n".join(cat_lines) if cat_lines else "（無）")
    )
    embeds.append({
        "title": f"📮 實習雷達週報 · {cutoff.strftime('%m/%d')} – {today.strftime('%m/%d')}",
        "description": stats_desc,
        "color": 0x4f46e5,
    })

    # 新增公司 embed
    if new_companies:
        max_companies = 25
        shown = new_companies[:max_companies]
        desc_lines = []
        for c in shown:
            tag = "⭐ " if is_known(c) else "• "
            desc_lines.append(f"{tag}{c}")
        more = f"\n\n（另有 {len(new_companies) - max_companies} 家省略）" if len(new_companies) > max_companies else ""
        embeds.append({
            "title": f"🏢 本週首次出現的公司（{len(new_companies)}）",
            "description": "\n".join(desc_lines) + more,
            "color": 0x10b981,
        })

    # 知名公司亮點 embed
    if known_new:
        lines = []
        for j in known_new:
            title = (j.get("title") or "").strip()
            url = j.get("url") or ""
            company = j.get("company") or ""
            salary = j.get("salary") or ""
            head = f"**[{title}]({url})**" if url else f"**{title}**"
            lines.append(f"{head}\n🏢 {company} · 💰 {salary}")
        embeds.append({
            "title": "⭐ 知名公司本週新職缺",
            "description": "\n\n".join(lines),
            "color": 0xf59e0b,
        })

    content = f"📬 **週報 · {today.strftime('%Y-%m-%d')}**"
    post_discord(webhook, content, embeds)
    print(f"Weekly trend posted: {len(new_jobs)} new jobs, {len(new_companies)} new companies, "
          f"{len(known_new)} known-company highlights")
    return 0


if __name__ == "__main__":
    sys.exit(main())
