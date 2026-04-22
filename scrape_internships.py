"""實習招募資料爬蟲

抓取 104、CakeResume、Yourator 目前平台上所有「實習」職缺，
依 categories.py 的 16 類別分類，輸出：

  data/internships.json  目前全部未截止的實習（供網站）
  data/new_today.json    這次跑才第一次看到的職缺（供 Discord）
  data/seen.json         歷史去重資料 {url: 首次看到日期}

使用方式：
    pip install -r requirements.txt
    python scrape_internships.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any

try:
    import requests
except ImportError:
    print("缺少 requests 套件，請先執行：pip install -r requirements.txt")
    sys.exit(1)

from categories import CATEGORIES, categorize


# ---------- 資料模型 ----------

@dataclass
class Job:
    platform: str
    title: str
    company: str
    location: str
    salary: str
    salary_min: int | None
    salary_type: str
    posted_at: str
    url: str
    description: str = ""
    category: str = "other"
    first_seen: str = ""


# ---------- 共用工具 ----------

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_salary(text: str) -> tuple[int | None, str]:
    if not text:
        return None, "unknown"
    t = text.replace(",", "").replace(" ", "")
    if "面議" in t or "negotiable" in t.lower():
        return None, "negotiable"
    nums = [int(n) for n in re.findall(r"\d+", t)]
    if not nums:
        return None, "unknown"
    first = nums[0]
    if "時薪" in t or "hourly" in t.lower() or "/hr" in t.lower():
        return first * 176, "hourly"
    if "日薪" in t:
        return first * 22, "hourly"
    if "年薪" in t or "annual" in t.lower():
        return first // 12, "monthly"
    if "月薪" in t or "monthly" in t.lower() or first >= 10000:
        return first, "monthly"
    return None, "unknown"


def within_days(date_str: str, days: int) -> bool:
    try:
        s = date_str.replace("-", "").replace("/", "")
        d = dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except Exception:
        return False
    return (dt.date.today() - d).days <= days


# ---------- 104 ----------

def fetch_104(keyword: str, max_pages: int) -> list[Job]:
    """104 公開搜尋 API。注意：data 直接是 list（2026 新版）。"""
    log("→ 抓 104 人力銀行...")
    jobs: list[Job] = []
    base = "https://www.104.com.tw/jobs/search/api/jobs"
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.104.com.tw/jobs/search/",
        "Accept": "application/json, text/plain, */*",
    }
    for page in range(1, max_pages + 1):
        params = {
            "ro": "0", "kwop": "7", "keyword": keyword,
            "expansionType": "area,spec,com,job,wf,wktm",
            "order": "16", "asc": "0", "page": str(page),
            "mode": "s", "jobsource": "2018indexpoc",
        }
        try:
            r = requests.get(base, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log(f"  page {page} 失敗：{e}")
            break

        # 2026 新版：data 直接是 list；舊版：data.list
        raw = data.get("data") or []
        if isinstance(raw, dict):
            raw = raw.get("list") or []
        if not raw:
            break

        for it in raw:
            try:
                title = (it.get("jobName") or "").strip()
                if "實習" not in title and "intern" not in title.lower():
                    continue
                company = (it.get("custName") or "").strip()
                location = (it.get("jobAddrNoDesc") or it.get("jobAddress") or "").strip()
                salary_raw = (it.get("salaryDesc") or "").strip()
                appear = it.get("appearDate") or ""
                link_obj = it.get("link") or {}
                link = link_obj.get("job") or ""
                if link.startswith("//"):
                    link = "https:" + link
                elif link.startswith("/"):
                    link = "https://www.104.com.tw" + link
                smin, stype = parse_salary(salary_raw)
                posted = f"{appear[:4]}-{appear[4:6]}-{appear[6:8]}" if len(appear) == 8 and appear.isdigit() else ""
                jobs.append(Job(
                    platform="104", title=title, company=company, location=location,
                    salary=salary_raw, salary_min=smin, salary_type=stype,
                    posted_at=posted, url=link,
                    description=(it.get("description") or it.get("descSnippet") or "")[:200],
                ))
            except Exception as e:
                log(f"  解析 item 失敗：{e}")
        time.sleep(0.8)
    log(f"  104 取得 {len(jobs)} 筆")
    return jobs


# ---------- Yourator ----------

def fetch_yourator(keyword: str, max_pages: int) -> list[Job]:
    """Yourator v4 公開 API。注意：salary 是格式化字串，lastActiveAt 是相對時間。"""
    log("→ 抓 Yourator...")
    jobs: list[Job] = []
    base = "https://www.yourator.co/api/v4/jobs"
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.yourator.co/jobs",
        "Accept": "application/json",
    }
    for page in range(1, max_pages + 1):
        params = {
            "position[]": "intern",
            "page": str(page),
            "sort": "published_at",
        }
        try:
            r = requests.get(base, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log(f"  page {page} 失敗：{e}")
            break

        payload = data.get("payload") or {}
        items = payload.get("jobs") or []
        if not items:
            break
        has_more = bool(payload.get("hasMore"))

        for it in items:
            try:
                title = (it.get("name") or it.get("title") or "").strip()
                # position[]=intern 已在 API 端過濾，不再額外字串過濾
                company_obj = it.get("company") or {}
                company = (company_obj.get("brand") or company_obj.get("name") or "").strip()
                location = (it.get("location") or "").strip()
                salary_raw = (it.get("salary") or "").strip() or "面議"
                smin, stype = parse_salary(salary_raw)
                # Yourator 不提供準確上架日期；留空
                posted = ""
                path = it.get("path") or ""
                if path.startswith("http"):
                    url = path
                elif path.startswith("/"):
                    url = f"https://www.yourator.co{path}"
                else:
                    url = "https://www.yourator.co/jobs"
                tags = it.get("tags") or []
                desc = " / ".join(tags) if isinstance(tags, list) else ""
                jobs.append(Job(
                    platform="Yourator", title=title, company=company, location=location,
                    salary=salary_raw, salary_min=smin, salary_type=stype,
                    posted_at=posted, url=url, description=desc[:200],
                ))
            except Exception as e:
                log(f"  解析 item 失敗：{e}")
        if not has_more:
            break
        time.sleep(0.8)
    log(f"  Yourator 取得 {len(jobs)} 筆")
    return jobs


# ---------- CakeResume ----------
# Cake 的搜尋 API 已撤下、HTML 結構依賴 JS 渲染；目前暫時停用，等找到穩定入口再補。

def fetch_cakeresume(keyword: str, max_pages: int) -> list[Job]:
    log("→ 抓 CakeResume...（已停用，等重寫）")
    return []


# ---------- 主流程 ----------

def run(
    days: int | None,
    keyword: str,
    salary_filter: bool,
    max_pages: int,
    output: str,
    seen_path: str,
    new_output: str,
) -> None:
    all_jobs: list[Job] = []
    for fn in (fetch_104, fetch_cakeresume, fetch_yourator):
        try:
            all_jobs.extend(fn(keyword, max_pages))
        except Exception as e:
            log(f"❌ {fn.__name__} 整個失敗：{e}")

    log(f"原始總數：{len(all_jobs)}")

    # 過濾
    filtered: list[Job] = []
    for j in all_jobs:
        if days is not None and j.posted_at and not within_days(j.posted_at, days):
            continue
        if salary_filter and j.salary_type in ("negotiable", "unknown"):
            continue
        filtered.append(j)

    # 去重：以 URL 為 key；無 URL 時退而求其次
    seen_keys: set[tuple[str, ...]] = set()
    unique: list[Job] = []
    for j in filtered:
        key = (j.url,) if j.url else (j.title, j.company, j.platform)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(j)

    # 分類 + first_seen
    today = dt.date.today().isoformat()
    seen_map: dict[str, str] = {}
    if os.path.exists(seen_path):
        try:
            with open(seen_path, "r", encoding="utf-8") as f:
                seen_map = (json.load(f).get("urls") or {})
        except Exception as e:
            log(f"  讀 seen.json 失敗（視為空）：{e}")

    new_jobs: list[Job] = []
    for j in unique:
        j.category = categorize(j.title, j.company, j.description)
        if j.url and j.url in seen_map:
            j.first_seen = seen_map[j.url]
        else:
            j.first_seen = today
            if j.url:
                seen_map[j.url] = today
            new_jobs.append(j)

    # 排序 key：分類優先順序 → 薪資 → 上架日
    cat_index = {c["key"]: i for i, c in enumerate(CATEGORIES)}

    def sort_key(j: Job):
        return (
            cat_index.get(j.category, 99),
            -(j.salary_min or 0),
            -(int(j.posted_at.replace("-", "")) if j.posted_at else 0),
        )

    unique.sort(key=sort_key)
    new_jobs.sort(key=sort_key)

    generated_at = dt.datetime.now().isoformat(timespec="seconds")

    # 分類 summary（含全部 16 類、0 筆也保留，供前端顯示 empty tab）
    def summarize_by_category(js: list[Job]) -> list[dict]:
        counts = {c["key"]: 0 for c in CATEGORIES}
        for j in js:
            counts[j.category] = counts.get(j.category, 0) + 1
        return [
            {
                "key": c["key"], "label": c["label"],
                "emoji": c["emoji"], "color": c["color"],
                "count": counts[c["key"]],
            }
            for c in CATEGORIES
        ]

    payload = {
        "generated_at": generated_at,
        "params": {"days": days, "keyword": keyword, "salary_filter": salary_filter},
        "summary": {
            "total": len(unique),
            "new_today": len(new_jobs),
            "by_platform": {
                p: sum(1 for j in unique if j.platform == p)
                for p in ("104", "CakeResume", "Yourator")
            },
        },
        "categories": summarize_by_category(unique),
        "jobs": [asdict(j) for j in unique],
    }
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    new_payload = {
        "generated_at": generated_at,
        "total": len(new_jobs),
        "categories": summarize_by_category(new_jobs),
        "jobs": [asdict(j) for j in new_jobs],
    }
    os.makedirs(os.path.dirname(new_output) or ".", exist_ok=True)
    with open(new_output, "w", encoding="utf-8") as f:
        json.dump(new_payload, f, ensure_ascii=False, indent=2)

    os.makedirs(os.path.dirname(seen_path) or ".", exist_ok=True)
    with open(seen_path, "w", encoding="utf-8") as f:
        json.dump({"last_updated": generated_at, "urls": seen_map}, f,
                  ensure_ascii=False, indent=2)

    log(f"✅ 完成：全部 {len(unique)} 筆 / 新增 {len(new_jobs)} 筆")
    cat_counts = {c["key"]: c["count"] for c in payload["categories"]}
    top = sorted(cat_counts.items(), key=lambda kv: -kv[1])[:5]
    log(f"   前 5 類別：{top}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None,
                    help="只抓 N 天內上架；預設不過濾（抓全部開放中）")
    ap.add_argument("--keyword", default="實習")
    ap.add_argument("--salary-filter", action="store_true",
                    help="只保留有明確薪資（預設含面議）")
    ap.add_argument("--max-pages", type=int, default=8)
    ap.add_argument("--output", default="data/internships.json")
    ap.add_argument("--seen", default="data/seen.json")
    ap.add_argument("--new-output", default="data/new_today.json")
    args = ap.parse_args()

    run(
        days=args.days,
        keyword=args.keyword,
        salary_filter=args.salary_filter,
        max_pages=args.max_pages,
        output=args.output,
        seen_path=args.seen,
        new_output=args.new_output,
    )


if __name__ == "__main__":
    main()
