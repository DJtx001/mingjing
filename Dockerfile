# 明镜·要素式智能受理系统 —— 应用镜像（后端 + 前端同源托管）
# 构建上下文 = 项目根（需先本地 npm run build 生成 frontend/dist）
FROM python:3.12-slim

# TZ 需 tzdata 支持（datetime.now() 显示北京时间；后端写入的时间/审计均依赖）
ENV PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖（国内 PyPI 源加速；chromadb 有 manylinux 预编译 wheel，无需编译工具链）
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY app/ ./app/
COPY frontend/dist/ ./frontend/dist/

EXPOSE 8000
# 必须 0.0.0.0（容器内 127.0.0.1 无法被端口映射转发）；单进程（reindex 状态在内存，禁多 worker）
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-graceful-shutdown", "3"]
