#!/bin/sh
# 启动后创建gunicorn.pid文件
.venv/bin/gunicorn run:App -c gunicorn.conf.py
