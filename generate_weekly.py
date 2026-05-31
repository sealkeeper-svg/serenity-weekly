import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import date, timedelta
from dataclasses import dataclass, field


@dataclass
class Post:
    date: str
    time: str
    text: str
    likes: int
    replies: int = 0
    link: str = ""
    mentioned_stocks: list[str] = field(default_factory=list)


CHROME_PROFILE = r"C:\Temp\chrome-debug-profile"
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"


def bu(*args: str, timeout: int = 30) -> str:
    """Run a browser-use CLI command. Returns stdout as string."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONLEGACYWINDOWSSTDIO": "utf-8"}
    cmd = ["browser-use"] + list(args)
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        env=env,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 and result.stderr:
        print(f"  [warn] browser-use: {result.stderr.strip()[:200]}")
    return result.stdout or ""


def get_next_week_info(week_num: int | None = None):
    existing = [f for f in os.listdir(".") if re.match(r"^week\d+\.md$", f)]
    if not existing:
        target_week = 1
    elif week_num is not None:
        target_week = week_num
    else:
        nums = sorted(int(re.search(r"\d+", f).group()) for f in existing)
        # Find first gap, or take max+1
        target_week = nums[0]
        for i, n in enumerate(nums):
            expected = nums[0] + i
            if n != expected:
                target_week = expected
                break
        else:
            target_week = nums[-1] + 1

    today = date.today()
    if today.weekday() == 6:
        sunday = today - timedelta(days=1)
        monday = sunday - timedelta(days=6)
    else:
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)

    return target_week, monday, sunday


def format_date(d: date) -> str:
    return f"{d.month}月{d.day}日"


def ensure_chrome_running() -> bool:
    try:
        urllib.request.urlopen(urllib.request.Request(f"{CDP_URL}/json/version"), timeout=3)
        print("[Chrome] CDP already running")
        return True
    except Exception:
        pass

    print("[Chrome] Starting Chrome with debug port...")
    subprocess.Popen(
        [CHROME_PATH, f"--remote-debugging-port={CDP_PORT}", f"--user-data-dir={CHROME_PROFILE}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    for i in range(30):
        time.sleep(1)
        try:
            urllib.request.urlopen(urllib.request.Request(f"{CDP_URL}/json/version"), timeout=2)
            print("[Chrome] CDP ready")
            return True
        except Exception:
            if i % 5 == 4:
                print(f"  waiting... ({i+1}s)")

    print("[Chrome] ERROR: Chrome failed to start within 30s")
    return False


# Simplified scrape JS – avoids complex escaping
SCRAPE_JS = (
    "(() => { const posts = [];"
    "document.querySelectorAll('article[data-testid=\"tweet\"]').forEach(t => {"
    "try {"
    "const text = t.querySelector('[data-testid=\"tweetText\"]')?.innerText || '';"
    "const time = t.querySelector('time')?.getAttribute('datetime') || '';"
    "const link = t.querySelector('a[href*=\"/status/\"]')?.href || '';"
    "const labels = [...t.querySelectorAll('[aria-label]')].map(e => e.getAttribute('aria-label')).join('|');"
    "const lm = labels.match(/([0-9,]+)\\s*(?:Likes|Like)/);"
    "const rm = labels.match(/([0-9,]+)\\s*(?:Replies|Reply)/);"
    "posts.push({time, text: text.substring(0, 500),"
    "likes: lm ? parseInt(lm[1].replace(/,/g, '')) : 0,"
    "replies: rm ? parseInt(rm[1].replace(/,/g, '')) : 0, link});"
    "} catch(e) {}"
    "}); return JSON.stringify(posts); })()"
)


def scrape_weekly_posts(monday: date, sunday: date) -> list[Post]:
    all_posts: list[Post] = []

    print("[Scraper] Opening profile...")
    out = bu("--cdp-url", CDP_URL, "open", "https://x.com/aleabitoreddit", timeout=20)
    time.sleep(1.5)

    print("[Scraper] Scrolling and extracting...")
    out_of_range_count = 0
    for round_num in range(15):
        raw = bu("eval", SCRAPE_JS, timeout=60)
        try:
            batch = _parse_raw_batch(raw)
            if not batch:
                print(f"  [warn] Empty batch at round {round_num}")
            else:
                in_range = [item for item in batch if item.get("time", "")[:10] >= str(monday)]
                out_of_range = [item for item in batch if item.get("time", "")[:10] < str(monday)]
                all_posts.extend(_to_posts(batch))
                print(f"  round {round_num}: {len(in_range)} in-range, {len(out_of_range)} old (latest: {batch[0].get('time', '')[:10]})")
                if out_of_range and len(in_range) == 0:
                    out_of_range_count += 1
                    if out_of_range_count >= 2:
                        print(f"[Scraper] Reached end of target week after {round_num + 1} rounds.")
                        break
                else:
                    out_of_range_count = 0
        except Exception as e:
            print(f"  [warn] Parse error round {round_num}: {e}")

        # Scroll page by page to trigger lazy loading
        bu("scroll", "down", "--amount", "2000", timeout=10)
        time.sleep(1.5)
        bu("scroll", "down", "--amount", "2000", timeout=10)
        time.sleep(1.5)

    all_posts = _dedupe(all_posts)
    all_posts = [p for p in all_posts if str(monday) <= p.date <= str(sunday)]
    print(f"[Scraper] Done. {len(all_posts)} posts in range.")
    return all_posts


def _parse_raw_batch(raw: str) -> list[dict]:
    raw = raw.strip()
    if raw.startswith("result:"):
        raw = raw.split("result:", 1)[1].strip()
    if not raw:
        return []
    return json.loads(raw)


def _to_posts(items: list[dict]) -> list[Post]:
    posts = []
    for item in items:
        text = (item.get("text") or "").strip()
        ts = (item.get("time") or "").strip()
        if not text or not ts:
            continue
        posts.append(Post(
            date=ts[:10], time=ts, text=text,
            likes=item.get("likes") or 0,
            replies=item.get("replies") or 0,
            link=item.get("link", ""),
        ))
    return posts


def _dedupe(posts: list[Post]) -> list[Post]:
    seen: dict[str, Post] = {}
    for p in posts:
        key = p.link or p.text[:80]
        if key not in seen or (p.likes or 0) > (seen[key].likes or 0):
            seen[key] = p
    return list(seen.values())


def extract_stocks(text: str) -> list[str]:
    return re.findall(r"\$[A-Z]{1,6}(?:\.[A-Z]{1,3})?", text)


def _generate_summary(posts: list[Post], monday: date, sunday: date) -> str:
    """Generate a data-driven summary paragraph from top posts."""
    if not posts:
        return "本周暂无数据。"

    stock_counts: dict[str, int] = {}
    for p in posts:
        for s in set(extract_stocks(p.text)) | set(p.mentioned_stocks):
            stock_counts[s] = stock_counts.get(s, 0) + 1

    top_stocks = sorted(stock_counts.items(), key=lambda x: -x[1])[:5]
    top_texts = [p.text for p in posts[:5]]

    # Find the highest-likes post
    best = max(posts, key=lambda p: p.likes)
    total_posts = len(posts)
    total_likes = sum(p.likes for p in posts)
    date_range = f"{format_date(monday)} – {format_date(sunday)}"

    stock_str = "、".join(f"{s}（{c}次）" for s, c in top_stocks)

    return (
        f"本周（{date_range}）Serenity 共发布 {total_posts} 条高赞分析帖，"
        f"累计获得 {total_likes:,} 赞。"
        f"核心关注板块为 CPO 光子学与 AI 半导体供应链，"
        f"提及最多的股票：{stock_str}。"
        f"单帖最高赞 {best.likes:,}（{best.date}），"
        f"主题：{best.text[:80]}..."
    )


def _generate_outlook(posts: list[Post]) -> str:
    """Generate outlook from late-week posts."""
    if not posts:
        return "暂无展望数据。"

    # Focus on posts from the last 2 days
    late_posts = sorted(posts, key=lambda p: p.time, reverse=True)[:5]

    stocks = set()
    themes = []
    for p in late_posts:
        stocks.update(extract_stocks(p.text))
        if "earnings" in p.text.lower() or "财报" in p.text:
            themes.append("财报后续市场反应")
        if "CHIPS" in p.text or "chips act" in p.text.lower():
            themes.append("CHIPS Act 政策进展")
        if "CPO" in p.text or "photonics" in p.text.lower():
            themes.append("CPO/光子学供应链动态")

    if not themes:
        themes = ["继续关注 CPO 光子学产业链消息", "跟踪半导体财报和产能扩张信号"]

    stock_list = "、".join(sorted(stocks)[:6]) if stocks else "—"
    return f"重点关注：{stock_list}。预期方向：{'；'.join(themes[:4])}。"


def generate_report(posts: list[Post], week_num: int, monday: date, sunday: date) -> str:
    long_posts = [p for p in posts if len(p.text) >= 100 and p.likes >= 400]
    long_posts.sort(key=lambda p: p.time, reverse=True)

    summary = _generate_summary(long_posts, monday, sunday)
    outlook = _generate_outlook(long_posts)
    company_rows = _build_company_table(long_posts)
    post_rows = _build_post_table(long_posts)
    date_range = f"{format_date(monday)} – {format_date(sunday)}"

    return f"""# @aleaborteddit (Serenity) 周报 #{week_num}

**时间：{date_range}**

---

## 一、本周总述

{summary}

---

## 二、重点关注公司

{company_rows}

---

## 三、下周展望

{outlook}

---

## 四、本周高赞贴文（≥400 赞）

{post_rows}

---

> ⚠️ 以上为对 @aleaborteddit 公开帖子的客观总结，不构成投资建议。NFA。
"""


def _build_company_table(posts: list[Post]) -> str:
    stock_posts: dict[str, list[Post]] = {}
    for p in posts:
        for s in set(extract_stocks(p.text)) | set(p.mentioned_stocks):
            stock_posts.setdefault(s, []).append(p)

    if not stock_posts:
        return "| 公司 | 代码 | 提及次数 |\n|------|------|----------|\n| — | — | — |\n"

    header = "| 公司 | 代码 | 提及次数 | 本周观点摘要 |\n|------|------|----------|-------------|\n"
    rows = []
    for stock, ps in sorted(stock_posts.items(), key=lambda x: -len(x[1])):
        samples = [p.text[:80].replace("\n", " ") for p in ps[:2]]
        rows.append(f"| — | {stock} | {len(ps)} | {' | '.join(samples)} |")
    return header + "\n".join(rows)


def _build_post_table(posts: list[Post]) -> str:
    header = "| 日期 | 内容摘要 | 提及公司 | 赞数 | 回复 | 链接 |\n|------|---------|---------|------|------|------|\n"
    rows = []
    for p in posts:
        stocks = set(extract_stocks(p.text)) | set(p.mentioned_stocks)
        stock_str = ", ".join(sorted(stocks)[:8]) if stocks else "—"
        summary = p.text[:100].replace("\n", " ").replace("|", "\\|")
        likes_str = f"~{p.likes}" if p.likes % 100 == 0 else str(p.likes)
        replies_str = str(p.replies) if p.replies else "—"
        link_str = f"[链接]({p.link})" if p.link else "—"
        rows.append(f"| {p.date} | {summary} | {stock_str} | {likes_str} | {replies_str} | {link_str} |")
    return header + "\n".join(rows)


def write_report(md_content: str, week_num: int) -> str:
    filename = f"week{week_num}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(md_content)
    return filename


def _git_push(filename: str, week_num: int, monday: date, sunday: date):
    date_range = f"{format_date(monday)} – {format_date(sunday)}"
    cmds = [
        f'git add "{filename}"',
        f'git commit -m "week{week_num}: 周报 #{week_num} ({date_range})"',
        "git push origin master",
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0 and "nothing to commit" not in result.stderr:
            print(f"  [warn] git: {result.stderr.strip()[:200]}")
    print(f"[Git] Pushed {filename} to GitHub")


def main(dry_run: bool = False):
    week_num, monday, sunday = get_next_week_info()
    print(f"Week #{week_num}: {monday} → {sunday}")

    if not ensure_chrome_running():
        print("FATAL: Chrome not available")
        sys.exit(1)

    posts = scrape_weekly_posts(monday, sunday)
    if not posts:
        print("No posts found for this week. Exiting.")
        return

    md = generate_report(posts, week_num, monday, sunday)
    filename = write_report(md, week_num)
    print(f"Generated: {filename} ({len(posts)} posts)")

    if not dry_run:
        _git_push(filename, week_num, monday, sunday)
    else:
        print("[dry-run] Skipping git push")


def catch_up():
    """Generate reports for all missing weeks since week1."""
    existing = sorted(
        [int(re.search(r"\d+", f).group()) for f in os.listdir(".")
         if re.match(r"^week\d+\.md$", f)]
    )
    if not existing:
        print("No existing weeks found. Generating week1.")
        main(dry_run="--dry-run" in sys.argv)
        return

    # Find gaps
    missing = []
    for i in range(existing[0], existing[-1] + 1):
        if i not in existing:
            missing.append(i)

    if not missing:
        print(f"All weeks present: {existing}")
        return

    print(f"Missing weeks: {missing}")
    for week_num in missing:
        print(f"\n=== Generating week{week_num} ===")
        wnum, monday, sunday = get_next_week_info(week_num=week_num)
        if not ensure_chrome_running():
            print("Chrome not available, stopping.")
            break
        posts = scrape_weekly_posts(monday, sunday)
        if not posts:
            print(f"No posts for week{week_num}, skipping.")
            continue
        md = generate_report(posts, wnum, monday, sunday)
        filename = write_report(md, wnum)
        print(f"Generated {filename}")
        if "--dry-run" not in sys.argv:
            _git_push(filename, wnum, monday, sunday)


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    catchup = "--catch-up" in sys.argv

    if dry:
        print("[dry-run mode]")
    if catchup:
        catch_up()
    else:
        main(dry_run=dry)
