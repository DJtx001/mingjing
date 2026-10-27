# 明镜加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉 7 项安全与正确性缺陷、清理 6 项工程卫生问题，全部改动本地验证，不部署。

**Architecture:** 后端改动集中在 `app/core/deps.py`（权限）、`app/services/session_service.py`（降级）、`app/api/auth.py`（建表）与 5 个 `app/api/*.py` 的写接口各加一行守卫。测试不引入 pytest，统一写成 `scripts/_smoke_hardening.py` 里的纯 `assert` 函数，零依赖、可重复跑。前端只改 `KnowledgeBaseView.vue` 的规则开关与提示文案。

**Tech Stack:** FastAPI 0.142、PyMySQL、redis-py、Vue 3 + Element Plus、Vitest 2、Python 3.12+（本机 3.14）。

**Spec:** `docs/superpowers/specs/2026-10-27-mingjing-hardening.md`（执行者必须同时读 spec）

## Global Constraints

- 只改本地；不部署、不推送云端。
- 数据库只允许 `CREATE TABLE IF NOT EXISTS` 与新增索引；禁止改列类型、删列、删表。
- 不新增运行时依赖；`requests==2.34.2` 仅补声明（`.venv` 已装）。
- 现有 14 个案件、6 个用户、会话数据不得被改动或丢失。
- 不跑真实 LLM 的 e2e；不跑 `retrieval_eval.py`。
- 提交分 3 个 commit：安全 ①—⑦ / 卫生 ⑧—⑫ / scripts ⑬。每个 task 完成时 `git add`，批次末统一 commit。
- 启动命令统一用 `python -m app.main`（禁 `--reload`，本机 Windows 重载失灵）。
- 测试运行器：`C:\Code\Project\ai-qiuzhao\mingjing-intake\.venv\Scripts\python.exe scripts\_smoke_hardening.py`

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `app/core/deps.py` | 修改 | 新增 `assert_case_writer`；替换 2 处硬编码邮箱 |
| `app/core/config.py` | 修改 | 新增 `CORS_ORIGINS` |
| `app/main.py` | 修改 | CORS 读配置；注册 `auth.init_tables()`（置于最前） |
| `app/api/auth.py` | 修改 | 新增 `init_tables()`：建 `user` 表 + 空表种子账号 |
| `app/api/cases.py` | 修改 | `_seed_if_empty` 受 `DEMO_SEED` 控制 |
| `app/api/kb.py` | 修改 | `PUT /admin/rules` 改 `require_admin` |
| `app/api/intake.py` | 修改 | 2 处写接口加案件守卫 |
| `app/api/documents.py` | 修改 | 2 处写接口加案件守卫 |
| `app/api/mediation.py` | 修改 | 2 处写接口加案件守卫 |
| `app/api/assist.py` | 修改 | `adopt` 加案件守卫 |
| `app/services/session_service.py` | 修改 | 2 处 Redis 写包 try/except |
| `frontend/src/views/KnowledgeBaseView.vue` | 修改 | 规则开关限 admin；邮箱文案 |
| `frontend/package.json` | 修改 | 增加 `test` 脚本 |
| `requirements.txt` | 修改 | 增加 `requests` |
| `.env.example` | 修改 | 补 6 个配置项 |
| `.gitignore` | 修改 | `scripts/` 整目录规则改为白名单 |
| `.gitignore` 关联 | 新增 | `scripts/_scratch/` 等忽略规则 |
| `scripts/_scratch/` | 移动 | 48 个临时探针迁入 |
| `scripts/_smoke_hardening.py` | 新增 | 本轮全部自动化断言 |
| `docs/superpowers/plans/` | 新增 | 本文件 |

## Review Focus

1. **写权限误伤正常流程** — 复核退回补充后由原承办人继续操作必须成功。T1 断言「本人对自己案件 PASS」覆盖。
2. **`user` 建表顺序** — `auth.init_tables()` 必须排在 `assist.init_tables()` 前，否则空库外键建表失败。T4 用源码顺序断言。
3. **CORS 默认关闭的副作用** — 独立部署的前端会被浏览器拦截。T2 断言默认 `allow_origins == []`，并在最终验证里人工确认同源页面可用。
4. **Redis 写降级掩盖故障** — 长期故障只留 warning。T3 捕获日志断言 warning 确实产生。
5. **scripts 纳管带入环境耦合** — 入库脚本含公网 IP/默认口令。T13 断言入库文件无这些字面量。

---

## Task 1: 案件写权限守卫

**Files:**
- Modify: `app/core/deps.py`
- Modify: `app/api/intake.py:132,183`、`app/api/documents.py:102,118`、`app/api/mediation.py:163,226`、`app/api/assist.py:600`
- Test: `scripts/_smoke_hardening.py`（新建）

**Interfaces:**
- Produces: `assert_case_writer(case_id: str, user: dict) -> None`，失败抛 `HTTPException(403, {"code": "AUTHZ_002", ...})`；案件不存在抛 `HTTPException(404, "案件不存在")`。

- [ ] **Step 1: 写失败测试**

新建 `scripts/_smoke_hardening.py`，内容：

```python
"""本轮加固的纯函数级回归断言。用法：.venv/Scripts/python.exe scripts/_smoke_hardening.py"""
import sys, traceback
from app.core.db import MySQLClient
from fastapi import HTTPException


def _one_case():
    db = MySQLClient()
    try:
        rows = db.execute("SELECT case_id, assignee_user_id FROM case_info ORDER BY case_id LIMIT 1")
        assert rows, "case_info 为空，无法测试"
        return rows[0]
    finally:
        db.close()


def test_assert_case_writer():
    from app.core.deps import assert_case_writer
    c = _one_case()
    owner = {"user_id": c["assignee_user_id"], "role": "intake_clerk"}
    other = {"user_id": "u_999", "role": "intake_clerk"}
    admin = {"user_id": "u_999", "role": "admin"}

    assert assert_case_writer(c["case_id"], owner) is None
    assert assert_case_writer(c["case_id"], admin) is None
    try:
        assert_case_writer(c["case_id"], other)
        raise AssertionError("他人应被 403")
    except HTTPException as e:
        assert e.status_code == 403
        assert e.detail["code"] == "AUTHZ_002"
    try:
        assert_case_writer("AJ9999-00000", admin)
        raise AssertionError("不存在案件应 404")
    except HTTPException as e:
        assert e.status_code == 404


TESTS = [test_assert_case_writer]


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    failed = 0
    for t in TESTS:
        if only and only not in t.__name__:
            continue
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    sys.exit(1 if failed else 0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py`
Expected: `ImportError: cannot import name 'assert_case_writer'`

- [ ] **Step 3: 实现 `assert_case_writer`**

`app/core/deps.py` 增加（`MySQLClient` 需新增 import）：

```python
def assert_case_writer(case_id: str, user: dict) -> None:
    """admin 直通；否则要求当前用户是该案承办人。"""
```

admin 判断用 `user.get("role") == "admin"`；查询用短连接 + `try/finally` 关闭；403 文案「你不是该案件承办人，无权修改」。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py`
Expected: `PASS test_assert_case_writer`

- [ ] **Step 5: 在 7 个写接口首行接入**

| 文件 | 函数 | 调用 |
|---|---|---|
| `intake.py:132` | `confirm_elements` | `assert_case_writer(case_id, user)` |
| `intake.py:183` | `clarify_element` | 同上 |
| `documents.py:102` | `generate_documents` | 同上 |
| `documents.py:118` | `issue_document` | 同上 |
| `mediation.py:163` | `save_mediation_result` | 同上 |
| `mediation.py:226` | `issue_agreement` | 同上 |
| `assist.py:600` | `adopt` | `assert_case_writer(body.case_id, user)` |

调用点放在函数 docstring 之后、任何写库之前。各文件补 `from app.core.deps import assert_case_writer`（已有 `get_current_user` 的合并为一次 import）。

- [ ] **Step 6: 静态确认 7 处都已接入**

Run: `grep -rn "assert_case_writer(" app/api/`
Expected: 恰好 7 行，且均在函数体内（不是 import 行）

- [ ] **Step 7: 暂存**

```bash
git add app/core/deps.py app/api/intake.py app/api/documents.py app/api/mediation.py app/api/assist.py scripts/_smoke_hardening.py
```

---

## Task 2: CORS 收窄

**Files:**
- Modify: `app/core/config.py`、`app/main.py:121-127`
- Test: `scripts/_smoke_hardening.py`

**Interfaces:**
- Produces: `config.CORS_ORIGINS: list[str]`，默认 `[]`。

- [ ] **Step 1: 写失败测试**

向 `scripts/_smoke_hardening.py` 追加：

```python
def test_cors_reads_config():
    from app.core.config import config
    assert isinstance(config.CORS_ORIGINS, list)
    from app.main import app
    cors = [m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware"][0]
    assert cors.kwargs["allow_origins"] == config.CORS_ORIGINS
    assert cors.kwargs["allow_credentials"] is bool(config.CORS_ORIGINS)
```

并加入 `TESTS`。前提：本地 `.env` 未设置 `CORS_ORIGINS`，此时期望值为 `[]`（Step 4 会单独确认默认值）。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py cors`
Expected: `AttributeError: 'Config' object has no attribute 'CORS_ORIGINS'`

- [ ] **Step 3: 实现配置与中间件**

`config.py` 在 OSS 之前新增：

```python
# 允许的跨域来源（逗号分隔，默认空=不开放跨域；同源访问与 Vite 代理不受影响）
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
```

`main.py:121-127` 改为：

```python
_origins = config.CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=bool(_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py cors`
Expected: `PASS test_cors_reads_config`

Run: `.venv/Scripts/python.exe -c "from app.core.config import config; print(repr(config.CORS_ORIGINS))"`
Expected: `[]`（若打印非空，说明本地 `.env` 设置过该值，属预期差异）

- [ ] **Step 5: 暂存**

```bash
git add app/core/config.py app/main.py scripts/_smoke_hardening.py
```

---

## Task 3: Redis 写路径降级

**Files:**
- Modify: `app/services/session_service.py:169-178,267-276`
- Test: `scripts/_smoke_hardening.py`

**Interfaces:**
- Produces: `create_session(user_id, case_id=None) -> str` 与 `append_message(...) -> None` 在 Redis 异常时仍完成 MySQL 写入，且记录 `WARNING`。

- [ ] **Step 1: 写失败测试**

追加：

```python
def test_redis_write_degrades():
    import logging
    from app.services import session_service as ss

    class _Boom:
        def __getattr__(self, _): raise ConnectionError("redis down")

    class _Capture(logging.Handler):
        def __init__(self): super().__init__(); self.msgs = []
        def emit(self, r): self.msgs.append(r.getMessage())

    orig = ss.get_redis
    cap = _Capture()
    ss.logger.addHandler(cap)
    ss.get_redis = lambda: _Boom()
    sid = None
    try:
        sid = ss.create_session("u_001")
        ss.append_message(sid, "user", "降级测试")
    finally:
        ss.get_redis = orig
        ss.logger.removeHandler(cap)
        db = MySQLClient()
        try:
            db.execute("DELETE FROM assist_message WHERE session_id=%s", (sid,))
            db.execute("DELETE FROM assist_session WHERE session_id=%s", (sid,))
            db.commit()
        finally:
            db.close()

    assert sid.startswith("sess_")
    assert any("redis" in m.lower() for m in cap.msgs), cap.msgs
```

并加入 `TESTS`。注意 `MySQLClient.commit()` 存在，可直接用。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py redis`
Expected: `FAIL`，`ConnectionError: redis down`

- [ ] **Step 3: 实现降级**

`create_session`：把 `r = get_redis()` 到 `_touch_user_index(...)` 整段包进 `try/except Exception as e: logger.warning("Redis 不可用，跳过会话热缓存 user_id=%s: %s", user_id, e)`，MySQL 写入保持在 try 之外。

`append_message`：把 `r = get_redis()` 到 `_touch_user_index(...)` 整段（`:267-276`）同样包裹，warning 文案 `"Redis 不可用，跳过消息热缓存 session_id=%s: %s"`。

- [ ] **Step 4: 跑测试确认通过，并确认真实 Redis 不受影响**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py redis`
Expected: `PASS test_redis_write_degrades`

Run: `.venv/Scripts/python.exe -c "from app.services.session_service import create_session; s=create_session('u_001'); print(s)"`
Expected: 打印 `sess_` 开头的 ID（真实 Redis 路径），无异常

- [ ] **Step 5: 暂存**

```bash
git add app/services/session_service.py scripts/_smoke_hardening.py
```

---

## Task 4: `user` 表 DDL 与种子账号

**Files:**
- Modify: `app/api/auth.py`、`app/main.py:178-194`
- Test: `scripts/_smoke_hardening.py`

**Interfaces:**
- Produces: `auth.init_tables() -> None`，幂等建 `user` 表；空表时插入 6 个账号，密码 `123456`。

- [ ] **Step 1: 写失败测试**

追加：

```python
def test_user_table_and_seed():
    import inspect
    from app.api import auth
    assert hasattr(auth, "init_tables")
    before = _user_rows()
    auth.init_tables()
    after = _user_rows()
    assert before == after, "已有用户不应被改动"
    assert len(after) >= 6

    import app.main as main_mod
    src = inspect.getsource(main_mod)
    assert src.index("auth.init_tables()") < src.index("assist.init_tables()"), \
        "auth 建表必须排在 assist 之前"


def _user_rows():
    db = MySQLClient()
    try:
        return sorted(r["username"] for r in db.execute("SELECT username FROM user"))
    finally:
        db.close()
```

并加入 `TESTS`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py user`
Expected: `FAIL AssertionError: hasattr(auth, 'init_tables')` 为 False

- [ ] **Step 3: 实现 `auth.init_tables()`**

`app/api/auth.py` 新增。DDL 与种子数据照抄 spec §4④：

- `CREATE TABLE IF NOT EXISTS user (...)`，列定义与实测一致
- `SELECT COUNT(*) FROM user` 为 0 时，用 `hash_password("123456")` 生成哈希，`executemany` 插入 6 行
- 全部包在 `try/finally: conn.close()` 中，`conn.commit()`

- [ ] **Step 4: 在 `main.py` 注册，位置最先**

在 `app/main.py` 的知识库建表块**之前**插入：

```python
# 用户表幂等建表（必须最先：assist 表有外键引用 user）
try:
    auth.init_tables()
except Exception as _e:
    logger.warning("user 建表失败: %s", _e)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py user`
Expected: `PASS test_user_table_and_seed`

- [ ] **Step 6: 空库场景手工验证**

```bash
.venv/Scripts/python.exe - <<'PY'
import pymysql
from app.core.config import config

m = config.MYSQL
c = pymysql.connect(**m)
c.cursor().execute("CREATE DATABASE IF NOT EXISTS mingjing_test CHARACTER SET utf8mb4")
c.commit(); c.close()

orig = m["database"]
m["database"] = "mingjing_test"
try:
    from app.api import auth
    auth.init_tables()
    c = pymysql.connect(**m); cur = c.cursor()
    cur.execute("SELECT COUNT(*) FROM user"); print("rows:", cur.fetchone()[0])
    c.close()
finally:
    m["database"] = orig
    c = pymysql.connect(**config.MYSQL)
    c.cursor().execute("DROP DATABASE IF EXISTS mingjing_test"); c.commit(); c.close()
PY
```
Expected: `rows: 6`（结束后 `mingjing_test` 已删除）

- [ ] **Step 7: 暂存**

```bash
git add app/api/auth.py app/main.py scripts/_smoke_hardening.py
```

---

## Task 5: 演示播种开关

**Files:**
- Modify: `app/api/cases.py:110-122`
- Test: `scripts/_smoke_hardening.py`

**Interfaces:**
- Produces: `_seed_if_empty()` 在 `DEMO_SEED != "1"` 时立即返回，不建数据库连接。

- [ ] **Step 1: 写失败测试**

追加：

```python
def test_demo_seed_off_by_default():
    import os
    os.environ.pop("DEMO_SEED", None)
    from app.api import cases
    orig = cases._conn
    cases._conn = lambda: (_ for _ in ()).throw(AssertionError("默认不应连接数据库"))
    try:
        cases._seed_if_empty()
    finally:
        cases._conn = orig
```

并加入 `TESTS`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py seed`
Expected: `FAIL AssertionError: 默认不应连接数据库`

- [ ] **Step 3: 实现开关**

`_seed_if_empty()` 首行：

```python
if os.getenv("DEMO_SEED") != "1":
    return
```

`cases.py` 顶部补 `import os`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py seed`
Expected: `PASS test_demo_seed_off_by_default`

- [ ] **Step 5: 暂存**

```bash
git add app/api/cases.py scripts/_smoke_hardening.py
```

---

## Task 6: 移除硬编码邮箱

**Files:**
- Modify: `app/core/deps.py:45,56`、`frontend/src/views/KnowledgeBaseView.vue:240`
- Test: `scripts/_smoke_hardening.py`

- [ ] **Step 1: 写失败测试**

追加：

```python
def test_no_hardcoded_admin_email():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    hits = [p for p in list(root.joinpath("app").rglob("*.py"))
                  + list(root.joinpath("frontend/src").rglob("*.vue"))
                  if "3112028466" in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits == [], hits
```

并加入 `TESTS`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py email`
Expected: `FAIL AssertionError`，列出 `deps.py`

- [ ] **Step 3: 替换文案**

后端两处改为 `"你没有权限，请联系系统管理员"` / `"你没有复核权限，请联系系统管理员"`；前端 `guardAdmin` 的 `ElMessage.error` 同步改为 `'你没有权限，请联系系统管理员'`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py email`
Expected: `PASS test_no_hardcoded_admin_email`

- [ ] **Step 5: 暂存**

```bash
git add app/core/deps.py frontend/src/views/KnowledgeBaseView.vue scripts/_smoke_hardening.py
```

---

## Task 7: 规则编辑权限

**Files:**
- Modify: `app/api/kb.py:192-194`、`frontend/src/views/KnowledgeBaseView.vue:129,234-235,528`
- Test: `scripts/_smoke_hardening.py`

- [ ] **Step 1: 写失败测试**

追加：

```python
def test_rules_admin_only():
    import inspect
    from app.api import kb
    src = inspect.getsource(kb.update_rule)
    assert "require_admin" in src
```

并加入 `TESTS`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py rules`
Expected: `FAIL AssertionError`

- [ ] **Step 3: 后端改依赖**

`app/api/kb.py:193`：`user=Depends(get_current_user)` → `user=Depends(require_admin)`；docstring 改为「仅管理员可启停/修改」。

- [ ] **Step 4: 前端同步**

- `:129` 的 `el-switch` 增加 `:disabled="!isAdmin"`
- `beforeSwitchChange`（`:528`）首行加 `if (!guardAdmin()) return false`
- `:234-235` 注释改为「规则启停与保存类操作均仅 admin」

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py rules`
Expected: `PASS test_rules_admin_only`

- [ ] **Step 6: 暂存**

```bash
git add app/api/kb.py frontend/src/views/KnowledgeBaseView.vue scripts/_smoke_hardening.py
```

---

## Task 8: 删除死文件（第一批 commit 收口）

**Files:**
- Delete: `frontend/legacy/index.html`
- Delete: `app/capability/retrieval/`（含 0 字节 `__init__.py`）
- Delete: `configs/prompts/` 空目录

- [ ] **Step 1: 确认无引用**

Run: `grep -rn "capability.retrieval\|capability/retrieval\|legacy/index" app/ frontend/src/ --include=*.py --include=*.js --include=*.vue`
Expected: 无输出

- [ ] **Step 2: 删除**

```bash
git rm -q frontend/legacy/index.html app/capability/retrieval/__init__.py
rm -rf app/capability configs/prompts
```
（`app/capability` 删空后一并移除；`configs/` 若还有其他内容则保留目录）

- [ ] **Step 3: 验证导入链未断**

Run: `.venv/Scripts/python.exe -c "import app.main; print('ok')"`
Expected: `ok`

- [ ] **Step 4: 安全批次提交**

```bash
git add app/ frontend/ docs/
git commit -m "fix(security): 案件写权限、CORS、Redis 写降级、user 建表、播种开关与权限收敛"
```

---

## Task 9: README 修正

**Files:**
- Modify: `README.md:11,17,63,188-191,202,209,238` + 快速开始段

- [ ] **Step 1: 逐条修改**

按 spec §4⑨ 的 7 行表格执行。快速开始补：

```
# 可选：演示数据播种（默认关闭）
DEMO_SEED=0
# 可选：允许的跨域来源，逗号分隔（默认不开放）
CORS_ORIGINS=
# 演示账号：admin / 123456（仅种子数据，生产必改）
```

- [ ] **Step 2: 验证关键断言**

Run: `grep -n "reload\|说明.md\|Ollama\|Python 3" README.md`
Expected: 无 `--reload` 启动示例；无 `说明.md` 条目；Ollama 标注为已关闭；Python 版本统一为 `3.12+`

- [ ] **Step 3: 暂存**

```bash
git add README.md
```

---

## Task 10: 补齐 `requests`

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 加一行**

`requests==2.34.2` 放在 `uvicorn` 之后。

- [ ] **Step 2: 验证**

Run: `.venv/Scripts/python.exe -c "import requests; print(requests.__version__)"`
Expected: `2.34.2`

Run: `grep -n "requests" requirements.txt`
Expected: 恰 1 行

- [ ] **Step 3: 暂存**

```bash
git add requirements.txt
```

---

## Task 11: 前端 test 脚本

**Files:**
- Modify: `frontend/package.json:6-10`

- [ ] **Step 1: 加脚本**

`scripts` 增加 `"test": "vitest run"`。

- [ ] **Step 2: 验证**

Run: `cd frontend && npm test`
Expected: Vitest 跑完 `smoke.spec.js`，退出码 0

（若 node_modules 缺失，先 `npm install`，再跑）

- [ ] **Step 3: 暂存**

```bash
git add frontend/package.json
```

---

## Task 12: `.env.example` 补全（卫生批次收口）

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: 增补配置**

在 OSS 段之后追加：

```
# ===== Embedding（DashScope 兼容模式）=====
EMBEDDING_API_KEY=
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v3

# ===== 向量库（派生数据，可 reindex 重建）=====
CHROMA_PATH=Chromadb

# ===== 跨域（逗号分隔；默认空=不开放）=====
CORS_ORIGINS=

# ===== 演示数据（1=空库自动播种 8 个演示案件）=====
DEMO_SEED=0
```

Ollama 段注释改为 `# ===== 本地兜底（已停用，代码保留）=====`。

- [ ] **Step 2: 验证**

Run: `grep -n "EMBEDDING_API_KEY\|CHROMA_PATH\|CORS_ORIGINS\|DEMO_SEED" .env.example`
Expected: 4 项各至少 1 行

- [ ] **Step 3: 卫生批次提交**

```bash
git add README.md requirements.txt frontend/package.json .env.example
git commit -m "chore: README 与实现对齐、补 requests/test 脚本、补全 .env.example、删死文件"
```

---

## Task 13: `scripts/` 纳管

**Files:**
- Modify: `.gitignore:22-24`
- Move: 48 个临时探针 → `scripts/_scratch/`
- Modify: `_smoke_deploy_check.py:18,30`、`_verify_http_session_order.py:4,13-17`、`_smoke_status_http.py:19`、`import_local_cases.py:23`、`verify_step4_parser.py:13`
- Test: `scripts/_smoke_hardening.py`

**Interfaces:**
- Consumes: Task 1—7 写入 `scripts/_smoke_hardening.py` 的全部测试。
- Produces: 入库的 `scripts/` 白名单，`git ls-files scripts/` 26~30 个。

- [ ] **Step 1: 写失败测试**

追加：

```python
def test_scripts_no_secrets():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    bad = []
    for p in root.joinpath("scripts").rglob("*.py"):
        if "_scratch" in p.parts:
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if "39.107.157.0" in txt:
            bad.append(f"{p.name}: 公网 IP")
        if 'password' in txt.lower() and any(
                s in txt for s in ("admin123", "admin@123")):
            bad.append(f"{p.name}: 明文口令")
    assert bad == [], bad
```

并加入 `TESTS`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py secrets`
Expected: `FAIL`，列出 `_smoke_deploy_check.py` 与 `_verify_http_session_order.py`

- [ ] **Step 3: 迁移临时探针**

```bash
cd scripts
mkdir -p _scratch
mv _probe_* _calibrate*.py _calib2.json verify_step*.py verify_ui_*.py \
   _shots _chroma_test _flags.txt _negqueries.txt _negrecall.txt \
   Professional_stock_photography_*.png _scratch/ 2>/dev/null
rm -rf __pycache__
cd ..
```
（`_scratch/` 内保留原样，不入库）

- [ ] **Step 4: 改 `.gitignore`**

删除 `scripts/` 整目录规则，改为：

```
# scripts 纳入版本控制；只忽略一次性探针与生成物
scripts/_scratch/
scripts/_shots/
scripts/_chroma_test/
scripts/__pycache__/
scripts/*.npz
```

- [ ] **Step 5: 脱敏**

- `_smoke_deploy_check.py:18`：`BASE = os.getenv("SMOKE_BASE_URL", "http://127.0.0.1:8000")`
- `_smoke_deploy_check.py` 凭据：`USER = os.getenv("SMOKE_USER", "admin")`、`PWD = os.getenv("SMOKE_PASSWORD", "")`；为空则打印跳过并 `return`
- `_verify_http_session_order.py`：删掉 8 个 `sess_` 字面量与 IP，改为运行时创建会话、`SMOKE_BASE_URL`；凭据同上
- `_smoke_status_http.py:19`：凭据同上
- `import_local_cases.py:23`：`CASE_DATA_DIR = os.getenv("CASE_DATA_DIR", r"D:\Data\mingjing\cases")`
- `verify_step4_parser.py:13`：`DATA_DIR = os.getenv("CASE_DATA_DIR", r"D:\Data\mingjing")`

- [ ] **Step 6: 跑测试确认通过**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py secrets`
Expected: `PASS test_scripts_no_secrets`

- [ ] **Step 7: 验证纳管边界**

Run: `git add scripts/ && git status --short scripts/ | wc -l`
Expected: 26~30

Run: `git status --ignored --short scripts/ | grep '^!!'`
Expected: 只出现 `_scratch/`、`_shots/`、`_chroma_test/`、`__pycache__/`、`*.npz`

Run: `git ls-files scripts/ | grep -c "npz\|_shots\|_chroma_test"`
Expected: `0`

- [ ] **Step 8: 提交**

```bash
git commit -m "chore(scripts): 纳入回归/评测/运维脚本，临时探针隔离并脱敏"
```

---

## Task 14: 最终验证（V1—V8）

- [ ] **Step 1: 启动完整性（V1）**

Run: `.venv/Scripts/python.exe -m app.main`（后台）
Expected: 日志 9 个 `init_tables` 无 error；出现 `warmup` 行

- [ ] **Step 2: 接口回归（V2）**

Run: `.venv/Scripts/python.exe scripts/test_api_e2e.py`
Expected: 全部 `PASS`，退出码 0

- [ ] **Step 3: 写权限矩阵（V3）**

用 `requests` 直接登录两个账号取 token（`POST /auth/login`，admin 与 lisi），携带 `Authorization: Bearer` 对 `AJ2026-10086`（assignee=u_002）调 `PUT /cases/AJ2026-10086/elements`，body 用 `{"elements": []}` 即可（权限校验在业务处理之前）：
Expected: lisi → 403 `AUTHZ_002`；admin → 非 403（可能 422/400，属业务校验，不算权限失败）

- [ ] **Step 4: 加固断言（V4）**

Run: `.venv/Scripts/python.exe scripts/_smoke_hardening.py`
Expected: 全部 `PASS`，退出码 0

- [ ] **Step 5: 会话链路（V5）**

真实 Redis 下：`POST /assist/sessions` → `POST /assist/chat` → `GET /assist/sessions/{id}/messages` → `DELETE`
Expected: 消息顺序正确、无 500

- [ ] **Step 6: 前端单测（V6）**

Run: `cd frontend && npm test`
Expected: 退出码 0

- [ ] **Step 7: 播种开关（V7）**

临时库 + 不设 `DEMO_SEED` 调 `GET /cases` → 0 行；设 `DEMO_SEED=1` → 8 行；验证后删库。

- [ ] **Step 8: 残留扫描（V8）**

Run: `grep -rn "3112028466" app/ frontend/src/`
Expected: 无输出

Run: `grep -n 'allow_origins' app/main.py`
Expected: 不再出现 `["*"]`

- [ ] **Step 9: 汇报**

输出 V1—V8 的逐项结果（命令 + 退出码 + 关键输出），未通过项单独列出，不宣称全绿。

---

## Self-Review 记录

- **Spec 覆盖**：①→T1，②→T2，③→T3，④→T4，⑤→T5，⑥→T6，⑦→T7，⑧→T8，⑨→T9，⑩→T10，⑪→T11，⑫→T12，⑬→T13；验证 V1—V8→T14。
- **类型一致性**：`assert_case_writer` 在 T1 定义、T1 内 7 处消费；`CORS_ORIGINS` T2 定义并被 `main.py` 消费；`auth.init_tables` T4 定义、T4 内 `main.py` 消费。
- **Review Focus 落点**：1→T1 Step 1「本人 PASS」断言；2→T4 Step 1 源码顺序断言；3→T2 Step 1 默认空断言 + T14 Step 7 手工；4→T3 Step 1 日志捕获断言；5→T13 Step 1 无密钥断言。
- **未覆盖项**：前端规则开关的视觉行为、CORS 在真实浏览器中的表现，属人工验证范围，已在 T14 与 spec §6 标注。