import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

class Config:
    # 云端 LLM（值统一写在 .env 中，这里只读变量名）
    CLOUD_API_KEY = os.getenv("CLOUD_LLM_API_KEY", "")
    CLOUD_BASE_URL = os.getenv("CLOUD_LLM_BASE_URL", "https://api.deepseek.com")
    CLOUD_MODEL = os.getenv("CLOUD_LLM_MODEL", "deepseek-chat")

    # 本地兜底
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    # MySQL
    MYSQL = {
        "host": os.getenv("MySQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MySQL_PORT", "3306")),
        "user": os.getenv("MySQL_USER", "root"),
        "password": os.getenv("MySQL_PASSWORD", "1234"),
        "database": os.getenv("MySQL_DATABASE", "mingjing"),
        "charset": os.getenv("MySQL_CHARSET", "utf8mb4"),
    }

    # ===== JWT 认证（单 token 方案）=====
    # 签名密钥：生产环境用 python -c "import secrets;print(secrets.token_hex(32))" 生成并覆盖
    JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-secret-change-me")
    JWT_ALGORITHM = "HS256"                         # 对称签名：一把密钥既签名又验签
    ACCESS_EXPIRE_HOURS = int(os.getenv("JWT_ACCESS_EXPIRE_HOURS", "24"))  # token 24 小时有效

    # Redis
    REDIS = {
        "host": os.getenv("REDIS_HOST", "127.0.0.1"),
        "port": int(os.getenv("REDIS_PORT", "6379")),
        "db": int(os.getenv("REDIS_DB", "0")),
        "password": os.getenv("REDIS_PASSWORD", "") or None,  # 空密码转 None
        "decode_responses": True,   # 自动 bytes→str
    }

    # 阿里云 OSS（对象存储：法条原文备份、附件、导出文书）
    OSS = {
        "access_key_id": os.getenv("OSS_ACCESS_KEY_ID", ""),
        "access_key_secret": os.getenv("OSS_ACCESS_KEY_SECRET", ""),
        "endpoint": os.getenv("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com"),
        "bucket": os.getenv("OSS_BUCKET", "mingjing-01"),
    }

config = Config()
