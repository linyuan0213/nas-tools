import pytest
from app.utils.json_utils import JsonUtils


class TestJsonUtilsIssue:
    """测试用户报告的问题"""

    def test_original_issue(self):
        """测试原始问题：路径错误导致匹配失败"""
        html_text = '{"code":0,"message":"success","data":{"id":5838,"uuid":"dffb27c6-cb11-4431-a955-2f2a864d64df","title":"Light the Night S03 1080p NF WEB-DL DDP 5.1 H.264-HHWEB","promotion":{"down_multiplier":1,"is_active":false,"is_global":false,"time_type":2,"type":1,"up_multiplier":1}}}'
        xpath_str = 'data.torrents.promotion.down_multiplier=0'
        
        # 原始代码的做法
        field = xpath_str.split('=')[0]
        result = JsonUtils.get_json_object(html_text, field)
        
        print(f"字段路径: {field}")
        print(f"查询结果: {result}")
        
        # 因为路径中有 torrents，但实际 JSON 中没有这一层，所以返回 None
        assert result is None, "错误的路径应该返回 None"

    def test_correct_path(self):
        """测试正确的路径"""
        html_text = '{"code":0,"message":"success","data":{"id":5838,"uuid":"dffb27c6-cb11-4431-a955-2f2a864d64df","title":"Light the Night S03 1080p NF WEB-DL DDP 5.1 H.264-HHWEB","promotion":{"down_multiplier":1,"is_active":false,"is_global":false,"time_type":2,"type":1,"up_multiplier":1}}}'
        
        # 正确的路径（去掉 torrents）
        correct_field = 'data.promotion.down_multiplier'
        result = JsonUtils.get_json_object(html_text, correct_field)
        
        print(f"正确字段路径: {correct_field}")
        print(f"查询结果: {result}")
        
        # 正确的路径应该返回 1
        assert result == 1, f"期望值 1，实际值 {result}"

    def test_value_check(self):
        """测试值检查逻辑"""
        html_text = '{"code":0,"message":"success","data":{"id":5838,"uuid":"dffb27c6-cb11-4431-a955-2f2a864d64df","title":"Light the Night S03 1080p NF WEB-DL DDP 5.1 H.264-HHWEB","promotion":{"down_multiplier":1,"is_active":false,"is_global":false,"time_type":2,"type":1,"up_multiplier":1}}}'
        xpath_str = 'data.promotion.down_multiplier=0'
        
        # 分离字段和期望值
        parts = xpath_str.split('=')
        field = parts[0]
        expected_value = parts[1] if len(parts) > 1 else None
        
        # 获取实际值
        actual_value = JsonUtils.get_json_object(html_text, field)
        
        print(f"字段: {field}")
        print(f"期望值: {expected_value}")
        print(f"实际值: {actual_value}")
        
        # 转换为相同类型进行比较
        if expected_value is not None:
            # 尝试将期望值转换为与实际值相同的类型
            try:
                if isinstance(actual_value, bool):
                    expected_value = expected_value.lower() == 'true'
                elif isinstance(actual_value, int):
                    expected_value = int(expected_value)
                elif isinstance(actual_value, float):
                    expected_value = float(expected_value)
            except (ValueError, AttributeError):
                pass
        
        is_match = actual_value == expected_value
        print(f"是否匹配: {is_match}")
        
        # 实际值是 1，期望值是 0，所以不匹配
        assert not is_match, "值不匹配应该返回 False"
        assert actual_value == 1
        assert expected_value == 0
