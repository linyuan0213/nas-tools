import os
import threading
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import NullPool

from app.db.models import Base
from app.utils import ExceptionUtils, PathUtils
from config import Config

lock = threading.Lock()
_Engine = create_engine(
    f"sqlite:///{os.path.join(Config().get_config_path(), 'user.db')}?check_same_thread=False",
    echo=False,
    poolclass=NullPool,
    connect_args={'timeout': 30}
)

# 启用 WAL 模式
with _Engine.connect() as conn:
    conn.execute(text("PRAGMA journal_mode=WAL;"))

_Session = scoped_session(sessionmaker(bind=_Engine,
                                       autoflush=True,
                                       autocommit=False,
                                       expire_on_commit=False))


class MainDb:

    @property
    def session(self):
        return _Session()

    def init_db(self):
        with lock:
            Base.metadata.create_all(_Engine)
            self.init_db_version()

    def init_db_version(self):
        """
        初始化数据库版本
        """
        try:
            self.excute("delete from alembic_version where 1")
            self.commit()
        except Exception as err:
            print(str(err))

    def init_data(self):
        """
        读取config目录下的sql文件，并初始化到数据库，只处理一次
        """
        config = Config().get_config()
        init_files = Config().get_config("app").get("init_files") or []
        config_dir = Config().get_script_path()
        sql_files = PathUtils.get_dir_level1_files(in_path=config_dir, exts=".sql")
        config_flag = False
        for sql_file in sql_files:
            if os.path.basename(sql_file) not in init_files:
                config_flag = True
                with open(sql_file, "r", encoding="utf-8") as f:
                    sql_list = f.read().split(';\n')
                    for sql in sql_list:
                        try:
                            self.excute(sql)
                            self.commit()
                        except Exception as err:
                            print(str(err))
                init_files.append(os.path.basename(sql_file))
        if config_flag:
            config['app']['init_files'] = init_files
            Config().save_config(config)

    def insert(self, data):
        """
        插入数据
        """
        if isinstance(data, list):
            self.session.add_all(data)
        else:
            self.session.add(data)

    def query(self, *obj):
        """
        查询对象
        """
        return self.session.query(*obj)

    def excute(self, sql):
        """
        执行SQL语句
        """
        self.session.execute(text(sql))

    def flush(self):
        """
        刷写
        """
        self.session.flush()

    def commit(self):
        """
        提交事务
        """
        self.session.commit()

    def rollback(self):
        """
        回滚事务
        """
        self.session.rollback()


class DbPersist(object):
    def __init__(self, db):
        self.db = db

    def __call__(self, f):
        def persist(*args, **kwargs):
            try:
                ret = f(*args, **kwargs)
                self.db.commit()
                return ret if ret is not None else True
            except Exception as e:
                ExceptionUtils.exception_traceback(e)
                self.db.rollback()
                return False
            finally:
                # 确保 Session 关闭并重置
                self.db.session.close()
                _Session.remove()  # 清理 scoped_session
        return persist