"""從職缺 title + description 抽取常見技能 tag。

使用字邊界正則避免誤判（如 "ai" 誤配 "main"）；中文詞直接子字串。
列表精簡到大學生實習常見的 30 個左右，寧漏不錯。
"""

from __future__ import annotations

import re


# label → list of regex patterns（大小寫不敏感、multi-line 模式）
SKILLS_KEYWORDS: dict[str, list[str]] = {
    # --- 程式語言 ---
    "Python": [r"\bpython\b"],
    "JavaScript": [r"\bjavascript\b", r"\bjs(?!on)\b"],
    "TypeScript": [r"\btypescript\b"],
    "Java": [r"\bjava\b(?!\s*script)"],
    "C++": [r"c\+\+"],
    "Go": [r"\bgolang\b", r"\bgo\s*語言"],
    "SQL": [r"\bsql\b"],
    # --- Web 框架 ---
    "React": [r"\breact(?!ive)\b"],
    "Vue": [r"\bvue(\.?js)?\b"],
    "Next.js": [r"\bnext\.?js\b"],
    "Node.js": [r"\bnode\.?js\b"],
    "Django": [r"\bdjango\b"],
    "Flask": [r"\bflask\b"],
    # --- 資料 / ML ---
    "TensorFlow": [r"\btensorflow\b"],
    "PyTorch": [r"\bpytorch\b"],
    "Pandas": [r"\bpandas\b"],
    "Tableau": [r"\btableau\b"],
    "Power BI": [r"\bpower\s*bi\b"],
    # --- Cloud / DevOps ---
    "AWS": [r"\baws\b"],
    "GCP": [r"\bgcp\b", r"google\s*cloud"],
    "Azure": [r"\bazure\b"],
    "Docker": [r"\bdocker\b"],
    "Kubernetes": [r"\bkubernetes\b", r"\bk8s\b"],
    # --- Mobile ---
    "iOS": [r"\bios\s*(?:開發|development|engineer|工程)"],
    "Android": [r"\bandroid\s*(?:開發|development|engineer|工程)"],
    "Flutter": [r"\bflutter\b"],
    "Swift": [r"\bswift(?:ui)?\b"],
    "Kotlin": [r"\bkotlin\b"],
    # --- 設計 ---
    "Figma": [r"\bfigma\b"],
    "Photoshop": [r"\bphotoshop\b", r"\bps\s*軟體"],
    "Illustrator": [r"\billustrator\b"],
    # --- 行銷 ---
    "SEO": [r"\bseo\b"],
    "SEM": [r"\bsem\b"],
    "GA": [r"google\s*analytics", r"\bga4\b"],
    # --- 辦公軟體 ---
    "Excel": [r"\bexcel\b"],
    "PowerPoint": [r"\bpowerpoint\b"],
    # --- 語言能力 ---
    "英文": [r"英文", r"\benglish\b", r"\btoeic\b", r"\btoefl\b", r"\bielts\b"],
    "日文": [r"日文", r"\bjapanese\b", r"\bjlpt\b"],
    # --- Finance ---
    "Bloomberg": [r"\bbloomberg\b"],
}


_COMPILED: dict[str, list[re.Pattern]] = {
    label: [re.compile(p, re.I) for p in patterns]
    for label, patterns in SKILLS_KEYWORDS.items()
}


def extract_skills(title: str, description: str) -> list[str]:
    """回傳命中的 skill 標籤清單，按 SKILLS_KEYWORDS 順序排序。"""
    hay = f"{title or ''} {description or ''}"
    found: list[str] = []
    for label, patterns in _COMPILED.items():
        if any(p.search(hay) for p in patterns):
            found.append(label)
    return found
