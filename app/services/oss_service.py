"""阿里云 OSS 服务：文件上传/下载/删除/列表。

依赖：oss2（已加入 requirements.txt）
用法：
    from app.services.oss_service import upload_file, download_file, list_files
"""
import oss2

from app.core.config import config

# 惰性初始化，避免模块加载时就连接（启动预热不依赖 OSS）
_bucket = None


def _get_bucket() -> oss2.Bucket:
    global _bucket
    if _bucket is None:
        auth = oss2.Auth(config.OSS["access_key_id"], config.OSS["access_key_secret"])
        _bucket = oss2.Bucket(auth, config.OSS["endpoint"], config.OSS["bucket"])
    return _bucket


def upload_file(key: str, data: bytes) -> str:
    """上传字节流到 OSS。key=文件路径（如 laws/民法典.md），返回访问 URL"""
    bucket = _get_bucket()
    bucket.put_object(key, data)
    # 公共读 bucket 可直接拼接 URL；私有 bucket 需用 sign_url
    return f"https://{config.OSS['bucket']}.{config.OSS['endpoint']}/{key}"


def upload_local_file(key: str, local_path: str) -> str:
    """上传本地文件到 OSS"""
    bucket = _get_bucket()
    with open(local_path, "rb") as f:
        bucket.put_object(key, f)
    return f"https://{config.OSS['bucket']}.{config.OSS['endpoint']}/{key}"


def download_file(key: str) -> bytes:
    """从 OSS 下载文件，返回字节流"""
    bucket = _get_bucket()
    result = bucket.get_object(key)
    return result.read()


def delete_file(key: str):
    """删除 OSS 上的文件"""
    bucket = _get_bucket()
    bucket.delete_object(key)


def list_files(prefix: str = "") -> list[dict]:
    """列出 OSS 上的全部文件（ObjectIterator 自动翻页，不受单页 1000 条上限约束）。

    prefix=前缀过滤（如 laws/）。max_keys 为每页大小，不影响总返回量。
    """
    bucket = _get_bucket()
    files = []
    for obj in oss2.ObjectIteratorV2(bucket, prefix=prefix, max_keys=500):
        files.append({
            "key": obj.key,
            "size": obj.size,
            "last_modified": obj.last_modified,
        })
    return files


def check_connection() -> bool:
    """验证 OSS 连接是否正常（尝试 list bucket）"""
    try:
        _get_bucket().list_objects(max_keys=1)
        return True
    except Exception:
        return False
