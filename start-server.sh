#!/bin/sh
# 激活虚拟环境
. .venv/bin/activate
# 启动后创建gunicorn.pid文件
gunicorn run:App -c gunicorn.conf.py
