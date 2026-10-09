---
name: bm25-oom-pitfall
description: BM25 混合检索云端 OOM 问题根因、修复与知识点
metadata:
  type: reference
---

# BM25 混合检索云端 OOM 与降级修复纪实

## 问题现象

| 环境 | 提问"买卖100张身份证怎么判决" | 提问"非法有枪怎么判决" |
|------|------------------------------|----------------------|
| **本地开发机** (64GB, 16核) | ✅ 找到刑法280条第3款 + 类案 | ✅ 散件折算规则 + 案例 |
| **云端服务器** (2C4G) | ❌ 仅找到1条相关法条,其余引用为民间借贷/寻衅滋事等 | ❌ 法条缺失,引用完全不相关 |

## 根因分析

### 直接原因：BM25 同步阻塞加载

原代码 `bm25_service.py` 使用 `ensure_loaded()` 同步加载：

```python
# ❌ 旧代码：同步阻塞
def ensure_loaded(self):
    if self._laws_bm25 is not None:
        return
    # 从这里开始,请求线程被阻塞直到 59K 法条全部建完索引
    laws = query("SELECT ... FROM law")     # 59K 条
    for row in laws:
        tok.append(jieba.lcut(head + text)) # jieba 分词
    self._laws_bm25 = BM25Okapi(tok)        # 构建 BM25
```

在 2C4G 上,59K 法条 jieba 分词耗时 **30-60 秒**。此期间：

1. **主线程卡死**：`ensure_loaded()` 未完成之前,sync def 不返回 → Uvicorn worker 无法处理新请求
2. **OOM 隐患**：jieba 分词 + 59K 文本 + BM25 索引同时驻留内存,4GB RAM 吃紧
3. **级联崩溃**：请求超时后客户端重试 → 更多 worker 排队 → 内存耗尽 → 进程被 kernel OOM killer 杀死 → 容器退出 → 整个服务不可用

### 间接原因：数据膨胀

`law` 表有 **59,443 条**,但实际有效法条约 5,000-8,000 条。多出的是同一部法律的多次修正版本（如《民事诉讼法》2012/2017/2021 三版并存）。MySQL SELECT 全量读取时全部载入内存,加剧了 OOM。

### 为什么本地不卡？

| 维度 | 本地开发机 | 云端服务器 |
|------|-----------|-----------|
| CPU | 16核 (i7-12700) | 2核 (ECS 通用型) |
| 内存 | 64GB | 4GB |
| 并发请求 | 1个 | 多个用户并发 |
| 首次加载 | jieba 秒级完成 | jieba 需 30-60s |

本地配置远超需求,BM25 加载耗时 ~1 秒,感知不到阻塞。

## 修复方案

### 代码修复：异步预加载 + 未就绪降级

```python
# ✅ 新代码：后台线程异步加载,请求不阻塞
class BM25Service:
    def __init__(self):
        self._ready_event = threading.Event()
        threading.Thread(target=self._load, daemon=True).start()

    def search_laws(self, query, top_k=10):
        if not self._ready_event.is_set():
            return []  # ← 核心：未就绪时空返回,降级为纯向量检索
        # ... 正常 BM25 检索

    def _load(self):
        # ... 读 MySQL + jieba 分词 + 建索引
        self._ready_event.set()  # 加载完毕通知
```

核心改动：
- `__init__` 中启动 `daemon=True` 后台线程
- `search_laws/search_cases` 检查 `_ready_event`,未就绪时返回空列表
- 检索层 `retrieval_service.py` 的 `_rrf_fuse` 自然处理空 BM25 结果 → 降级为纯向量检索
- `reload_bm25()` 创建新实例即可触发后台重加载

### 线程安全设计

```python
from threading import Event

_ready_event = threading.Event()
# Event 的特性:
# - is_set(): 非阻塞检查状态
# - wait():   阻塞直到 set()（仅 ensure_loaded 用）
# - set():    原子操作,多线程安全
```

### 数据治理建议（可选）

减少 law 表冗余可加速 BM25 加载：

```sql
-- 查看同一部法律有多少版本
SELECT source, COUNT(*) FROM law GROUP BY source HAVING COUNT(*) > 1;
```

当前 59K 条中大量为同一法律的多次修正。若清理到 5K-8K 有效条目,BM25 加载可从 **30-60s 降到 2-4s**。

## 知识点文档

### 1. 同步 vs 异步加载

| | 同步加载 | 异步加载（后台线程） |
|--|---------|-------------------|
| 调用方感受 | 阻塞等待 | 立即返回/稍后重试 |
| 错误隔离 | 失败则请求失败 | 失败不影响当前请求 |
| 适用场景 | 加载 < 100ms | 加载 > 1s |

### 2. Python 线程安全原语

| 原语 | 特性 | 适用 |
|------|------|------|
| `threading.Event` | 单次信号,set 后永久 `is_set()` | 就绪通知 |
| `threading.Lock` | 互斥访问 | 写保护 |
| `threading.Condition` | 等待特定条件 | 复杂同步 |
| `threading.Barrier` | 多线程同步点 | 分阶段加载 |

本项目选用 `Event`：加载完成 `set()` → `search_*` 检查 `is_set()` → 未就绪降级。

### 3. daemon 线程

```python
threading.Thread(target=load, daemon=True).start()
```

- `daemon=True`：主线程退出时自动杀死,不留孤儿进程
- 反之 `daemon=False` 的子线程会阻止 Python 退出
- 适用于后台加载、心跳、监控等"随主进程生死"的场景

### 4. Docker OOM 与 restart policy

```yaml
# docker-compose.yml
restart: unless-stopped
```

- **OOM kill** 会杀死容器进程,Docker 根据 restart policy 重启
- **但** 如果 OOM 发生在 host 层面（宿主机内存耗尽）,dockerd 也可能被 kill,此时需要阿里云控制台手动重启 ECS
- 查看 OOM 日志：`docker inspect <container> | grep -i oom`

### 5. BM25 工作原理

- **BM25Okapi** 是经典概率检索模型,基于词频(TF)和逆文档频率(IDF)
- **jieba** 中文分词：将"非法持有枪支弹药"切为 `["非法","持有","枪支","弹药"]`
- 每个词的 `IDF = log(文档总数 / 包含该词的文档数)`——「枪支」在 59K 法律中只出现在少数法条,IDF 高,关键词配效果好
- 对比向量检索：「枪支」+「弹药」的语义嵌入可能找到"武器""暴力"等近义词,但可能偏离法律条文的精确措辞

### 6. 检索质量对比

| 检索方式 | 优点 | 缺点 |
|---------|------|------|
| 纯向量（Chroma） | 语义理解,找近义词 | 精度不够,常返回"形似神不似" |
| 纯 BM25 | 精确关键词匹配 | 无法处理同义词/近义词 |
| 混合（RRF 融合） | 两路互补,召回率高 | 需要两路都可用 |

## 预防措施

1. **任何慢启动必须异步**：首次加载 > 1s 的操作就必须后台执行
2. **降级策略**：新功能不可用时系统应优雅降级,而非崩溃
3. **2C4G 的容量规划**：
   - Python Web 服务 + Chroma ≈ 1-2GB RSS
   - BM25 索引 ≈ 200-400MB
   - 剩余内存约 1.5-2GB,留足 buffer
4. **监控**：生产环境应有 OOM 告警,发版前做容量测试

## 相关文件

- `app/services/bm25_service.py` — BM25 服务（包含异步加载逻辑）
- `app/services/retrieval_service.py` — 检索层（RRF 融合）
- `docker-compose.yml` — 容器重启策略配置
- [[mingjing-cloud-deploy]] — 云端部署信息