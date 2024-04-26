#!/bin/sh
# 启动后创建gunicorn.pid文件
gunicorn run:App -c gunicorn.conf.py