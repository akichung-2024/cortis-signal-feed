
import json
import re
import hashlib
import html
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET

from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

OUTPUT = Path("feed.json")
MAX_ITEMS = 80
MAX_AGE_DAYS = 30

MEMBERS = {
    "MARTIN": ["MARTIN", "마틴", "馬丁", "マーティン"],
    "JAMES": ["JAMES", "제임스", "詹姆斯", "ジェームス"],
    "JUHOON": ["JUHOON", "주훈", "朱勳", "ジュフン"],
    "SEONGHYEON": ["SEONGHYEON", "성현", "成賢", "ソンヒョン"],
    "KEONHO": ["KEONHO", "건호", "建豪", "ゴンホ"],
}

GROUP_NAMES = [
    "CORTIS", "코르티스", "コルティス", "考蒂斯"
]

SEARCHES = [
    ("CORTIS Kpop", "en-US", "US", "US:en"),
    ('"CORTIS" "BIGHIT"', "en-US", "US", "US:en"),
    ("코르티스", "ko", "KR", "KR:ko"),
    ("CORTIS コルティス", "ja", "JP", "JP:ja"),
    ("CORTIS 韓團", "zh-TW", "TW", "TW:zh-Hant"),
    ('"CORTIS" "JAMES"', "en-US", "US", "US:en"),
    ('"CORTIS" "JUHOON"', "en-US", "US", "US:en"),
    ('"CORTIS" "MARTIN"', "en-US", "US", "US:en"),
    ('"CORTIS" "SEONGHYEON"', "en-US", "US", "US:en"),
    ('"CORTIS" "KEONHO"', "en-US", "US", "US:en"),
]

def clean(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def fetch_rss(query, hl, gl, ceid):
    params = urllib.parse.urlencode({
        "q": query,
        "hl": hl,
        "gl": gl,
        "ceid": ceid,
    })
    url = "https://news.google.com/rss/search?" + params

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 CORTIS-SIGNAL/1.0",
            "Accept": "application/rss+xml, application/xml, text/xml",
        },
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read()

    root = ET.fromstring(data)
    return root.findall("./channel/item")

def get_text(node, tag):
    element = node.find(tag)
    return clean(element.text if element is not None else "")

def parse_date(value):
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None

def identify_members(title, description):
    # 優先依新聞標題辨識成員，避免把
    # 內文列出的五位成員都當作新聞主角。
    title_upper = title.upper()
    found = []

    for member, aliases in MEMBERS.items():
        for alias in aliases:
            if alias.isascii():
                pattern = r"(?<![A-Z])" + re.escape(alias) + r"(?![A-Z])"
                matched = re.search(pattern, title_upper)
            else:
                matched = alias in title

            if matched:
                found.append(member)
                break

    return found or ["GROUP"]

def is_relevant(title, description):
    content = (title + " " + description).upper()

    if any(name.upper() in content for name in GROUP_NAMES):
        return True

    return False

def read_existing():
    if not OUTPUT.exists():
        return []

    try:
        data = json.loads(OUTPUT.read_text(encoding="utf-8"))
        items = data.get("items", [])
        return items if isinstance(items, list) else []
    except (OSError, ValueError, TypeError):
        return []

def normalize_key(title):
    # 不同地區 RSS 可能收錄同一則新聞。
    title = re.sub(r"\s+[-–|]\s+[^-–|]+$", "", title)
    return re.sub(r"[\W_]+", "", title.casefold())

def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    collected = {}
    success_count = 0

    for query, hl, gl, ceid in SEARCHES:
        try:
            entries = fetch_rss(query, hl, gl, ceid)
            success_count += 1
            print(f"OK: {query} ({len(entries)} results)")
        except Exception as exc:
            print(f"WARNING: {query}: {exc}")
            continue

        for entry in entries:
            title = get_text(entry, "title")
            link = get_text(entry, "link")
            description = get_text(entry, "description")
            source = get_text(entry, "source")
            published = parse_date(get_text(entry, "pubDate"))

            if not title or not link or not published:
                continue

            if published < cutoff or published > now + timedelta(days=1):
                continue

            if not is_relevant(title, description):
                continue

            members = identify_members(title, description)
            member = members[0]

            key = normalize_key(title)
            if not key:
                continue

            item = {
                "id": hashlib.sha256(
                    key.encode("utf-8")
                ).hexdigest()[:20],
                "title": title,
                "description": description[:350],
                "url": link,
                "link": link,
                "source": source or "Google News",
                "publishedAt": published.isoformat(),
                "date": published.isoformat(),
                "member": member,
                "members": members,
                "category": "NEWS",
            }

            old = collected.get(key)
            if old is None or item["publishedAt"] > old["publishedAt"]:
                collected[key] = item

    if success_count == 0:
        raise RuntimeError(
            "All RSS requests failed. Existing feed was preserved."
        )

    previous = read_existing()

    # 若暫時沒有新結果，保留仍在30天內的舊新聞。
    for item in previous:
        if not isinstance(item, dict):
            continue

        title = item.get("title", "")
        date_str = item.get("publishedAt") or item.get("date", "")
        try:
            dt = datetime.fromisoformat(
                date_str.replace("Z", "+00:00")
            )
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            continue

        if dt < cutoff:
            continue

        key = normalize_key(title)
        if key and key not in collected:
            collected[key] = item

    items = sorted(
        collected.values(),
        key=lambda x: x.get("publishedAt", x.get("date", "")),
        reverse=True,
    )[:MAX_ITEMS]

    # 不用空結果覆蓋原本正常的新聞資料。
    if not items:
        raise RuntimeError(
            "No relevant news found. Existing feed was preserved."
        )

    feed = {
        "updatedAt": now.isoformat(),
        "status": "ok",
        "count": len(items),
        "items": items,
    }

    OUTPUT.write_text(
        json.dumps(feed, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"SUCCESS: Saved {len(items)} news items to feed.json")

if __name__ == "__main__":
    main()
