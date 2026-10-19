
import json
from datetime import datetime, timezone
from pathlib import Path

def main():
    feed = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "items": []
    }

    Path("feed.json").write_text(
        json.dumps(feed, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("CORTIS feed generated successfully")

if __name__ == "__main__":
    main()
