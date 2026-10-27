# 明镜加固 Spec（2026-10-27）

> 本文件只回答三个问题：**改什么、为什么这么改、怎么算改对了**。
> 不含逐步代码计划；实现细节（具体行号、函数体）由后续 plan 承载。

**目标**：在不新增功能、不新增运行时依赖的前提下，修掉 7 项安全与正确性缺陷，并把 5 项低成本工程卫生问题清干净。

**非目标**：云端部署同步、性能优化、新功能、测试框架化、数据库列变更、密钥轮换。

---

## 1. 背景

全链路（M0 受理 → M1 文书 → M2 复核 → M3 调解结案）已闭环，RAG/BM25/FC/MCP 均已上线。当前问题集中在工程卫生，不在功能。本轮依据 2026-10-27 的全量探查报告，只处理其中「已验证、可复现、有明确修复位置」的条目。

---

## 2. 全局约束

| 约束 | 内容 |
|---|---|
| 范围 | 只改本地；不部署、不推送到云端 |
| 数据库 | 只允许 `CREATE TABLE IF NOT EXISTS` 与新增索引；**禁止**改列类型、删列、删表 |
| 依赖 | 不新增运行时依赖；`requests` 仅补声明（`.venv` 已装 2.34.2） |
| 验证 | 全部改完一次性验证；不跑真实 LLM 的 e2e，不跑 200 条检索评测 |
| 提交 | 3 个 commit：安全 ①—⑦、卫生 ⑧—⑫、scripts 纳管 ⑬ |
| 兼容 | 现有 14 个案件、6 个用户、会话数据不得被改动或丢失 |

---

## 3. 决策记录

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| D1 | 本轮目标 | 修真实缺陷，顺带零成本清理 | 缺陷是复利成本；新功能无明确需求 |
| D2 | 部署 | 只做本地 | 代码未验证就上云，无法区分代码问题与部署问题 |
| D3 | 案件可见性 | **读：全员可见；写：仅承办人或 admin** | 用户选定口径「乙」 |
| D4 | 未归属案件 | 不特殊处理 | 实测 14 个案件 `assignee_user_id` 全部非空 |
| D5 | 自动播种 | 环境变量 `DEMO_SEED=1` 才播种，默认关 | 一行开关同时满足演示与生产 |
| D6 | CORS | 默认不允许任何跨域，来源由 `CORS_ORIGINS` 显式配置 | 线上同源托管、开发走 Vite 代理，真实访问都不需要 CORS |
| D7 | 种子账号密码 | 统一演示密码 `123456`，README 标注「仅演示」 | 仅空表时插入，本地现有 6 账号不受影响 |
| D8 | scripts 纳管 | 资产与运维脚本入库，临时探针移入 `scripts/_scratch/` 并继续忽略 | 避免后人猜哪个脚本还能跑 |
| D9 | Redis 写降级 | 吞异常 + `logger.warning`，继续写 MySQL | 与读路径对称；会话热缓存丢失不影响真相源 |

---

## 4. 改动规格

### ① 案件写权限

**现状**：`app/api/cases.py:197-238` 只校验登录；要素、文书、调解、采纳等写接口同样只依赖 `get_current_user`。任何登录用户可修改任意案件。

**目标行为**：读接口不变；下列 7 个写入口要求 `user.role == "admin"` 或 `case_info.assignee_user_id == user.user_id`，否则 403。

| 接口 | 位置 |
|---|---|
| `PUT /cases/{case_id}/elements` | `app/api/intake.py:132` |
| `POST /cases/{case_id}/elements/{element_id}/clarify` | `app/api/intake.py:183` |
| `POST /cases/{case_id}/documents/generate` | `app/api/documents.py:102` |
| `POST /cases/{case_id}/documents/{doc_id}/issue` | `app/api/documents.py:118` |
| `PUT /cases/{case_id}/mediation-result` | `app/api/mediation.py:163` |
| `POST /cases/{case_id}/agreement/issue` | `app/api/mediation.py:226` |
| `POST /assist/adopt`（`case_id` 在 body） | `app/api/assist.py:600` |

复核裁决 `POST /reviews/{case_id}/decision` **不纳入**，它按角色（`reviewer`/`admin`）校验，与归属无关。

**实现**：`app/core/deps.py` 新增：

```python
def assert_case_writer(case_id: str, user: dict) -> None:
    """admin 直通；否则要求当前用户是该案承办人。案件不存在抛 404。"""
```

- admin：`user["role"] == "admin"` → 直接返回
- 查 `SELECT assignee_user_id FROM case_info WHERE case_id=%s`
- 无行 → `HTTPException(404, "案件不存在")`
- 归属不等 → `HTTPException(403, {"code": "AUTHZ_002", "message": "你不是该案件承办人，无权修改"})`

`assist.adopt` 在函数内 `assert_case_writer(body.case_id, user)`；其余 6 处同样在函数体首行调用（不包装成 `Depends`，因为 `adopt` 的 `case_id` 不在路径里，两套写法不如一套）。

**验收**：
- u_003 的 token 调 u_002 名下案件（如 `AJ2026-10086`）的任一写接口 → 403 `AUTHZ_002`
- u_002（admin）调同一接口 → 不因权限失败
- 案件不存在 → 404
- 读接口（列表、详情）对 u_003 仍返回全部 14 个案件

---

### ② CORS 收窄

**现状**：`app/main.py:121-127`，`allow_origins=["*"]` + `allow_credentials=True`。

**目标行为**：新增配置 `CORS_ORIGINS`（逗号分隔，默认空）。`allow_origins` 取该列表；`allow_credentials = bool(origins)`。无 Origin 头或同源请求不受影响。

**落点**：`app/core/config.py` 新增 `CORS_ORIGINS`（`list[str]`，`os.getenv("CORS_ORIGINS", "")` 按逗号切分并去空白）；`app/main.py:121-127` 使用之。

**验收**：
- 不设 `CORS_ORIGINS`：带 `Origin: http://evil.example` 的响应无 `Access-Control-Allow-Origin`
- 设 `CORS_ORIGINS=http://localhost:5173`：该来源得到正确 ACAO 头
- 浏览器直接访问 8000 端口页面（同源）功能正常

---

### ③ Redis 写路径降级

**现状**：`app/services/session_service.py:169-178`（`create_session`）与 `:267-276`（`append_message`）的 Redis 写操作无异常处理；Redis 不可用时整个请求 500，且 MySQL 真相源也不会写入。

**目标行为**：Redis 写段整体包 `try/except Exception`，`logger.warning` 记录后继续执行 MySQL 写入。`create_session` 仍返回有效 `session_id`；`append_message` 仍写入 `assist_message`。

**落点**：上述两个函数；`_touch_user_index` 的调用包含在 try 内。

**验收**：把 `app.services.session_service.get_redis` 替换为抛 `ConnectionError` 的函数后：
- `create_session("u_001")` 不抛异常，返回 `sess_` 前缀 ID，`assist_session` 新增一行
- `append_message(sid, "user", "测试")` 不抛异常，`assist_message` 新增一行
- 日志出现 `warning`，不含堆栈中断

---

### ④ `user` 表 DDL 与种子账号

**现状**：`user` 表只存在于本地 MySQL（9 列、6 行），仓库内无建表语句；`app/api/assist.py:218` 还有外键引用它。新环境按 README 启动后无法登录。

**目标行为**：`app/api/auth.py` 新增 `init_tables()`，在 `app/main.py` 的建表序列中**最先**调用（必须先于 `assist.init_tables()`，否则外键建表失败）。

表结构（照实测列定义）：

```sql
CREATE TABLE IF NOT EXISTS user (
  user_id VARCHAR(16) PRIMARY KEY,
  username VARCHAR(32) NOT NULL UNIQUE,
  password_hash VARCHAR(128) NOT NULL,
  name VARCHAR(32) NOT NULL,
  role ENUM('intake_clerk','reviewer','admin') NOT NULL,
  org VARCHAR(64) DEFAULT NULL,
  status ENUM('active','disabled') DEFAULT 'active',
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) DEFAULT CHARSET=utf8mb4 COMMENT='系统用户';
```

种子：仅在 `SELECT COUNT(*) FROM user` 为 0 时插入 6 个账号，密码统一 `123456`，用 `app.core.security.hash_password` 现算（避免启动时重复 bcrypt 开销）：

| user_id | username | name | role |
|---|---|---|---|
| u_001 | zhangming | 张明 | intake_clerk |
| u_002 | admin | 系统管理员 | admin |
| u_003 | lisi | 李四 | intake_clerk |
| u_004 | wangwu | 王五 | reviewer |
| u_005 | zhaoliu | 赵六 | intake_clerk |
| u_006 | sunqi | 孙七 | intake_clerk |

**验收**：
- 现有库启动后 `user` 仍为 6 行、`password_hash` 未变
- 空库（临时库名）启动后自动建表并插入 6 行，`admin / 123456` 可登录
- 启动日志中 `auth.init_tables` 无 warning

---

### ⑤ 演示播种开关

**现状**：`app/api/cases.py:110-122` 在 `case_info` 为空时插入 8 个虚构案件；`:202`、`:240` 每次列表/详情访问都会触发。

**目标行为**：`DEMO_SEED` 环境变量不等于 `"1"` 时 `_seed_if_empty()` 立即返回。函数保留，用于演示环境。

**落点**：`app/api/cases.py:110` 首行加判断；`.env.example` 补注释说明。

**验收**：
- 清空 `DEMO_SEED`，对**临时空库**（`MySQL_DATABASE=mingjing_test`）调 `GET /cases` → `case_info` 仍为 0 行
- 设 `DEMO_SEED=1`，对同一空库调 `GET /cases` → 插入 8 行，且第二次调用不重复插入
- 验证结束后删除临时库；现有 `mingjing` 库不得被触碰

---

### ⑥ 硬编码管理员邮箱

**现状**：`app/core/deps.py:45`、`:56`、`frontend/src/views/KnowledgeBaseView.vue:240` 三处写死 `3112028466@qq.com`。

**目标行为**：文案统一为「你没有权限，请联系系统管理员」。前端同步替换。

**验收**：全仓 `grep -r "3112028466"` 无命中。

---

### ⑦ 规则编辑权限

**现状**：`app/api/kb.py:192-194` 的 `PUT /admin/rules` 只要求登录，任意受理员可启停核验规则；同模块 Schema/Prompt/删除/reindex 均要求 `require_admin`。前端 `KnowledgeBaseView.vue:129` 的规则开关对所有人可点。

**目标行为**：后端改为 `Depends(require_admin)`；前端 `KnowledgeBaseView.vue:129` 的开关加 `:disabled="!isAdmin"`，`beforeSwitchChange`（`:528`）首行改调 `guardAdmin()`，并更新 `:234-235` 的注释。

**验收**：
- 受理员（u_003）`PUT /admin/rules` → 403
- admin → 200
- 非 admin 前端规则开关不可点，点击提示权限不足

---

### ⑧ 删除死文件

| 路径 | 依据 |
|---|---|
| `frontend/legacy/index.html` | 全仓无引用，`git mv`/`rm` 跟踪文件中 |
| `app/capability/retrieval/` | 仅 0 字节 `__init__.py`，检索实现已在 `app/services/retrieval_service.py` |
| `configs/prompts/` | 空目录，提示词实际在 `kb_prompt` 表 |

**验收**：`grep -r "capability.retrieval\|legacy/index" --include=*.py --include=*.js --include=*.vue` 无命中；后端启动正常。

---

### ⑨ README 修正

| 位置 | 改法 |
|---|---|
| `README.md:238` | 去掉 `--reload`，改为 `-m app.main`（与本机 Windows 重载失灵一致） |
| `README.md:17` | Ollama 描述改为「已关闭，代码保留以便恢复」 |
| `README.md:11`、`:209` | Python 版本统一为「3.12+（本机 3.14 实测可用）」 |
| `README.md:188-191` | 组件树补 `MedSummary.vue`，views 列表与 `frontend/src/views/` 对齐 |
| `README.md:63` | 归属描述改为「案件可读全员；写操作限承办人或管理员」 |
| `README.md:202` | 删除不存在的 `说明.md` |
| `README.md` 快速开始 | 补 `DEMO_SEED`、`CORS_ORIGINS` 与种子账号说明 |

**验收**：README 中每条命令可照抄执行；`说明.md` 不再出现。

---

### ⑩ 补齐 `requests`

`requirements.txt` 增加 `requests==2.34.2`（与 `.venv` 实测版本一致）。Docker 镜像不受影响（`scripts/` 不复制进镜像）。

**验收**：干净 venv 中 `pip install -r requirements.txt` 后 `python -c "import requests"` 成功。

---

### ⑪ 前端 test 脚本

`frontend/package.json` 的 `scripts` 增加 `"test": "vitest run"`。

**验收**：`cd frontend && npm test` 通过。

---

### ⑫ `.env.example` 补全

补齐：`EMBEDDING_API_KEY`、`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL`、`CHROMA_PATH`、`CORS_ORIGINS`、`DEMO_SEED`。删除或注明 `OLLAMA_*` 已停用。

**验收**：照 `.env.example` 全量复制为 `.env` 后，`python -m app.main` 启动日志无「embedding 未配置」类报错。

---

### ⑬ `scripts/` 纳管

**现状**：`.gitignore:22-24` 忽略整个 `scripts/`；目录 78 个文件、24.7 MB，其中 `_parent_refresh.npz` 18.8 MB、13 张截图 5.7 MB、48 个一次性探针。

**目标行为**：

1. `.gitignore` 删除 `scripts/` 整目录规则，改为：
   ```
   scripts/_scratch/
   scripts/_shots/
   scripts/_chroma_test/
   scripts/__pycache__/
   scripts/*.npz
   ```
2. 48 个临时探针移入 `scripts/_scratch/`（不删除，只是不入库）：`_probe_*`、`_calibrate*`、`_calib2.json`、`verify_step*`、`verify_ui_*`、`_shots/`、`_chroma_test/`、`_flags.txt`、`_negqueries.txt`、`_negrecall.txt`、`Professional_stock_photography_*.png`。
3. 入库清单：5 个 `test_*_e2e.py`、8 个 `_smoke_*.py`、`retrieval_eval.py` + `retrieval_queries.json` + `_eval200_baseline.txt` + `_eval200_final.txt`、导入/运维 12 个（`import_*`、`fix_law_category`、`cleanup_db`、`reset_sessions`、`_clean_ghost_cases`、`_purge_session_msgs_cache`、`_refresh_parent_cases`、`_import_parent_cases`、`seed_demo_cases`、`backfill_seed_cases`）、`_verify_http_session_order.py`、本轮新增 `_smoke_hardening.py`。
4. 入库文件脱敏：
   - 公网 IP（`_smoke_deploy_check.py:18`、`_verify_http_session_order.py:4`）→ 读 `SMOKE_BASE_URL`，缺省 `http://127.0.0.1:8000`
   - 默认管理员凭据（`_verify_http_session_order.py:17`、`_smoke_status_http.py:19`、`_smoke_deploy_check.py:30`）→ 读 `SMOKE_USER` / `SMOKE_PASSWORD`，未设置则打印跳过并 `return`
   - 云端会话 ID（`_verify_http_session_order.py:13-15`）→ 删除字面量，改为运行时创建会话
   - 数据路径（`import_local_cases.py:23`、`verify_step4_parser.py:13`）→ `CASE_DATA_DIR` 环境变量，缺省保留现路径

**验收**：
- `git status --ignored scripts/` 只剩 `_scratch/`、`_shots/`、`_chroma_test/`、`__pycache__/`、`*.npz`
- `git ls-files scripts/ | wc -l` 在 26~30 之间
- `grep -r "39.107.157.0" scripts/` 无命中（`_scratch/` 除外）
- 入库脚本中无明文密码字面量

---

## 5. 验证策略

全部改动完成后一次性执行。**必跑**：

| # | 验证项 | 命令 / 方法 | 通过标准 |
|---|---|---|---|
| V1 | 启动完整性 | `python -m app.main` | 9 个 `init_tables` 全过，无 error 级日志 |
| V2 | 权限回归 | `python scripts/test_api_e2e.py` | 全 PASS |
| V3 | 写权限矩阵 | 手工 HTTP：u_003 改 u_002 案件 | 403；admin 改 → 200 |
| V4 | Redis 降级 | `python scripts/_smoke_hardening.py` | 打桩断言全 PASS |
| V5 | 会话链路 | 真实 Redis：建会话→发消息→读回→删除 | 数据一致，无 500 |
| V6 | 前端单测 | `cd frontend && npm test` | 通过 |
| V7 | 播种开关 | 空库 + 不设/设置 `DEMO_SEED` | 分别 0 行 / 8 行 |
| V8 | 残留扫描 | `grep -rn "3112028466" app/ frontend/src/` 与 `grep -n 'allow_origins' app/main.py` | 前者无命中；后者不再出现 `["*"]` |

**不跑**：`test_intake_e2e.py`、`test_documents_e2e.py`（真实 LLM），`retrieval_eval.py`（200 条评测）。

新增 `scripts/_smoke_hardening.py` 的断言范围：① 权限函数三种身份（admin / 本人 / 他人）、③ Redis 写降级打桩、⑥ 邮箱文案残留、⑦ 规则接口依赖类型。纯函数级，不打真 LLM。

---

## 6. Review Focus

以下五类风险本 spec 未在自动化断言中完整覆盖，实现时需人工确认：

1. **写权限误伤正常流程** — 复核退回补充后，承办人若在另一账号下编辑要素，会被 403；需确认 `review_followup` 链路仍走原承办人账号。
2. **`user` 建表顺序** — 若 `auth.init_tables()` 排在 `assist.init_tables()` 之后，空库启动时外键建表失败，且只在 warning 里可见。
3. **CORS 默认关闭的副作用** — 若有人用 `file://` 或独立部署的前端访问，会被浏览器拦截且错误信息晦涩。
4. **Redis 写降级掩盖真实故障** — 长期 Redis 挂掉只留 warning，会话列表退化为 MySQL 查询，性能下降但无告警。
5. **scripts 纳管带入环境耦合** — 入库脚本仍依赖 `D:\Data\mingjing`、Chrome 路径等本机环境，换机器运行时需改环境变量。

---

## 7. 风险与回滚

- 所有改动分 3 个 commit，任一 commit 可独立 `git revert`。
- 数据库只做 `CREATE TABLE IF NOT EXISTS`，不触碰现有数据；回滚只需撤销代码，无数据迁移。
- `scripts/` 纳管不重写历史，仅新增提交。
- 若 V1 失败，最先怀疑 `auth.init_tables()` 的调用位置与 `user` 列定义。

---

## 8. 执行顺序

1. 安全 ①—⑦ → 提交
2. 卫生 ⑧—⑫ → 提交
3. scripts ⑬ + `_smoke_hardening.py` → 提交
4. 跑 V1—V8
5. 全绿后由用户决定是否推送