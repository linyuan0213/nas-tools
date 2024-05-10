#!/bin/sh
# 停止 gunicorn
# gunicorn 关闭后不会自动删掉pid文件，这里自行删掉
pid_dir=$(dirname $NASTOOL_CONFIG)
cd $pid_dir
for id in `cat gunicorn.pid`;do
kill -TERM $id
done
rm -f gunicorn.pid

# 停止文件监控
# 获取指定进程的PID
PID=$(pgrep -f "python config_monitor.py")

# 检查进程是否正在运行
if [ -z "$PID" ]; then
    echo "进程未找到或未运行."
    exit 1
fi

# 向进程发送终止信号
kill -TERM $PID

echo "进程已停止."