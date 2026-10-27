"""引用卡片过滤自检：正文没标注的材料不该出现在卡片区。

场景（用户 2026-10-19 报告）：检索给 7 条材料，正文只引用 [1][2][3][4][5][7]，
并写明「[6] 与本题无关，未予引用」，但卡片区仍列出第 6 条（开设赌场罪案例）。
用法：python scripts/_smoke_citation_filter.py
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root if (_root / "app").is_dir() else _root.parent))

from app.api.assist import _used_citations

CITES = [{"citation_type": "law" if i <= 4 else "similar_case", "ref_id": f"c{i}",
          "title": f"材料{i}", "snippet": ""} for i in range(1, 8)]
KEEP_1_5_7 = [CITES[i] for i in (0, 1, 2, 3, 4, 6)]


def t(name, got, want):
    ok = got == want
    print(f"  {'✓' if ok else '✗'} {name}" + ("" if ok else f"\n      got={got}\n      want={want}"))
    return ok


def main():
    results = [
        t("正文标注 1-5,7 → 去掉第 6 条（用户场景）",
          _used_citations("依据如下 [1][2][3][4][5]，另见 [7]。", CITES), KEEP_1_5_7),
        t("全部标注 → 全保留",
          _used_citations(" ".join(f"[{i}]" for i in range(1, 8)), CITES), CITES),
        t("无任何标注 → 兜底全量", _used_citations("直接回答，没有任何标注", CITES), CITES),
        t("空正文 → 兜底全量", _used_citations("", CITES), CITES),
        t("标注全越界 → 兜底全量", _used_citations("见 [9][0]", CITES), CITES),
        t("markdown 链接不算标注", _used_citations("见 [链接](http://x) 和 [1]", CITES), [CITES[0]]),
        t("重复标注不重复出卡", _used_citations("[1][1][1]", CITES), [CITES[0]]),
    ]
    print(f"{sum(results)}/{len(results)} PASS")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())