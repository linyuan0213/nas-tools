#!/bin/sh
# gunicorn 关闭后不会自动删掉pid文件，这里自行删掉
pid_dir=$(dirname $NASTOOL_CONFIG)
cd $pid_dir
for id in `cat gunicorn.pid`;do
kill -HUP $id
done
