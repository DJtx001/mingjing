"""本地目录案例批量入库（写入 MySQL case_ref）。

背景：离线整理的四段式裁判文书 md（D:\\Data\\mingjing\\cases\\{大类}\\{案由}\\{案号}.md）
需要写进 case_ref；向量库随后由前端「重建索引 / 灌库」灌入。

- file_key = cases/{案由}/{案号}.md → _meta_category 取第 2 段作 source（案由）
- 任一段超过 embedding 上限的案例跳过：embed_texts 会按 MAX_CHARS 截尾，
  判决书尾部截断会丢结论/依据，宁缺毋滥
- title 全局唯一，重跑覆盖更新（ON DUPLICATE KEY），幂等
用法：
  python scripts/import_local_cases.py       # 全量
  python scripts/import_local_cases.py 5     # 只跑前 5 篇（验证）
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.kb import _import_case
from app.llm.embedding import MAX_CHARS
from app.services.kb_parser import parse_case_md

SRC = Path(os.environ.get("CASE_DATA_DIR", r"D:\Data\mingjing\cases"))
SECTIONS = ("fact", "process", "result", "comment")


def main(limit: int | None = None) -> None:
    files = sorted(SRC.glob("*/*/*.md"))
    if limit:
        files = files[:limit]
    print(f"待处理 {len(files)} 篇", flush=True)

    ok = skipped = failed = 0
    for i, fp in enumerate(files, 1):
        text = fp.read_text(encoding="utf-8")
        r = parse_case_md(text)
        if not any(r[k] for k in SECTIONS):
            skipped += 1
            continue
        if any(len(r[k] or "") > MAX_CHARS for k in SECTIONS):
            skipped += 1
            continue
        try:
            ok += _import_case(text, f"cases/{fp.parent.name}/{fp.name}")
        except Exception as e:
            failed += 1
            print(f"  失败 {fp.name}: {str(e)[:120]}", flush=True)
        if i % 500 == 0:
            print(f"  进度 {i}/{len(files)}｜入库 {ok} 跳过 {skipped} 失败 {failed}", flush=True)

    print(f"\n完成：入库 {ok} 篇，跳过 {skipped} 篇，失败 {failed} 篇", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else None)
