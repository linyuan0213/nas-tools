# -*- coding: utf-8 -*-
"""
测试 RequestUtils 在使用 session 时正确传递 headers
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.utils.http_utils import RequestUtils


class TestRequestUtilsHeaders:
    """测试 RequestUtils 的 headers 传递问题"""

    def setup_method(self):
        """每个测试方法前清除 session 缓存"""
        RequestUtils._session_pool.clear()

    def test_get_res_with_session_includes_headers(self):
        """测试 get_res 方法在使用 session 时传递 headers"""
        headers = {'authorization': 'Bearer test_token_123'}
        
        with patch('app.utils.http_utils.requests.Session') as MockSession:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.text = '{"code": 200}'
            mock_response.status_code = 200
            mock_session.get.return_value = mock_response
            MockSession.return_value = mock_session
            
            # 创建 RequestUtils 实例（会使用共享 session）
            utils = RequestUtils(headers=headers)
            res = utils.get_res('http://example.com/api')
            
            # 验证 session.get 被调用时包含了 headers
            mock_session.get.assert_called_once()
            call_kwargs = mock_session.get.call_args[1]
            assert 'headers' in call_kwargs
            assert call_kwargs['headers'] == headers
    
    def test_post_res_with_session_includes_headers(self):
        """测试 post_res 方法在使用 session 时传递 headers"""
        headers = {'authorization': 'Bearer test_token_456'}
        
        with patch('app.utils.http_utils.requests.Session') as MockSession:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.text = '{"code": 200}'
            mock_response.status_code = 200
            mock_session.post.return_value = mock_response
            MockSession.return_value = mock_session
            
            # 创建 RequestUtils 实例（会使用共享 session）
            utils = RequestUtils(headers=headers)
            res = utils.post_res('http://example.com/api', json={'key': 'value'})
            
            # 验证 session.post 被调用时包含了 headers
            mock_session.post.assert_called_once()
            call_kwargs = mock_session.post.call_args[1]
            assert 'headers' in call_kwargs
            assert call_kwargs['headers'] == headers

    def test_get_with_session_includes_headers(self):
        """测试 get 方法在使用 session 时传递 headers"""
        headers = {'authorization': 'Bearer test_token_789'}
        
        with patch('app.utils.http_utils.requests.Session') as MockSession:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.text = '{"code": 200}'
            mock_response.status_code = 200
            mock_session.get.return_value = mock_response
            MockSession.return_value = mock_session
            
            # 创建 RequestUtils 实例（会使用共享 session）
            utils = RequestUtils(headers=headers)
            res = utils.get('http://example.com/api')
            
            # 验证 session.get 被调用时包含了 headers
            mock_session.get.assert_called_once()
            call_kwargs = mock_session.get.call_args[1]
            assert 'headers' in call_kwargs
            assert call_kwargs['headers'] == headers

    def test_post_with_session_includes_headers(self):
        """测试 post 方法在使用 session 时传递 headers"""
        headers = {'authorization': 'Bearer test_token_abc'}
        
        with patch('app.utils.http_utils.requests.Session') as MockSession:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.text = '{"code": 200}'
            mock_response.status_code = 200
            mock_session.post.return_value = mock_response
            MockSession.return_value = mock_session
            
            # 创建 RequestUtils 实例（会使用共享 session）
            utils = RequestUtils(headers=headers)
            res = utils.post('http://example.com/api', json={'key': 'value'})
            
            # 验证 session.post 被调用时包含了 headers
            mock_session.post.assert_called_once()
            call_kwargs = mock_session.post.call_args[1]
            assert 'headers' in call_kwargs
            assert call_kwargs['headers'] == headers


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
