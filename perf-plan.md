# 明镜性能优化 Plan（2026-10-27）

**目标**：热态首 token 从基线 ~1.5s 压到 ~1.0s；接口 P50 降低 30~50%；不做 rerank、不换模型、不牺牲准确率。

**基准**：本机热态（用户选定：直接按本机数据开改，云端数字等下次部署再验证）。云端为最终验收口径。

**测量方法**：每批改动前后跑 `tests/_perf_check.py`（连接复用、缓存命中、接口 P50），并各跑 3 次真实提问取中位数。真实提问仅用于首 token 对比，费用可接受。

## 已定范围

| 组 | 内容 | 状态 |
|---|---|---|
| A | MySQL 连接池、`count()` 缓存、`/stats/kb` 结果缓存 | 本批 |
| C | 前端路由级 code-split、登录背景图压缩 | 本批 |
| B | BM25 索引落盘 + `_load` 守卫、检索 embedding LRU、FC 触发收紧 | 紧随 |
| D | embedding 出口 / 保活策略 | 跳过，等云端基线 |
| — | Chroma 案例子块独立 Collection | 跳过，重灌成本另议 |

## 验收阈值

| 指标 | 基线 | 目标 |
|---|---|---|
| 热态首 token | 1.45~1.55s | ≤ 1.1s |
| `GET /cases` P50 | 61.7ms | ≤ 35ms |
| `GET /cases/{id}` P50 | 62.6ms | ≤ 35ms |
| 新会话首问 DB 段 | ~124ms | ≤ 20ms |
| 前端 JS gzip | 467KB | ≤ 320KB |
| 登录页背景图 | 306KB | ≤ 120KB |
| BM25 就绪时间 | ~50s | ≤ 5s（落盘后） |

## A1 MySQL 连接池

- 改动：`app/core/db.py` 内部改为 `queue.LifoQueue` 连接池（默认 20），取出时 `ping(reconnect=True)`，归还前 `rollback()` 丢弃未提交事务；池满则关闭多余连接。**对外接口 `MySQLClient()` / `.execute()` / `.commit()` / `.close()` 完全不变**，调用方零改动。
- 测量：`_perf_check.py` 断言两次 `MySQLClient()` 复用同一连接对象；`GET /cases` P50。
- 风险：未提交事务在归还时被回滚——与旧行为（close 即回滚）一致；临时表会跨请求残留——全仓无 `CREATE TEMPORARY`，不适用。
- 回滚：单文件改动，`git revert` 即可。

## A2 `count()` 缓存

- 改动：`app/services/vector_service.py` 增加 `count_cached(name, ttl=60)`，`retrieval_service` 的两处 `count()` 改用它。
- 测量：一次 `retrieve()` 内两次 count 的耗时；冷/热。
- 风险：灌库后计数最多过期 60s，不影响召回。

## A3 `/stats/kb` 结果缓存

- 原计划「给 `law(category)` 加索引」，但实测该索引已存在（`idx_category`），66ms 是 59k 行 GROUP BY 本身。改为**接口结果缓存 30s**。
- 改动：`app/api/stats.py` 模块级 `(payload, ts)` 缓存。
- 测量：连续两次 `GET /stats/kb` 的 P50。
- 风险：新增数据最多延迟 30s 出现在统计页。

## C1 前端 code-split

- 改动：`frontend/src/App.vue` 的 7 个视图改为 `defineAsyncComponent`，ECharts 随 StatsView 进入独立 chunk。
- 测量：构建后 `dist/assets/*.js` 体积；首屏实际加载的 chunk 数。
- 风险：首次切到某页多一次 chunk 加载（<100ms）。

## C2 登录背景图压缩

- 改动：`login-bg.jpg` 转 WebP（质量 80）或降分辨率到 1600px 宽，保留 JPG 兜底。
- 测量：文件体积。
- 风险：低版本浏览器不支持 WebP；保留 `<picture>` 或直接用 JPG 压缩。

## B1 BM25 索引落盘

- 改动：`bm25_service._load` 先尝试读 `data/bm25_cache.pkl`（分词后的 token 列表 + 文档数据 + 版本号）；版本号取 `law/case_ref` 的 `COUNT(*)` 与 `MAX(id)`。不匹配则重建并落盘。`_load` 整体加 try/except，失败记 error 并让 `ready` 保持 False（行为与现在一致，但日志可见）。
- 测量：冷启动到 `ready` 的时间。
- 风险：缓存与 MySQL 不同步时多一次全量重建；pickle 文件损坏则删除重建。

## B2 检索 embedding LRU

- 改动：`app/services/retrieval_service.py` 对查询 embedding 加 `functools.lru_cache(maxsize=500)`（key 为 query 原文）。只缓存查询向量，不缓存最终材料。
- 测量：同一问题连续两次 `retrieve()` 的耗时差。
- 风险：模型/维度变更后需重启；单条 4KB，500 条约 2MB。

## B3 FC 触发收紧

- 现状：`_DB_QUERY_PATTERN` 命中（如「多少…法律」）时先做一次非流式 LLM 工具调用，再流式生成，多 0.6~1.5s。
- 改动：仅收紧**明显非 DB 问句**的误命中（如纯概念解释），不改需要工具的路径。
- 测量：用 10 条典型问句（5 条 DB、5 条概念）测 `_DB_QUERY_PATTERN` 命中率，要求 DB 类 5/5 命中、概念类命中 ≤1。
- 风险：误伤确实需要全库统计的问句；用测试集兜底。

## 执行顺序

1. 写 `tests/_perf_check.py`（先红后绿）
2. A1 → A2 → A3 → 跑 e2e 回归
3. C1 → C2 → 构建验证
4. B1 → B2 → B3 → 跑加固断言 + e2e
5. 总测量，对比阈值，输出结果表