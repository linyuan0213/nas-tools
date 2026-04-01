import os

import log
from app.utils.temp_manager import temp_manager


class TempCleanupHelper:
    """
    临时文件定期清理助手
    负责定时清理过期的临时文件
    """

    # 默认文件保留时间：24小时
    DEFAULT_MAX_AGE_HOURS = 24
    # 排除的目录/文件模式（保留不清理）
    EXCLUDE_PATTERNS = ["signin", "backup_temp"]

    @staticmethod
    def do_cleanup():
        """
        执行清理任务
        """
        try:
            log.info("【TempCleanupHelper】开始执行临时文件清理...")

            # 获取清理前的大小
            size_before = temp_manager.get_temp_size_human()

            # 执行清理
            deleted_count = temp_manager.cleanup_old_files(
                max_age_hours=TempCleanupHelper.DEFAULT_MAX_AGE_HOURS,
                exclude_patterns=TempCleanupHelper.EXCLUDE_PATTERNS
            )

            # 获取清理后的大小
            size_after = temp_manager.get_temp_size_human()

            if deleted_count > 0:
                log.info(f"【TempCleanupHelper】清理完成：删除 {deleted_count} 个文件，"
                        f"大小从 {size_before} 变为 {size_after}")
            else:
                log.debug(f"【TempCleanupHelper】没有需要清理的临时文件，当前大小: {size_after}")

        except Exception as e:
            log.error(f"【TempCleanupHelper】执行清理任务出错: {str(e)}")

    @staticmethod
    def get_temp_info():
        """
        获取临时目录信息
        :return: 字典包含大小和文件数量
        """
        try:
            temp_path = temp_manager.get_temp_path()
            if not os.path.exists(temp_path):
                return {"size": "0 B", "count": 0, "path": temp_path}

            # 计算文件数量
            file_count = 0
            for _, _, files in os.walk(temp_path):
                file_count += len(files)

            return {
                "size": temp_manager.get_temp_size_human(),
                "count": file_count,
                "path": temp_path
            }
        except Exception as e:
            log.error(f"【TempCleanupHelper】获取临时目录信息失败: {str(e)}")
            return {"size": "unknown", "count": -1, "path": temp_manager.get_temp_path()}
