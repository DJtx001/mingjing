"""把 OSS cases/ 下的案例 PDF 批量解析入库（一次性补导脚本，可重复执行）。

背景：早期上传的 20 个人民法院案例库 PDF 只存了 OSS 未解析；PDF 解析器补全后，
本脚本从 OSS 拉取全部 .pdf 解析四段式并写入 case_ref；向量库由前端「灌库」统一灌入。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.kb import _import_case_pdf
from app.services.oss_service import download_file, list_files


def main():
    pdfs = [f for f in list_files("cases/") if f["key"].lower().endswith(".pdf")]
    print(f"待处理 {len(pdfs)} 个案例 PDF")
    ok, fail = 0, []
    for i, f in enumerate(pdfs, 1):
        try:
            n = _import_case_pdf(download_file(f["key"]), f["key"])
            ok += n
        except Exception as e:
            fail.append((f["key"], str(e)[:80]))
        if i % 10 == 0:
            print(f"  …{i}/{len(pdfs)}，已入库 {ok}")
    print(f"完成：入库 {ok} 个案例，失败 {len(fail)}")
    for k, e in fail:
        print("  失败:", k, e)


if __name__ == "__main__":
    main()
