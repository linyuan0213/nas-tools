# gunicorn.conf.py
import os
import hashlib
import random
import ruamel.yaml
import shutil

os.environ['SERVER_INSTANCE'] = hashlib.md5(str(random.random()).encode()).hexdigest()

config = os.environ.get('NASTOOL_CONFIG')
if not config:
    print("环境变量 NASTOOL_CONFIG 不存在")
    os._exit(-1)

if not os.path.exists(config):
    os.makedirs(os.path.dirname(config), exist_ok=True)
    cfg_tp_path = os.path.join('./config', "config.yaml")
    shutil.copy(cfg_tp_path, config)
    print("【Config】config.yaml 配置文件不存在，已将配置文件模板复制到配置目录...")
ssl_cert = ''
ssl_key = ''
with open(config, 'r') as f:
    try:
        yaml = ruamel.yaml.YAML()
        cf = yaml.load(f)
        ssl_cert = cf.get('app').get('ssl_cert')
        ssl_key = cf.get('app').get('ssl_key')
    except Exception as e:
        print("【Config】config.yaml 异常请删除重新配置...")

ROOT_PATH = os.path.dirname(os.path.abspath(config))
LOG_PATH = os.path.join(ROOT_PATH, 'logs')
if not os.path.exists(LOG_PATH):
    os.makedirs(LOG_PATH)

port = os.environ.get('NT_PORT') if os.environ.get('NT_PORT') else 3000

bind = f'[::]:{port}'  # 绑定ip和端口号
timeout = 60  # 超时
daemon = False  # 是否后台运行
debug = False
workers = 1  # 进程数
worker_class = "gthread"
threads = 10  # 指定每个进程开启的线程数
loglevel = 'info'  # 日志级别，这个日志级别指的是错误日志的级别，而访问日志的级别无法设置
pidfile = os.path.join(ROOT_PATH, "gunicorn.pid")  # 存放Gunicorn进程pid的位置，便于跟踪

access_log_format = '%(t)s %(p)s %(h)s "%(r)s" %(s)s %(L)s %(b)s %(f)s" "%(a)s"'  # 设置gunicorn访问日志格式，错误日志无法设置
accesslog = os.path.join(LOG_PATH, "gunicorn_access.log")  # 访问日志文件
errorlog = '-'  # 错误日志文件
graceful_timeout = 10
keyfile = ssl_key
certfile = ssl_cert
