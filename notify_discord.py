"""將每日實習推到 Discord（以 embed 分類呈現）。

讀取 scrape_internships.py 產生的 JSON，每日選出最多 50 筆，
依 categories.py 的分類分組送出 — 供行銷同仁產出 Thread 貼文用。

選擇演算法：
  - 若總筆數 ≤ 50，全部發出
  - 否則按各分類 top_n 配額挑選，不足的名額再按優先順序補給科技類
  - 每個分類內排序：first_seen 新的優先 → salary 高的優先

Webhook URL 必須放在環境變數 DISCORD_WEBHOOK_URL。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time

import requests

from categories import CATEGORIES, CATEGORY_BY_KEY, color_int
from known_companies import is_known, KNOWN_BONUS


MAX_JOBS = 50
EMBED_DESC_LIMIT = 4000
EMBEDS_PER_MESSAGE = 10
TOTAL_EMBED_CHARS_PER_MESSAGE = 5800


def _salary_percentile_map(jobs: list[dict]) -> dict[str, float]:
    """把有薪資的職缺轉成「薪資百分位」(0..1)，沒薪資的回 0.3（中性偏低）。"""
    pairs = [(j.get("url") or id(j), j.get("salary_min") or 0) for j in jobs]
    valid = sorted((v for _, v in pairs if v > 0))
    n = len(valid)
    def pct(v: int) -> float:
        if v <= 0 or n == 0:
            return 0.3
        import bisect
        return bisect.bisect_left(valid, v) / max(1, n - 1)
    return {k: pct(v) for k, v in pairs}


def score_job(j: dict, salary_pct: dict, today_iso: str) -> float:
    """Composite 分數（越高越會被選入 Top 50）。

    構成（大致對應使用者的定義）：
      - 分類優先：排越前的類別分越高（0-20）
      - 新鮮度：first_seen 越接近今天分越高（0-15）
      - 薪資百分位：0-15
      - 知名公司 bonus：+KNOWN_BONUS
    """
    cat_idx = next(
        (i for i, c in enumerate(CATEGORIES) if c["key"] == j.get("category")),
        len(CATEGORIES) - 1,
    )
    cat_score = max(0.0, 20.0 - cat_idx * 1.0)

    fs = j.get("first_seen") or ""
    if fs and today_iso:
        try:
            import datetime as _dt
            d = _dt.date.fromisoformat(fs)
            today = _dt.date.fromisoformat(today_iso)
            days_old = max(0, (today - d).days)
            freshness = max(0.0, 15.0 - days_old * 2.0)
        except Exception:
            freshness = 0.0
    else:
        freshness = 0.0

    key = j.get("url") or id(j)
    sal_score = 15.0 * salary_pct.get(key, 0.3)

    known_bonus = KNOWN_BONUS if is_known(j.get("company") or "") else 0.0

    return cat_score + freshness + sal_score + known_bonus


def select_top(jobs: list[dict], limit: int = MAX_JOBS) -> dict[str, list[dict]]:
    """用 composite score 挑前 limit 筆，再按分類分組（分類內保留分數排序）。

    vs 舊版配額：
      - 舊版硬分配每類別 N 筆，常會把低分「補齊」進去
      - 新版按全域分數挑，知名公司 + 高薪 + 新鮮的職缺會浮上來，
        精準度大幅提升；分類仍保留在輸出結構給行銷同仁看。
    """
    if not jobs:
        return {}
    today_iso = dt.date.today().isoformat()
    salary_pct = _salary_percentile_map(jobs)
    scored = sorted(
        jobs,
        key=lambda j: score_job(j, salary_pct, today_iso),
        reverse=True,
    )[:limit]

    buckets: dict[str, list[dict]] = {c["key"]: [] for c in CATEGORIES}
    for j in scored:
        key = j.get("category") or "other"
        buckets.setdefault(key, []).append(j)

    return {k: v for k, v in buckets.items() if v}


def format_job(j: dict) -> str:
    title = (j.get("title") or "—").replace("\n", " ").strip()
    url = j.get("url") or ""
    is_new = j.get("first_seen") == dt.date.today().isoformat()
    head = f"**[{title}]({url})**" if url else f"**{title}**"
    if is_new:
        head = f"✨ {head}"

    company = (j.get("company") or "").strip()
    location = (j.get("location") or "").strip()
    line2_parts = []
    if company:
        line2_parts.append(f"🏢 {company}")
    if location:
        line2_parts.append(f"📍 {location}")
    line2 = " · ".join(line2_parts)

    line3_parts = []
    if j.get("salary"):
        line3_parts.append(f"💰 {j['salary']}")
    line3_parts.append(f"_{j.get('platform', '?')}_")
    line3 = " · ".join(line3_parts)

    parts = [head]
    if line2:
        parts.append(line2)
    parts.append(line3)
    return "\n".join(parts)


def build_embeds(selected: dict[str, list[dict]]) -> list[dict]:
    embeds: list[dict] = []
    for cat in CATEGORIES:
        key = cat["key"]
        jobs = selected.get(key) or []
        if not jobs:
            continue
        # 切 block，單 embed description <= 4000 字
        blocks: list[list[str]] = [[]]
        cur_len = 0
        for j in jobs:
            txt = format_job(j)
            if cur_len + len(txt) + 2 > EMBED_DESC_LIMIT and blocks[-1]:
                blocks.append([])
                cur_len = 0
            blocks[-1].append(txt)
            cur_len += len(txt) + 2
        total_blocks = len(blocks)
        for i, blk in enumerate(blocks):
            if not blk:
                continue
            suffix = "" if total_blocks == 1 else f" ({i + 1}/{total_blocks})"
            embeds.append({
                "title": f"{cat['emoji']} {cat['label']} · {len(jobs)} 筆{suffix}",
                "description": "\n\n".join(blk),
                "color": color_int(key),
            })
    return embeds


def chunk_embeds(embeds: list[dict]) -> list[list[dict]]:
    batches: list[list[dict]] = [[]]
    cur_chars = 0
    for emb in embeds:
        cost = len(emb.get("title", "")) + len(emb.get("description", ""))
        if (len(batches[-1]) >= EMBEDS_PER_MESSAGE
                or cur_chars + cost > TOTAL_EMBED_CHARS_PER_MESSAGE):
            batches.append([])
            cur_chars = 0
        batches[-1].append(emb)
        cur_chars += cost
    return [b for b in batches if b]


def post(webhook: str, content: str | None = None, embeds: list[dict] | None = None) -> None:
    payload: dict = {"allowed_mentions": {"parse": []}}
    if content:
        payload["content"] = content
    if embeds:
        payload["embeds"] = embeds
    for _ in range(3):
        r = requests.post(webhook, json=payload, timeout=20)
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
    ap.add_argument("input", nargs="?", default="data/new_today.json")
    ap.add_argument("--limit", type=int, default=MAX_JOBS,
                    help=f"最多推送幾筆（預設 {MAX_JOBS}）")
    args = ap.parse_args()

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        print("ERROR: DISCORD_WEBHOOK_URL 未設定", file=sys.stderr)
        return 2

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    jobs = data.get("jobs", []) or []
    today = dt.date.today().isoformat()

    if not jobs:
        post(webhook,
             content=f"🎯 **實習雷達 · {today}**\n今天沒有新發現的實習職缺。")
        print("Posted empty-day notice.")
        return 0

    selected = select_top(jobs, args.limit)
    total_selected = sum(len(v) for v in selected.values())
    total_available = len(jobs)

    # Header：統計 + 說明
    cat_counts_text = " / ".join(
        f"{CATEGORY_BY_KEY[k]['emoji']}{len(v)}"
        for k in [c["key"] for c in CATEGORIES]
        if (v := selected.get(k))
    )
    truncated_note = ""
    if total_available > total_selected:
        truncated_note = f"（共發現 {total_available} 筆，精選前 {total_selected} 筆）"

    header = (
        f"🎯 **實習雷達 · {today}**\n"
        f"本次推播 **{total_selected}** 筆{truncated_note}\n"
        f"{cat_counts_text}"
    )

    embeds = build_embeds(selected)
    batches = chunk_embeds(embeds)

    for i, batch in enumerate(batches):
        post(webhook, content=header if i == 0 else None, embeds=batch)
        if i < len(batches) - 1:
            time.sleep(0.7)

    print(f"Posted {len(batches)} message(s) / {len(embeds)} embed(s) / {total_selected} jobs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
