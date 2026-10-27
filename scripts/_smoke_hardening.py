"""本轮加固的纯函数级回归断言。用法：.venv/Scripts/python.exe scripts/_smoke_hardening.py"""
import pathlib
import sys
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from fastapi import HTTPException

from app.core.db import MySQLClient


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
    assert c["assignee_user_id"], "测试前置：取到的案件必须有承办人"
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
        assert_case_writer("AJ9999-00000", other)
        raise AssertionError("不存在案件应 404")
    except HTTPException as e:
        assert e.status_code == 404


def test_cors_reads_config():
    from app.core.config import config
    assert isinstance(config.CORS_ORIGINS, list)
    from app.main import app
    cors = [m for m in app.user_middleware if m.cls.__name__ == "CORSMiddleware"][0]
    assert cors.kwargs["allow_origins"] == config.CORS_ORIGINS
    assert cors.kwargs["allow_credentials"] is bool(config.CORS_ORIGINS)


def test_redis_write_degrades():
    import logging

    from app.services import session_service as ss

    class _Boom:
        def __getattr__(self, _):
            raise ConnectionError("redis down")

    class _Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.msgs = []

        def emit(self, record):
            self.msgs.append(record.getMessage())

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


def test_no_hardcoded_admin_email():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    hits = [p for p in list(root.joinpath("app").rglob("*.py"))
                  + list(root.joinpath("frontend/src").rglob("*.vue"))
                  if "3112028466" in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits == [], hits


def test_rules_admin_only():
    from app.api import kb
    route = next(r for r in kb.router.routes
                 if getattr(r, "path", "") == "/admin/rules" and "PUT" in r.methods)
    deps = [d.call.__name__ for d in route.dependant.dependencies if d.call]
    assert "require_admin" in deps, deps


def test_scripts_no_secrets():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    bad = []
    for p in root.joinpath("scripts").rglob("*.py"):
        if "_scratch" in p.parts or p.name == "_smoke_hardening.py":
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if "39.107.157.0" in txt:
            bad.append(f"{p.name}: 公网 IP")
        if "sess_08bf" in txt:
            bad.append(f"{p.name}: 云端会话 ID")
    assert bad == [], bad


def test_user_table_collation_matches_assist():
    """新库建 user 表后，assist_session 的外键必须能建（两表 collation 一致）。"""
    import pymysql
    from app.core.config import config

    m = config.MYSQL
    c = pymysql.connect(**m)
    c.cursor().execute(
        "CREATE DATABASE IF NOT EXISTS mingjing_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    c.commit(); c.close()

    orig = m["database"]
    m["database"] = "mingjing_test"
    try:
        from app.api import assist, auth
        auth.init_tables()
        try:
            assist.init_tables()
        except Exception as e:
            raise AssertionError(f"assist 建表失败（collation 不匹配）: {e}")
        c = pymysql.connect(**m); cur = c.cursor()
        cur.execute("SHOW TABLES LIKE 'assist_session'")
        assert cur.fetchone(), "assist_session 未创建"
        c.close()
    finally:
        m["database"] = orig
        c = pymysql.connect(**config.MYSQL)
        c.cursor().execute("DROP DATABASE IF EXISTS mingjing_test"); c.commit(); c.close()


def test_script_safety_guards():
    """审查发现的脚本安全门：无悬空变量、清库需显式确认、重写评测集先备份。"""
    import pathlib
    d = pathlib.Path(__file__).resolve().parent
    sess = (d / "_verify_http_session_order.py").read_text(encoding="utf-8")
    assert "CLEARED" not in sess, "会话顺序脚本仍引用已删除的 CLEARED"
    oss = (d / "import_oss_kb.py").read_text(encoding="utf-8")
    assert "CONFIRM_PURGE" in oss, "OSS 补库脚本缺少清库确认门"
    fix = (d / "_fix_labels.py").read_text(encoding="utf-8")
    assert ".bak" in fix, "评测集重写脚本缺少备份"


def test_scripts_no_plaintext_password():
    """spec ⑬ 验收项：入库脚本中不得有明文口令字面量。"""
    import pathlib
    import re

    d = pathlib.Path(__file__).resolve().parent
    pat = re.compile(r"""(?i)\b(password|passwd|pwd)\s*=\s*["'][^"']+["']""")
    bad = []
    for p in list(d.rglob("*.py")) + list(d.rglob("*.json")) + list(d.rglob("*.txt")):
        if "_scratch" in p.parts or p.name == "_smoke_hardening.py":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if pat.search(line):
                bad.append(f"{p.name}:{i}")
    assert bad == [], bad


TESTS = [
    test_assert_case_writer,
    test_cors_reads_config,
    test_redis_write_degrades,
    test_user_table_and_seed,
    test_demo_seed_off_by_default,
    test_no_hardcoded_admin_email,
    test_rules_admin_only,
    test_scripts_no_secrets,
    test_user_table_collation_matches_assist,
    test_script_safety_guards,
    test_scripts_no_plaintext_password,
]


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