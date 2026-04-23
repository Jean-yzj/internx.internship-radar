"""實習招募資料爬蟲

抓取 104、Yourator、CakeResume 目前平台上所有「實習」職缺，
依 categories.py 分類，輸出：

  data/internships.json  目前全部未截止的實習（供網站）
  data/new_today.json    這次跑才第一次看到的職缺（供 Discord）
  data/seen.json         去重／首見日／最後出現日

使用方式：
    pip install -r requirements.txt
    python scrape_internships.py

進階：
    --llm-categorize   用 Claude Haiku 重新分類（需 ANTHROPIC_API_KEY）
    --salary-filter    只保留有明確薪資
    --max-pages N      每平台抓 N 頁（預設 8）
    --days N           只留 N 天內上架（預設不過濾）
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

try:
    import requests
except ImportError:
    print("缺少 requests 套件，請先執行：pip install -r requirements.txt")
    sys.exit(1)

from categories import CATEGORIES, CATEGORY_BY_KEY, categorize
from skills import extract_skills
from eligibility import extract_eligibility


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
    last_seen: str = ""
    deadline: str = ""
    skills: list[str] = None  # type: ignore[assignment]
    eligibility: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.skills is None:
            self.skills = []
        if self.eligibility is None:
            self.eligibility = []


UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

SEEN_PRUNE_DAYS = 180


def log(msg: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------- 通用工具 ----------

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


# ---------- 截止日解析 ----------

# 常見 pattern：
#   "(Apply by 29 April)"
#   "03/15投遞截止"、"4/30 中午12點前截止"、"【4/30 截止】"
#   "截止日：2026/04/30"、"deadline: 2026-04-30"
#   "2026年4月30日 截止"
_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}

_DEADLINE_PATTERNS = [
    r"apply\s+by\s+(\d{1,2})\s+([A-Za-z]+)",                  # "Apply by 29 April"
    r"apply\s+by\s+([A-Za-z]+)\s+(\d{1,2})",                   # "Apply by April 29"
    r"deadline[:：\s]+([0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2})",  # "deadline: 2026-04-30"
    r"截止(?:日(?:期)?)?[:：\s]*([0-9]{4}[-/年][0-9]{1,2}[-/月][0-9]{1,2})",
    r"([0-9]{1,2}/[0-9]{1,2})\s*(?:中午)?(?:[0-9]{1,2}點)?(?:之前|前)?\s*(?:投遞)?截止",
    r"截止(?:日(?:期)?)?[:：\s]*([0-9]{1,2}/[0-9]{1,2})",
]


def _norm_date(y: int, m: int, d: int) -> str:
    try:
        return dt.date(y, m, d).isoformat()
    except Exception:
        return ""


def extract_deadline(text: str) -> str:
    """從任意文字找出截止日，回傳 YYYY-MM-DD；找不到回空字串。"""
    if not text:
        return ""
    s = text.lower()
    today = dt.date.today()

    # pattern 1: apply by 29 april
    m = re.search(r"apply\s+by\s+(\d{1,2})\s+([a-z]+)", s)
    if m:
        day, mon_name = int(m.group(1)), m.group(2)
        mon = _MONTH_NAMES.get(mon_name)
        if mon:
            year = today.year + (1 if mon < today.month - 3 else 0)
            return _norm_date(year, mon, day)

    # pattern 2: apply by april 29
    m = re.search(r"apply\s+by\s+([a-z]+)\s+(\d{1,2})", s)
    if m:
        mon_name, day = m.group(1), int(m.group(2))
        mon = _MONTH_NAMES.get(mon_name)
        if mon:
            year = today.year + (1 if mon < today.month - 3 else 0)
            return _norm_date(year, mon, day)

    # pattern 3: deadline: 2026-04-30 / 2026/4/30 / 截止｜2026/05/06
    m = re.search(
        r"(?:deadline|截止(?:日(?:期)?)?)[^\d]{0,4}(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})",
        s,
    )
    if m:
        return _norm_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # pattern 4: 03/15投遞截止 / 4/30 前截止 / 【4/30 中午12點前截止】
    m = re.search(r"(\d{1,2})/(\d{1,2})(?:[^/0-9]{0,10})?(?:中午|上午|下午|[0-9]+[:：][0-9]+|\d+點)?(?:[^截止]{0,10})?(?:投遞|之前|前)?\s*截止", text)
    if m:
        mon, day = int(m.group(1)), int(m.group(2))
        # 年份推斷：若月份已過 3 個月以上，視為明年
        year = today.year + (1 if mon < today.month - 3 else 0)
        return _norm_date(year, mon, day)

    # pattern 5: 截止: 4/30 / 截止日 4/30
    m = re.search(r"截止(?:日(?:期)?)?[:：\s]*(\d{1,2})/(\d{1,2})", text)
    if m:
        mon, day = int(m.group(1)), int(m.group(2))
        year = today.year + (1 if mon < today.month - 3 else 0)
        return _norm_date(year, mon, day)

    return ""


# ---------- 104 ----------

def fetch_104(keyword: str, max_pages: int) -> list[Job]:
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
                link = (it.get("link") or {}).get("job") or ""
                if link.startswith("//"):
                    link = "https:" + link
                elif link.startswith("/"):
                    link = "https://www.104.com.tw" + link
                smin, stype = parse_salary(salary_raw)
                posted = (f"{appear[:4]}-{appear[4:6]}-{appear[6:8]}"
                          if len(appear) == 8 and appear.isdigit() else "")
                desc = (it.get("description") or it.get("descSnippet") or "")[:200]
                deadline = extract_deadline(f"{title} {desc}")
                jobs.append(Job(
                    platform="104", title=title, company=company, location=location,
                    salary=salary_raw, salary_min=smin, salary_type=stype,
                    posted_at=posted, url=link, description=desc, deadline=deadline,
                ))
            except Exception as e:
                log(f"  解析 item 失敗：{e}")
        time.sleep(0.8)
    log(f"  104 取得 {len(jobs)} 筆")
    return jobs


# ---------- Yourator ----------

def fetch_yourator(keyword: str, max_pages: int) -> list[Job]:
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
                company_obj = it.get("company") or {}
                company = (company_obj.get("brand") or company_obj.get("name") or "").strip()
                location = (it.get("location") or "").strip()
                salary_raw = (it.get("salary") or "").strip() or "面議"
                smin, stype = parse_salary(salary_raw)
                path = it.get("path") or ""
                url = path if path.startswith("http") else (
                    f"https://www.yourator.co{path}" if path.startswith("/")
                    else "https://www.yourator.co/jobs"
                )
                tags = it.get("tags") or []
                desc = " / ".join(tags) if isinstance(tags, list) else ""
                deadline = extract_deadline(f"{title} {desc}")
                jobs.append(Job(
                    platform="Yourator", title=title, company=company, location=location,
                    salary=salary_raw, salary_min=smin, salary_type=stype,
                    posted_at="", url=url, description=desc[:200], deadline=deadline,
                ))
            except Exception as e:
                log(f"  解析 item 失敗：{e}")
        if not has_more:
            break
        time.sleep(0.8)
    log(f"  Yourator 取得 {len(jobs)} 筆")
    return jobs


# ---------- CakeResume (HTML scrape) ----------

def _cake_find_suffix(el, suffix: str):
    """找 class 後綴為 `suffix` 的子元素（CSS module hash 會變，用尾綴 match）。"""
    def _match(val):
        if not val:
            return False
        classes = val if isinstance(val, list) else [val]
        return any("JobSearchItem" in x and x.endswith(suffix) for x in classes)
    return el.find(class_=_match)


def fetch_cakeresume(keyword: str, max_pages: int) -> list[Job]:
    """爬 Cake /jobs HTML。

    Cake 的搜尋 API 已下架，HTML 靠 Next.js SSR 只輸出前 ~10 筆；
    pagination 要 client-side JS 才能拉更多。實務上用兩個入口拼湊：
      1) /jobs/internship  — 內建只放 intern 的頁面
      2) /jobs?q=<keyword> — 關鍵字搜尋
    重疊後約 20 筆不重覆 intern 職缺，作為 Cake 最低補強。
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log("  CakeResume 略過：缺 beautifulsoup4")
        return []
    log("→ 抓 CakeResume (HTML SSR)...")
    jobs: list[Job] = []
    base = "https://www.cake.me"
    headers = {"User-Agent": UA, "Accept": "text/html"}
    seen_urls: set[str] = set()

    entry_urls = [
        f"{base}/jobs/internship",
        f"{base}/jobs?q={requests.utils.quote(keyword)}",
    ]

    for url in entry_urls:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
        except Exception as e:
            log(f"  {url[-30:]} 失敗：{e}")
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.find_all(class_=lambda c: c and any(
            "JobSearchItem" in x and x.endswith("__container")
            for x in (c if isinstance(c, list) else [c])
        ))

        for card in cards:
            try:
                title_el = _cake_find_suffix(card, "__jobTitle")
                company_el = _cake_find_suffix(card, "__companyName")
                segments = _cake_find_suffix(card, "__featureSegments")
                content_el = _cake_find_suffix(card, "__content")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if "實習" not in title and "intern" not in title.lower():
                    continue
                job_href = ""
                for a in card.find_all("a", href=True):
                    h = a["href"]
                    if "/companies/" in h and "/jobs/" in h:
                        job_href = h
                        break
                if not job_href:
                    continue
                job_url = job_href if job_href.startswith("http") else base + job_href
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                company = company_el.get_text(strip=True) if company_el else ""
                seg_text = segments.get_text(separator=" · ", strip=True) if segments else ""
                content_text = (content_el.get_text(separator=" ", strip=True)[:200]
                                if content_el else "")
                salary_raw = "面議"
                smin, stype = parse_salary(salary_raw)
                deadline = extract_deadline(f"{title} {content_text}")
                jobs.append(Job(
                    platform="CakeResume", title=title, company=company,
                    location="", salary=salary_raw,
                    salary_min=smin, salary_type=stype,
                    posted_at="", url=job_url,
                    description=(seg_text + " · " + content_text).strip(" ·")[:200],
                    deadline=deadline,
                ))
            except Exception as e:
                log(f"  解析 card 失敗：{e}")
        time.sleep(0.7)

    log(f"  CakeResume 取得 {len(jobs)} 筆")
    return jobs


# ---------- LLM 分類（選用） ----------

def llm_categorize(jobs: list[Job]) -> int:
    """用 Claude Haiku 覆寫每筆 job 的 .category。成功返回已分類數；
    未設 API key 或失敗時不動原有 category，返回 0。
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return 0
    try:
        from anthropic import Anthropic
    except ImportError:
        log("  LLM 分類略過：缺 anthropic 套件")
        return 0

    log("→ 啟用 LLM 分類（Claude Haiku）...")
    client = Anthropic(api_key=api_key)

    cat_list = "\n".join(
        f"- {c['key']}: {c['label']}"
        for c in CATEGORIES if c["key"] != "other"
    )
    system_prompt = (
        "你是實習職缺分類器。看每一筆職缺的標題與公司，回傳最適合的 category key。\n"
        f"Category keys:\n{cat_list}\n"
        "- other: 無明確歸屬\n\n"
        "輸出規則：只回 JSON object，key 是編號字串，value 是 category key。\n"
        '範例輸入：\n1. Software Engineer Intern / Google\n2. 會計實習生 / 勤業眾信\n'
        '範例輸出：{"1":"tech","2":"accounting"}'
    )

    batch_size = 20
    changed = 0
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i:i + batch_size]
        user_content = "\n".join(
            f"{k+1}. {j.title} / {j.company}" for k, j in enumerate(batch)
        )
        try:
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            text = resp.content[0].text.strip()
            # 裁掉可能的 ```json ... ```
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
            result = json.loads(text)
            for k, j in enumerate(batch):
                key = result.get(str(k + 1))
                if key and key in CATEGORY_BY_KEY and key != j.category:
                    j.category = key
                    changed += 1
        except Exception as e:
            log(f"  LLM batch {i // batch_size} 失敗：{e}")
            continue
    log(f"  LLM 分類完成：{changed} 筆被重新歸類")
    return changed


# ---------- 主流程 ----------

def _load_seen(seen_path: str) -> dict[str, dict]:
    """載入 seen.json，相容舊格式 {url: date_str} 與新格式 {url: {first_seen, last_seen}}。"""
    if not os.path.exists(seen_path):
        return {}
    try:
        with open(seen_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    urls = raw.get("urls") or {}
    out: dict[str, dict] = {}
    for u, v in urls.items():
        if isinstance(v, str):
            out[u] = {"first_seen": v, "last_seen": v}
        elif isinstance(v, dict):
            out[u] = {
                "first_seen": v.get("first_seen", ""),
                "last_seen": v.get("last_seen", v.get("first_seen", "")),
            }
    return out


def generate_feed(jobs: list[Job], output_path: str, site_url: str = "https://internshipradar.zeabur.app") -> None:
    """輸出 Atom 1.0 feed（最多 30 筆最新），可被 RSS reader 訂閱。"""
    from html import escape
    # 最新的 first_seen 排前面
    sorted_jobs = sorted(
        jobs,
        key=lambda j: (j.first_seen or "", j.salary_min or 0),
        reverse=True,
    )[:30]
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    entries = []
    for j in sorted_jobs:
        title = escape(f"{j.title} · {j.company}")
        url = escape(j.url)
        fs = j.first_seen or dt.date.today().isoformat()
        updated = f"{fs}T00:00:00+08:00"
        category = escape(j.category)
        summary_parts = []
        if j.salary:
            summary_parts.append(f"薪資：{j.salary}")
        if j.location:
            summary_parts.append(f"地點：{j.location}")
        if j.deadline:
            summary_parts.append(f"截止：{j.deadline}")
        summary_parts.append(f"平台：{j.platform}")
        summary = escape(" · ".join(summary_parts))
        entries.append(
            f'  <entry>\n'
            f'    <title>{title}</title>\n'
            f'    <id>{url}</id>\n'
            f'    <link href="{url}" />\n'
            f'    <updated>{updated}</updated>\n'
            f'    <category term="{category}" />\n'
            f'    <summary>{summary}</summary>\n'
            f'  </entry>'
        )
    feed = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f'  <title>實習雷達</title>\n'
        f'  <subtitle>104 · CakeResume · Yourator 每日實習彙整</subtitle>\n'
        f'  <link href="{site_url}" rel="alternate" />\n'
        f'  <link href="{site_url}/data/feed.xml" rel="self" />\n'
        f'  <id>{site_url}/</id>\n'
        f'  <updated>{now}</updated>\n'
        + "\n".join(entries) + "\n"
        '</feed>\n'
    )
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(feed)


def _prune_seen(seen: dict[str, dict], today: dt.date) -> int:
    """移除 last_seen 超過 SEEN_PRUNE_DAYS 的項目。"""
    cutoff = today - dt.timedelta(days=SEEN_PRUNE_DAYS)
    to_drop = []
    for u, v in seen.items():
        ls = v.get("last_seen", "") or v.get("first_seen", "")
        try:
            d = dt.date.fromisoformat(ls)
            if d < cutoff:
                to_drop.append(u)
        except Exception:
            to_drop.append(u)  # malformed → drop
    for u in to_drop:
        del seen[u]
    return len(to_drop)


def run(
    days: int | None,
    keyword: str,
    salary_filter: bool,
    max_pages: int,
    output: str,
    seen_path: str,
    new_output: str,
    use_llm: bool,
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

    # 跨平台去重（URL 為主 key）
    seen_keys: set[tuple[str, ...]] = set()
    unique: list[Job] = []
    for j in filtered:
        key = (j.url,) if j.url else (j.title, j.company, j.platform)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(j)

    # 關鍵字分類（基本）
    for j in unique:
        j.category = categorize(j.title, j.company, j.description)
        j.skills = extract_skills(j.title, j.description)
        j.eligibility = extract_eligibility(j.title, j.description)

    # LLM 分類（可選，覆寫上面）
    if use_llm:
        llm_categorize(unique)

    # 更新 seen map（first_seen / last_seen）
    today = dt.date.today()
    today_iso = today.isoformat()
    seen_map = _load_seen(seen_path)
    pruned = _prune_seen(seen_map, today)
    if pruned:
        log(f"  seen.json 清理 {pruned} 筆過期 URL（>{SEEN_PRUNE_DAYS} 天未出現）")

    new_jobs: list[Job] = []
    for j in unique:
        if j.url and j.url in seen_map:
            j.first_seen = seen_map[j.url]["first_seen"]
            seen_map[j.url]["last_seen"] = today_iso
        else:
            j.first_seen = today_iso
            if j.url:
                seen_map[j.url] = {"first_seen": today_iso, "last_seen": today_iso}
            new_jobs.append(j)
        j.last_seen = today_iso

    # 排序 key：分類優先 → 薪資 → 上架日
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
        "params": {
            "days": days, "keyword": keyword, "salary_filter": salary_filter,
            "llm_categorized": use_llm,
        },
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

    # RSS / Atom feed
    feed_path = os.path.join(os.path.dirname(output) or ".", "feed.xml")
    try:
        generate_feed(unique, feed_path)
    except Exception as e:
        log(f"  feed.xml 產生失敗：{e}")

    log(f"✅ 完成：全部 {len(unique)} 筆 / 新增 {len(new_jobs)} 筆 / 分類法：{'LLM' if use_llm else 'keyword'}")
    deadline_count = sum(1 for j in unique if j.deadline)
    if deadline_count:
        log(f"   抓到截止日 {deadline_count} 筆")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--keyword", default="實習")
    ap.add_argument("--salary-filter", action="store_true")
    ap.add_argument("--max-pages", type=int, default=8)
    ap.add_argument("--output", default="data/internships.json")
    ap.add_argument("--seen", default="data/seen.json")
    ap.add_argument("--new-output", default="data/new_today.json")
    ap.add_argument("--llm-categorize", action="store_true",
                    help="改用 Claude Haiku 分類（需 ANTHROPIC_API_KEY 環境變數）")
    args = ap.parse_args()

    run(
        days=args.days,
        keyword=args.keyword,
        salary_filter=args.salary_filter,
        max_pages=args.max_pages,
        output=args.output,
        seen_path=args.seen,
        new_output=args.new_output,
        use_llm=args.llm_categorize,
    )


if __name__ == "__main__":
    main()
