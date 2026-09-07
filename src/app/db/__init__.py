import log
from app.db.session import SessionManager


def init_db():
    """
    初始化数据库表结构
    数据库迁移（alembic upgrade head）由 Docker entrypoint 或部署脚本在启动前执行
    """
    log.console("开始初始化数据库表结构...")
    # create_all 幂等：仅创建缺失表。
    # 新模型（如 SITE_PARSE_HEALTH）由启动期模型导入注册进 metadata 后，
    # 既有部署随本次启动自动补建，无需额外迁移文件
    SessionManager().create_all()
    log.console("数据库表结构初始化完成")


def init_data():
    """
    初始化数据
    """
    log.console("开始初始化数据...")
    SessionManager().init_data()
    log.console("数据初始化完成")
