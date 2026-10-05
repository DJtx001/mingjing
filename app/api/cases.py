"""B组 案件接口（严格对齐《受理Agent接口文档》V1.1 B组）
列表字段：case_id/dispute_type/applicant_name/current_step/status/status_label/assignee
"""
from fastapi import APIRouter

router = APIRouter(prefix="/cases", tags=["B-案件"])

# TODO(建库后)：接入 MySQL 真实查询，当前无数据源，返回空结果


@router.get("")
async def list_cases(status: str = "", dispute_type: str = "", keyword: str = "",
                     page: int = 1, page_size: int = 20):
    """B2 案件列表（页⑦）。status 支持逗号分隔多值"""
    return {"items": [], "page": page, "page_size": page_size, "total": 0}


@router.get("/{case_id}")
async def get_case(case_id: str):
    """B3 案件详情（含状态流转时间线）"""
    return {"error": {"code": "CASE_004", "message": "案件不存在"}}
