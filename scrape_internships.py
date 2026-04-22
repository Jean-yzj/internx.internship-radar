"""
實習招募資料爬蟲
抓取 104、CakeResume、Yourator 的最新實習職缺，
過濾「7 天內上架」+「有明確薪資」，輸出成 internships.json。

使用方式：
    pip install requests
    python scrape_internships.py

可選參數：
    --days N       只抓 N 天內上架的 (預設 7)
    --keyword 關鍵字   搜尋關鍵字 (預設「實習」)
    --no-salary-filter  不過濾掉面議職缺
    --output PATH  輸出路徑 (預設 internships.json)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any, Iterable

try:
    import requests
except ImportError:
    print("缺少 requests 套件，請先執行：pip install requests")
    sys.exit(1)


# ---------- 資料模型 ----------

@dataclass
class Job:
    platform: str          # "104" / "CakeResume" / "Yourator"
    title: str
    company: str
    location: str
    salary: str            # 原字串，例如 "月薪 35,000~45,000 元"
    salary_min: int | None # 月薪下限 (NTD)，時薪會換算成月薪 * 176 估算
    salary_type: str       # "monthly" / "hourly" / "negotiable" / "unknown"
    posted_at: str         # ISO 日期字串 YYYY-MM-DD
    url: str               # 完整職缺連結
    description: str = ""  # 簡短摘要


# ---------- 共用工具 ----------

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_salary(text: str) -> tuple[int | None, str]:
    """回傳 (月薪下限, salary_type)。無法解析時 salary_min 為 None。"""
    if not text:
        return None, "unknown"
    t = text.replace(",", "").replace(" ", "")
    if "面議" in t or "negotiable" in t.lower():
        return None, "negotiable"

    # 抓第一個數字
    nums = [int(n) for n in re.findall(r"\d+", t)]
    if not nums:
        return None, "unknown"
    first = nums[0]

    if "時薪" in t or "hourly" in t.lower() or "/hr" in t.lower():
        # 時薪估算月薪：176 小時/月 (台灣法定工時上限)
        return first * 176, "hourly"
    if "日薪" in t:
        return first * 22, "hourly"
    if "年薪" in t or "annual" in t.lower():
        return first // 12, "monthly"
    if "月薪" in t or "monthly" in t.lower() or first >= 10000:
        return first, "monthly"
    return None, "unknown"


def within_days(date_str: str, days: int) -> bool:
    """date_str: 'YYYY-MM-DD' 或 'YYYYMMDD'"""
    try:
        s = date_str.replace("-", "").replace("/", "")
        d = dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except Exception:
        return False
    return (dt.date.today() - d).days <= days


# ---------- 104 ----------

def fetch_104(keyword: str, max_pages: int = 3) -> list[Job]:
    """
    104 公開搜尋 API。
    重點 query 參數：
      keyword  關鍵字
      jobexp=1 工作經驗 1 年以下 (近似實習族群)
      order=16 依最新上架排序 (15=日期 16=更新日期)
      asc=0    遞減
      mode=s   搜尋模式
    """
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
            "ro": "0",
            "kwop": "7",
            "keyword": keyword,
            "expansionType": "area,spec,com,job,wf,wktm",
            "order": "16",
            "asc": "0",
            "page": str(page),
            "mode": "s",
            "jobsource": "2018indexpoc",
        }
        try:
            r = requests.get(base, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log(f"  page {page} 失敗：{e}")
            break

        items = (data.get("data") or {}).get("list") or []
        if not items:
            break

        for it in items:
            try:
                title = it.get("jobName", "").strip()
                company = it.get("custName", "").strip()
                location = (it.get("jobAddrNoDesc") or it.get("jobAddress") or "").strip()
                salary_raw = it.get("salaryDesc", "").strip()
                appear = it.get("appearDate", "")  # YYYYMMDD
                link = it.get("link", {}).get("job", "")
                if link.startswith("//"):
                    link = "https:" + link
                elif link.startswith("/"):
                    link = "https://www.104.com.tw" + link

                smin, stype = parse_salary(salary_raw)
                # 標準化日期
                if len(appear) == 8 and appear.isdigit():
                    posted = f"{appear[:4]}-{appear[4:6]}-{appear[6:8]}"
                else:
                    posted = ""

                # 篩實習
                if "實習" not in title and "intern" not in title.lower():
                    continue

                jobs.append(Job(
                    platform="104",
                    title=title,
                    company=company,
                    location=location,
                    salary=salary_raw,
                    salary_min=smin,
                    salary_type=stype,
                    posted_at=posted,
                    url=link,
                    description=(it.get("description") or "")[:200],
                ))
            except Exception as e:
                log(f"  解析 item 失敗：{e}")
                continue

        time.sleep(0.8)  # 禮貌間隔
    log(f"  104 取得 {len(jobs)} 筆")
    return jobs


# ---------- CakeResume (cake.me) ----------

def fetch_cakeresume(keyword: str, max_pages: int = 3) -> list[Job]:
    """
    CakeResume 改名為 Cake (cake.me)。
    公開 API：https://www.cake.me/api/v3/search/jobs
    篩選 employment_type = internship
    """
    log("→ 抓 CakeResume (Cake)...")
    jobs: list[Job] = []
    base = "https://www.cake.me/api/v3/search/jobs"
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.cake.me/jobs",
        "Accept": "application/json",
    }
    for page in range(1, max_pages + 1):
        params = {
            "query": keyword,
            "employment_type[]": "internship",
            "order": "latest",
            "page": str(page),
            "per_page": "24",
        }
        try:
            r = requests.get(base, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log(f"  page {page} 失敗：{e}")
            break

        items = data.get("items") or data.get("jobs") or data.get("data") or []
        if not items:
            break

        for it in items:
            try:
                title = (it.get("title") or it.get("name") or "").strip()
                company = (
                    (it.get("page") or {}).get("name")
                    or (it.get("company") or {}).get("name")
                    or ""
                ).strip()
                # 地點
                loc = it.get("location") or it.get("city") or ""
                if isinstance(loc, dict):
                    loc = loc.get("name") or loc.get("city") or ""
                location = str(loc).strip()

                # 薪資
                smin_raw = it.get("salary_min") or it.get("salaryMin")
                smax_raw = it.get("salary_max") or it.get("salaryMax")
                stype_raw = it.get("salary_type") or ""
                if smin_raw and smax_raw:
                    salary_raw = f"{smin_raw:,}-{smax_raw:,} ({stype_raw})"
                elif smin_raw:
                    salary_raw = f"{smin_raw:,}+ ({stype_raw})"
                else:
                    salary_raw = stype_raw or "面議"

                smin, stype = (int(smin_raw), "monthly") if (smin_raw and "month" in stype_raw.lower()) else parse_salary(salary_raw)

                # 日期
                posted = (it.get("published_at") or it.get("created_at") or "")[:10]

                # URL
                slug = it.get("path") or it.get("slug") or ""
                page_slug = (it.get("page") or {}).get("path") or ""
                if slug.startswith("http"):
                    url = slug
                elif page_slug and slug:
                    url = f"https://www.cake.me/companies/{page_slug}/jobs/{slug}"
                elif slug:
                    url = f"https://www.cake.me{slug if slug.startswith('/') else '/' + slug}"
                else:
                    url = "https://www.cake.me/jobs"

                jobs.append(Job(
                    platform="CakeResume",
                    title=title,
                    company=company,
                    location=location,
                    salary=salary_raw,
                    salary_min=smin,
                    salary_type=stype,
                    posted_at=posted,
                    url=url,
                    description=(it.get("description_plain_text") or it.get("description") or "")[:200],
                ))
            except Exception as e:
                log(f"  解析 item 失敗：{e}")
                continue

        time.sleep(0.8)
    log(f"  CakeResume 取得 {len(jobs)} 筆")
    return jobs


# ---------- Yourator ----------

def fetch_yourator(keyword: str, max_pages: int = 3) -> list[Job]:
    """
    Yourator 公開 API。
    https://www.yourator.co/api/v2/jobs?company_category[]=&category[]=internship&q[base]=實習
    """
    log("→ 抓 Yourator...")
    jobs: list[Job] = []
    base = "https://www.yourator.co/api/v2/jobs"
    headers = {
        "User-Agent": UA,
        "Referer": "https://www.yourator.co/jobs",
        "Accept": "application/json",
    }
    for page in range(1, max_pages + 1):
        params = {
            "term[base]": keyword,
            "term[exp]": "intern",
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

        items = data.get("payload") or data.get("jobs") or data.get("data") or []
        if not items:
            break

        for it in items:
            try:
                title = (it.get("name") or it.get("title") or "").strip()
                company_obj = it.get("company") or {}
                company = (company_obj.get("brand") or company_obj.get("name") or "").strip()
                location = (it.get("city") or it.get("location") or "").strip()

                smin_raw = it.get("salary_min")
                smax_raw = it.get("salary_max")
                stype_raw = (it.get("salary_type") or "").lower()
                if smin_raw:
                    salary_raw = f"{smin_raw:,}" + (f"-{smax_raw:,}" if smax_raw else "+")
                    salary_raw += f" ({stype_raw})"
                else:
                    salary_raw = "面議"
                smin, stype = (int(smin_raw), "monthly") if (smin_raw and "month" in stype_raw) else parse_salary(salary_raw)

                posted = (it.get("published_at") or it.get("created_at") or "")[:10]

                slug = it.get("path") or it.get("slug") or ""
                company_slug = company_obj.get("path") or company_obj.get("slug") or ""
                if slug.startswith("http"):
                    url = slug
                elif company_slug and slug:
                    url = f"https://www.yourator.co/companies/{company_slug}/jobs/{slug}"
                else:
                    url = "https://www.yourator.co/jobs"

                jobs.append(Job(
                    platform="Yourator",
                    title=title,
                    company=company,
                    location=location,
                    salary=salary_raw,
                    salary_min=smin,
                    salary_type=stype,
                    posted_at=posted,
                    url=url,
                    description=(it.get("description") or "")[:200],
                ))
            except Exception as e:
                log(f"  解析 item 失敗：{e}")
                continue

        time.sleep(0.8)
    log(f"  Yourator 取得 {len(jobs)} 筆")
    return jobs


# ---------- 主流程 ----------

def run(days: int, keyword: str, salary_filter: bool, output: str) -> None:
    all_jobs: list[Job] = []

    for fn in (fetch_104, fetch_cakeresume, fetch_yourator):
        try:
            all_jobs.extend(fn(keyword))
        except Exception as e:
            log(f"❌ {fn.__name__} 整個失敗：{e}")

    log(f"原始總數：{len(all_jobs)}")

    # 過濾
    filtered: list[Job] = []
    for j in all_jobs:
        if j.posted_at and not within_days(j.posted_at, days):
            continue
        if salary_filter and j.salary_type in ("negotiable", "unknown"):
            continue
        filtered.append(j)

    # 去重 (同 title + 同 company)
    seen = set()
    unique: list[Job] = []
    for j in filtered:
        key = (j.title, j.company, j.platform)
        if key in seen:
            continue
        seen.add(key)
        unique.append(j)

    # 排序：最新在前，其次薪資高的在前
    unique.sort(
        key=lambda j: (j.posted_at or "", j.salary_min or 0),
        reverse=True,
    )

    payload = {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "params": {
            "days": days,
            "keyword": keyword,
            "salary_filter": salary_filter,
        },
        "summary": {
            "total_raw": len(all_jobs),
            "total_after_filter": len(unique),
            "by_platform": {
                p: sum(1 for j in unique if j.platform == p)
                for p in ("104", "CakeResume", "Yourator")
            },
        },
        "jobs": [asdict(j) for j in unique],
    }

    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log(f"✅ 完成，共 {len(unique)} 筆寫入 {output}")
    log(f"   104={payload['summary']['by_platform']['104']}  "
        f"Cake={payload['summary']['by_platform']['CakeResume']}  "
        f"Yourator={payload['summary']['by_platform']['Yourator']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--keyword", default="實習")
    ap.add_argument("--no-salary-filter", action="store_true",
                    help="不過濾面議/未填薪資的職缺")
    ap.add_argument("--output", default="internships.json")
    args = ap.parse_args()

    run(
        days=args.days,
        keyword=args.keyword,
        salary_filter=not args.no_salary_filter,
        output=args.output,
    )


if __name__ == "__main__":
    main()
