import os
import re
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Post:
    date: str
    time: str
    text: str
    likes: int
    replies: int = 0
    link: str = ""
    mentioned_stocks: list[str] = field(default_factory=list)


def get_next_week_info():
    existing = [f for f in os.listdir(".") if re.match(r"^week\d+\.md$", f)]
    if not existing:
        week_num = 1
    else:
        nums = [int(re.search(r"\d+", f).group()) for f in existing]
        week_num = max(nums) + 1

    today = date.today()
    if today.weekday() == 6:
        # Sunday: report covers the week that just ended
        sunday = today - timedelta(days=1)
        monday = sunday - timedelta(days=6)
    else:
        # Mon-Sat: report covers the current week
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)

    return week_num, monday, sunday


def format_date(d: date) -> str:
    return f"{d.month}月{d.day}日"


def extract_stocks(text: str) -> list[str]:
    return re.findall(r"\$[A-Z]{1,6}(?:\.[A-Z]{1,3})?", text)


def generate_report(posts: list[Post], week_num: int, monday: date, sunday: date) -> str:
    """Generate markdown weekly report from post data."""

    # Filter: long-form original posts only, >= 400 likes
    long_posts = [p for p in posts if len(p.text) >= 100 and p.likes >= 400]
    long_posts.sort(key=lambda p: p.time, reverse=True)

    # Collect all mentioned stocks
    all_stocks = set()
    for p in long_posts:
        all_stocks.update(extract_stocks(p.text))
        all_stocks.update(p.mentioned_stocks)

    # Build company focus table
    company_rows = _build_company_table(long_posts)

    # Build post list table
    post_rows = _build_post_table(long_posts)

    date_range = f"{format_date(monday)} – {format_date(sunday)}"

    md = f"""# @aleabitoreddit (Serenity) 周报 #{week_num}

**时间：{date_range}**

---

## 一、本周总述

<!-- TODO: 手动补充或 AI 生成 -->

---

## 二、重点关注公司

{company_rows}

---

## 三、下周展望

<!-- TODO: 手动补充或 AI 生成 -->

---

## 四、本周高赞贴文（≥400 赞）

{post_rows}

---

> ⚠️ 以上为对 @aleabitoreddit 公开帖子的客观总结，不构成投资建议。NFA。
"""
    return md


def _build_company_table(posts: list[Post]) -> str:
    """Build markdown table of key companies mentioned."""
    stock_posts: dict[str, list[Post]] = {}
    for p in posts:
        stocks = set(extract_stocks(p.text))
        stocks.update(p.mentioned_stocks)
        for s in stocks:
            if s not in stock_posts:
                stock_posts[s] = []
            stock_posts[s].append(p)

    if not stock_posts:
        return "| 公司 | 代码 | 提及次数 |\n|------|------|----------|\n| — | — | — |\n"

    rows = []
    for stock, ps in sorted(stock_posts.items(), key=lambda x: -len(x[1])):
        samples = [p.text[:80].replace("\n", " ") for p in ps[:2]]
        note = " | ".join(samples)
        rows.append(f"| — | {stock} | {len(ps)} | {note} |")

    header = "| 公司 | 代码 | 提及次数 | 本周观点摘要 |\n|------|------|----------|-------------|\n"
    return header + "\n".join(rows)


def _build_post_table(posts: list[Post]) -> str:
    """Build markdown table of posts."""
    header = "| 日期 | 内容摘要 | 提及公司 | 赞数 | 回复 | 链接 |\n|------|---------|---------|------|------|------|\n"

    rows = []
    for p in posts:
        stocks = set(extract_stocks(p.text))
        stocks.update(p.mentioned_stocks)
        stock_str = ", ".join(sorted(stocks)[:8]) if stocks else "—"
        summary = p.text[:100].replace("\n", " ").replace("|", "\\|")
        likes_str = f"~{p.likes}" if p.likes % 100 == 0 else str(p.likes)
        replies_str = str(p.replies) if p.replies else "—"
        link_str = f"[链接]({p.link})" if p.link else "—"
        rows.append(
            f"| {p.date} | {summary} | {stock_str} | {likes_str} | {replies_str} | {link_str} |"
        )

    return header + "\n".join(rows)


def write_report(md_content: str, week_num: int) -> str:
    filename = f"week{week_num}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(md_content)
    return filename


# ============================================================
# Dry-run test with sample data
# ============================================================

if __name__ == "__main__":
    week_num, monday, sunday = get_next_week_info()
    print(f"Week #{week_num}: {monday} → {sunday}")

    # Sample posts for testing
    sample_posts = [
        Post(
            date="2026-06-01",
            time="2026-06-01T10:00:00Z",
            text="$SIVE earnings confirmed the CPO supercycle thesis. 77% pipeline growth QoQ. This is the clearest signal yet.",
            likes=1604,
            replies=89,
            link="https://x.com/aleabitoreddit/status/example1",
            mentioned_stocks=["$SIVE"],
        ),
        Post(
            date="2026-06-02",
            time="2026-06-02T14:00:00Z",
            text="Foxconn shareholder meeting: CPO switches begin Q3 mass production. Shunsin (6451) is the key subsidiary. $AAOI positioned well.",
            likes=920,
            replies=45,
            link="https://x.com/aleabitoreddit/status/example2",
            mentioned_stocks=["$AAOI"],
        ),
        Post(
            date="2026-06-01",
            time="2026-06-01T08:00:00Z",
            text="Just hit 550K followers. Thank you all. Free research is winning.",
            likes=2100,
            replies=156,
            link="https://x.com/aleabitoreddit/status/example3",
        ),
        Post(
            date="2026-06-03",
            time="2026-06-03T12:00:00Z",
            text="Short reply lol",
            likes=1500,
            replies=10,
            link="https://x.com/aleabitoreddit/status/example4",
        ),
        Post(
            date="2026-06-02",
            time="2026-06-02T09:00:00Z",
            text="$MU at $1.2T now. The memory super-cycle is real. $NVDA demand pulling everything up. $SNDK and $WDC next.",
            likes=880,
            replies=62,
            link="https://x.com/aleabitoreddit/status/example5",
            mentioned_stocks=["$MU", "$NVDA", "$SNDK", "$WDC"],
        ),
    ]

    md = generate_report(sample_posts, week_num, monday, sunday)
    filename = write_report(md, week_num)
    print(f"Generated: {filename}")
    print("--- Preview (first 500 chars) ---")
    print(md[:500])
