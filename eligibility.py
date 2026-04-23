"""從職缺 title + description 抽取「可投遞年級」。

台灣實習常見的年級表達：
  - 大一 / 大二 / 大三 / 大四 / 大五
  - 研究所 / 碩士 / 碩一 / 碩二 / 博士
  - 不限年級 / 大學生 / 在學中
  - 應屆畢業生
  - "大三以上 / 大三（含）以上" → 展開成 大三, 大四, 研究所
"""

from __future__ import annotations

import re


GRADES_ORDERED = ["大一", "大二", "大三", "大四", "大五", "研究所"]


# 各年級對應的 regex 模式
_GRADE_PATTERNS = {
    "大一": [r"大一", r"freshman"],
    "大二": [r"大二", r"sophomore"],
    "大三": [r"大三", r"junior"],
    "大四": [r"大四", r"senior"],
    "大五": [r"大五"],
    "研究所": [r"研究所", r"碩士", r"碩一", r"碩二", r"grad(?:uate)?", r"master"],
    "博士": [r"博士", r"ph\.?d"],
    "應屆": [r"應屆(?:畢業)?生?", r"new grad", r"fresh grad"],
    "不限": [r"不限年級", r"大學生", r"在學(?:生|中)", r"undergrad"],
}

# 「以上」型 — 匹配到「大三以上」會展開
_ABOVE_PATTERNS = [
    (r"大一(?:\s*\(含\))?\s*以上", ["大一", "大二", "大三", "大四", "大五", "研究所"]),
    (r"大二(?:\s*\(含\))?\s*以上", ["大二", "大三", "大四", "大五", "研究所"]),
    (r"大三(?:\s*\(含\))?\s*以上", ["大三", "大四", "大五", "研究所"]),
    (r"大四(?:\s*\(含\))?\s*以上", ["大四", "大五", "研究所"]),
]


def extract_eligibility(title: str, description: str) -> list[str]:
    """回傳有序的年級清單；若匹配到「不限」優先回 ['不限']。"""
    hay = f"{title or ''} {description or ''}".lower()

    # 1) 若出現「不限年級 / 大學生」→ 就不詳列
    for p in _GRADE_PATTERNS["不限"]:
        if re.search(p, hay, re.I):
            return ["不限"]

    found: set[str] = set()

    # 2) 先處理「以上」
    for pat, grades in _ABOVE_PATTERNS:
        if re.search(pat, hay, re.I):
            found.update(grades)

    # 3) 再處理單獨出現的年級
    for grade, patterns in _GRADE_PATTERNS.items():
        if grade in ("不限", "應屆", "博士"):
            continue
        for p in patterns:
            if re.search(p, hay, re.I):
                found.add(grade)
                break

    # 4) 應屆 / 博士 獨立處理
    for p in _GRADE_PATTERNS["應屆"]:
        if re.search(p, hay, re.I):
            found.add("應屆")
            break
    for p in _GRADE_PATTERNS["博士"]:
        if re.search(p, hay, re.I):
            found.add("博士")
            break

    # 排序：大一 → 大二 → ... → 研究所 → 博士 → 應屆
    def sort_key(g):
        order = {
            "大一": 0, "大二": 1, "大三": 2, "大四": 3, "大五": 4,
            "研究所": 5, "博士": 6, "應屆": 7,
        }
        return order.get(g, 99)
    return sorted(found, key=sort_key)


def format_eligibility(grades: list[str]) -> str:
    """把年級清單格式化成人類讀得懂的短字串。"""
    if not grades:
        return ""
    if grades == ["不限"]:
        return "🎓 不限年級"
    # 連續的本科年級 → 用「以上」
    ug_grades = [g for g in grades if g in GRADES_ORDERED]
    other = [g for g in grades if g not in GRADES_ORDERED]
    display_parts = []
    if ug_grades:
        # 如果全本科 + 研究所 都有，簡化為「大X 以上」
        idxs = [GRADES_ORDERED.index(g) for g in ug_grades]
        if idxs and "研究所" in ug_grades and idxs[0] < 5:
            min_grade = GRADES_ORDERED[min(idxs)]
            display_parts.append(f"{min_grade}以上")
        elif len(ug_grades) > 1:
            display_parts.append("/".join(ug_grades))
        else:
            display_parts.append(ug_grades[0])
    display_parts.extend(other)
    return "🎓 " + "、".join(display_parts)
