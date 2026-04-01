# -*- coding: utf-8 -*-

import requests
import json
import re
import os
import log
import hashlib
import base64
import bencodepy


class PyThunder:
    """迅雷客户端封装类"""
    
    def __init__(self, token=None, host='localhost', port=2345):
        """
        PyThunder constructor.
        
        token: 迅雷认证token
        host: string, 迅雷主机地址，默认是 'localhost'
        port: integer, 迅雷端口，默认是 2345
        """
        self.base_url = f"http://{host}:{port}"
        self.session = requests.Session()
        self.token = token
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
            "Authorization": self.token,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        }
    
    def get_pan_token(self):
        """获取PAN token"""
        url = f"{self.base_url}/webman/3rdparty/pan-xunlei-com/index.cgi/"
        response = self.session.get(url, headers=self.headers, verify=False)
        
        # 从响应文本中提取 token
        pattern = r'function uiauth\(value\)\{ return "([^"]+)" \}'
        match = re.search(pattern, response.text)
        
        if match:
            token = match.group(1)
            return token
        else:
            # 如果第一种模式没匹配到，尝试匹配 JWT 格式
            jwt_pattern = r'[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'
            match_jwt = re.search(jwt_pattern, response.text)
            if match_jwt:
                return match_jwt.group()
            else:
                raise ValueError("未在响应中找到 token")
    
    def get_device_id(self):
        """获取设备ID"""
        self.headers["Accept"] = "application/json, text/plain, */*"
        url = f"{self.base_url}/webman/3rdparty/pan-xunlei-com/index.cgi/device/info/watch"
        params = {
            "pan_auth": self.get_pan_token(),
            "device_space": ""
        }
        data = {}
        data = json.dumps(data, separators=(',', ':'))
        response = self.session.post(url, headers=self.headers, params=params, data=data, verify=False)
        if response.status_code == 200:
            response_data = response.json()
            # 从 target 字段提取 device_id
            target = response_data.get('target', '')
            if target and '#' in target:
                device_id = target.split('#')[1]
                return device_id
            else:
                raise ValueError(f"无法从响应中提取 device_id，target 字段格式不正确: {target}")
        else:
            raise ValueError(f"请求失败，状态码: {response.status_code}")
    
    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小为可读格式"""
        if size_bytes == 0:
            return "0 B"
        
        units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
        unit_index = 0
        size = float(size_bytes)
        
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
            
        return f"{size:.2f} {units[unit_index]}"
    
    def get_torrent_info(self, download_urls: str, extract_info: bool = True):
        """
        获取种子/资源信息（文件列表、大小等）
        
        Args:
            download_urls: 下载链接（磁力链、HTTP链接等）
            extract_info: 是否提取文件列表和大小信息，如果为False则返回原始响应
            
        Returns:
            如果 extract_info=True: 返回包含文件列表、总大小等信息的字典
            如果 extract_info=False: 返回原始API响应
        """
        url = f"{self.base_url}/webman/3rdparty/pan-xunlei-com/index.cgi/drive/v1/resource/list"
        pan_token = self.get_pan_token()
    
        self.headers["Accept"] = "application/json, text/plain, */*"
        self.headers["content-type"] = "application/json"

        params = {
            "pan_auth": pan_token,
            "device_space": ""
        }

        data = {
            "page_size": 2000,
            "urls": download_urls
        }
        data = json.dumps(data, separators=(',', ':'))
        response = self.session.post(url, headers=self.headers, params=params, data=data, verify=False)
        
        if not extract_info:
            return response.json()
        
        # 提取文件信息
        result = response.json()
        
        # 检查响应结构
        if 'list' not in result or 'resources' not in result['list']:
            return result
        
        resources = result['list']['resources']
        
        # 递归提取所有文件信息
        def extract_files_from_resources(resources_list, parent_path="", file_index_counter=0):
            """
            递归从资源列表中提取文件信息
            
            Args:
                resources_list: 资源列表
                parent_path: 父目录路径
                file_index_counter: 文件索引计数器
                
            Returns:
                (file_list, total_size, total_files, file_index_counter)
            """
            file_list = []
            total_size = 0
            total_files = 0
            
            for resource in resources_list:
                resource_id = resource.get('id', '')
                resource_name = resource.get('name', '')
                resource_size = resource.get('file_size', 0)
                is_dir = resource.get('is_dir', False)
                
                # 构建完整路径
                current_path = f"{parent_path}/{resource_name}" if parent_path else resource_name
                
                if is_dir and 'dir' in resource and 'resources' in resource['dir']:
                    # 递归处理目录
                    dir_resources = resource['dir']['resources']
                    sub_files, sub_size, sub_count, file_index_counter = extract_files_from_resources(
                        dir_resources, current_path, file_index_counter
                    )
                    file_list.extend(sub_files)
                    total_size += sub_size
                    total_files += sub_count
                else:
                    # 处理文件
                    file_index_counter += 1
                    
                    # 从id中提取文件索引（最后一个点后面的数字）
                    file_index = 0
                    if resource_id:
                        parts = resource_id.split('.')
                        if len(parts) > 0:
                            try:
                                # 尝试获取最后一个部分作为索引
                                last_part = parts[-1]
                                file_index = int(last_part)
                            except (ValueError, IndexError):
                                # 如果不能转换为数字，使用计数器
                                file_index = file_index_counter
                    
                    file_info = {
                        'id': resource_id,
                        'name': resource_name,
                        'full_path': current_path,
                        'size_bytes': resource_size,
                        'size_formatted': self._format_file_size(resource_size),
                        'file_index': file_index,  # 文件索引，用于下载时选择
                        'mime_type': resource.get('meta', {}).get('mime_type', ''),
                        'status': resource.get('meta', {}).get('status', ''),
                        'hash': resource.get('meta', {}).get('hash', ''),
                        'is_dir': is_dir,
                        'parent_id': resource.get('parent_id', '')
                    }
                    file_list.append(file_info)
                    
                    total_size += resource_size
                    total_files += 1
            
            return file_list, total_size, total_files, file_index_counter
        
        # 提取所有文件
        file_list, total_size_bytes, total_files, _ = extract_files_from_resources(resources)
        
        # 按文件索引排序
        file_list.sort(key=lambda x: x.get('file_index', 0))
        
        # 返回结构化的信息
        return {
            'list_id': result.get('list_id', ''),
            'total_files': total_files,
            'total_size_bytes': total_size_bytes,
            'total_size_formatted': self._format_file_size(total_size_bytes),
            'files': file_list,
            'raw_response': result if len(file_list) == 0 else None  # 如果没有文件，保留原始响应
        }
    
    def download(self, download_urls: str, destination_path: str = "/downloads/xunlei/",
                 file_indices: str = None, file_names: list = None):
        """
        开始下载任务（使用真正的下载API）
        
        Args:
            download_urls: 下载链接（磁力链、种子文件路径等）
            destination_path: 下载保存路径，默认为 "/downloads/xunlei/"
            file_indices: 下载文件索引，格式如 "--1"（全部），"1-10"（范围），"1,3,5"（指定）
                          如果为None，则下载全部文件
            file_names: 指定要下载的文件名列表，如果提供则忽略 file_indices
            
        Returns:
            下载任务创建结果
        """
        # 判断输入类型：磁力链接还是种子文件
        actual_download_url = download_urls
        
        if download_urls.startswith('magnet:?'):
            log.info(f"检测到磁力链接: {download_urls[:80]}...")
        elif download_urls.endswith('.torrent') or os.path.exists(download_urls):
            log.info(f"检测到种子文件: {download_urls}")
            # 转换为磁力链接
            magnet_url = self.torrent_to_magnet(download_urls)
            if not magnet_url:
                raise ValueError(f"种子文件转换失败: {download_urls}")
            actual_download_url = magnet_url
            log.info(f"已转换为磁力链接: {magnet_url[:80]}...")
        else:
            log.info(f"输入类型未知，按磁力链接处理: {download_urls[:80]}...")
        
        # 首先获取种子信息，用于获取文件详情
        torrent_info = self.get_torrent_info(actual_download_url, extract_info=True)
        
        if not torrent_info or 'files' not in torrent_info or len(torrent_info['files']) == 0:
            raise ValueError("无法获取种子信息或没有找到可下载的文件")
        
        files = torrent_info['files']
        total_files = torrent_info['total_files']
        total_size_bytes = torrent_info['total_size_bytes']
        
        # 确定要下载的文件
        if file_names:
            # 根据文件名筛选文件
            selected_files = [f for f in files if f['name'] in file_names]
            if not selected_files:
                raise ValueError(f"未找到指定的文件: {file_names}")
            
            # 计算选中的文件大小总和
            selected_size = sum(f['size_bytes'] for f in selected_files)
            selected_count = len(selected_files)
            
            # 生成文件索引（使用从id提取的file_index）
            indices = [str(f['file_index']) for f in selected_files]
            sub_file_index = ",".join(indices)
            
            # 使用第一个选中文件的名称作为任务名称
            task_name = selected_files[0]['name'] if selected_files else files[0]['name']
            download_size = selected_size
            download_count = selected_count
            
        elif file_indices:
            # 使用指定的文件索引
            sub_file_index = file_indices
            task_name = files[0]['name']  # 使用第一个文件作为任务名称
            
            # 如果指定了索引，需要计算选中文件的大小
            if file_indices == "--1":
                # 下载全部
                download_size = total_size_bytes
                download_count = total_files
            else:
                # 解析索引范围或列表，计算实际选中的文件大小
                # 首先解析索引
                selected_indices = set()
                if '-' in file_indices:
                    # 范围格式：1-10
                    try:
                        start_str, end_str = file_indices.split('-')
                        start = int(start_str.strip())
                        end = int(end_str.strip())
                        selected_indices = set(range(start, end + 1))
                    except ValueError:
                        raise ValueError(f"无效的索引范围格式: {file_indices}")
                elif ',' in file_indices:
                    # 列表格式：1,3,5
                    try:
                        selected_indices = set(int(idx.strip()) for idx in file_indices.split(','))
                    except ValueError:
                        raise ValueError(f"无效的索引列表格式: {file_indices}")
                else:
                    # 单个索引
                    try:
                        selected_indices = {int(file_indices.strip())}
                    except ValueError:
                        raise ValueError(f"无效的索引格式: {file_indices}")
                
                # 筛选文件并计算大小
                selected_files = [f for f in files if f.get('file_index', 0) in selected_indices]
                if not selected_files:
                    log.warn(f"警告: 没有找到索引为 {file_indices} 的文件，将下载全部文件")
                    sub_file_index = "--1"
                    download_size = total_size_bytes
                    download_count = total_files
                else:
                    download_size = sum(f['size_bytes'] for f in selected_files)
                    download_count = len(selected_files)
                    log.info(f"选中 {download_count} 个文件，总大小: {self._format_file_size(download_size)}")
        else:
            # 默认下载全部
            sub_file_index = "--1"
            task_name = files[0]['name']
            download_size = total_size_bytes
            download_count = total_files
        
        # 获取 device_id
        try:
            device_id = self.get_device_id()
        except Exception as e:
            log.warn(f"获取 device_id 失败，使用默认值: {e}")
            # 使用示例中的 device_id 作为后备
            device_id = "7abd3182d399f7bdda199550d8babede"
        
        # 获取 pan_token
        pan_token = self.get_pan_token()
        
        # 准备下载请求
        url = f"{self.base_url}/webman/3rdparty/pan-xunlei-com/index.cgi/drive/v1/task"
        
        # 更新 headers
        self.headers.update({
            "Accept": "*/*",
            "content-type": "application/json",
            "device-space": "",
            "pan-auth": pan_token
        })
        
        # 使用第一个文件的信息
        first_file = files[0]
        
        data = {
            "type": "user#download-url",
            "name": task_name,
            "file_name": task_name,
            "file_size": str(download_size),  # 使用需要下载的文件大小总和
            "space": f"device_id#{device_id}",
            "params": {
                "target": f"device_id#{device_id}",
                "url": download_urls,
                "total_file_count": str(download_count),
                "parent_folder_path": destination_path,
                "sub_file_index": sub_file_index,  # 下载文件索引
                "mime_type": first_file.get('mime_type', ''),
                "file_id": first_file.get('id', '')
            }
        }
        
        data_json = json.dumps(data, separators=(',', ':'))
        
        log.info(f"开始下载任务: {task_name}")
        log.info(f"下载文件数: {download_count}")
        log.info(f"下载大小: {self._format_file_size(download_size)}")
        log.info(f"文件索引: {sub_file_index}")
        log.info(f"保存路径: {destination_path}")
        
        response = self.session.post(url, headers=self.headers, data=data_json, verify=False)
        
        if response.status_code == 200:
            result = response.json()
            
            # 根据实际响应结构提取任务信息
            task_info = result
            if 'task' in result:
                task_info = result['task']
            
            log.info(f"✓ 下载任务创建成功")
            log.info(f"  任务ID: {task_info.get('id', 'N/A')}")
            log.info(f"  任务名称: {task_info.get('name', 'N/A')}")
            log.info(f"  阶段: {task_info.get('phase', 'N/A')}")
            log.info(f"  消息: {task_info.get('message', 'N/A')}")
            log.info(f"  创建时间: {task_info.get('created_time', 'N/A')}")
            
            return task_info
        else:
            error_msg = f"下载任务创建失败，状态码: {response.status_code}"
            log.error(error_msg)
            log.error(f"响应: {response.text}")
            raise Exception(error_msg)
    
    def _get_tasks(self, phase_filter: str, limit: int = 100):
        """
        内部方法：获取指定阶段的任务
        
        Args:
            phase_filter: 阶段过滤器，如 "PHASE_TYPE_PENDING,PHASE_TYPE_RUNNING,PHASE_TYPE_PAUSED,PHASE_TYPE_ERROR"
            limit: 返回任务数量限制，默认100
            
        Returns:
            任务列表
        """
        # 获取 device_id
        try:
            device_id = self.get_device_id()
        except Exception as e:
            log.warn(f"获取 device_id 失败，使用默认值: {e}")
            device_id = "7abd3182d399f7bdda199550d8babede"
        
        # 获取 pan_token
        pan_token = self.get_pan_token()
        
        # 准备请求
        url = f"{self.base_url}/webman/3rdparty/pan-xunlei-com/index.cgi/drive/v1/tasks"
        
        # 更新 headers
        self.headers.update({
            "Accept": "*/*",
            "content-type": "application/json",
            "device-space": "",
            "pan-auth": pan_token,
            "Referer": f"{self.base_url}/webman/3rdparty/pan-xunlei-com/index.cgi/"
        })
        
        # 构建 filters 参数
        filters = {
            "phase": {"in": phase_filter},
            "type": {"in": "user#download-url,user#download"}
        }
        filters_json = json.dumps(filters, separators=(',', ':'))
        
        params = {
            "space": f"device_id#{device_id}",
            "page_token": "",
            "filters": filters_json,
            "limit": str(limit),
            "pan_auth": pan_token,
            "device_space": ""
        }
        
        response = self.session.get(url, headers=self.headers, params=params, verify=False)
        
        if response.status_code == 200:
            result = response.json()
            # 返回任务列表
            tasks = result.get('tasks', [])
            log.debug(f"获取到 {len(tasks)} 个任务")
            return tasks
        else:
            error_msg = f"获取任务失败，状态码: {response.status_code}"
            log.error(error_msg)
            log.error(f"响应: {response.text}")
            raise Exception(error_msg)
    
    def get_downloading_tasks(self, limit: int = 100):
        """
        获取正在下载的任务（等待中、运行中、暂停、错误）
        
        Args:
            limit: 返回任务数量限制，默认100
            
        Returns:
            正在下载的任务列表
        """
        phase_filter = "PHASE_TYPE_PENDING,PHASE_TYPE_RUNNING,PHASE_TYPE_PAUSED,PHASE_TYPE_ERROR"
        return self._get_tasks(phase_filter, limit)
    
    def get_complete_tasks(self, limit: int = 100):
        """
        获取已完成的任务
        
        Args:
            limit: 返回任务数量限制，默认100
            
        Returns:
            已完成的任务列表
        """
        phase_filter = "PHASE_TYPE_COMPLETE"
        return self._get_tasks(phase_filter, limit)
    
    def _update_task_phase(self, task_id: str, phase: str):
        """
        内部方法：更新任务阶段（暂停/启动/删除）
        
        Args:
            task_id: 任务ID
            phase: 阶段，如 "pause"、"running" 或 "delete"
            
        Returns:
            操作是否成功 (True/False)
        """
        # 获取 device_id
        try:
            device_id = self.get_device_id()
        except Exception as e:
            log.warn(f"获取 device_id 失败，使用默认值: {e}")
            device_id = "7abd3182d399f7bdda199550d8babede"
        
        # 获取 pan_token
        pan_token = self.get_pan_token()
        
        # 准备请求
        url = f"{self.base_url}/webman/3rdparty/pan-xunlei-com/index.cgi/method/patch/drive/v1/task"
        
        # 更新 headers
        self.headers.update({
            "Accept": "*/*",
            "content-type": "application/json",
            "device-space": "",
            "pan-auth": pan_token
        })
        
        # 构建请求数据
        data = {
            "space": f"device_id#{device_id}",
            "type": "user#download-url",
            "id": task_id,
            "set_params": {
                "spec": json.dumps({"phase": phase})
            }
        }
        
        data_json = json.dumps(data, separators=(',', ':'))
        
        params = {
            "pan_auth": pan_token,
            "device_space": ""
        }
        
        response = self.session.patch(url, headers=self.headers, params=params, data=data_json, verify=False)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('HttpStatus') == 0:
                log.debug(f"✓ 任务 {task_id} 已成功设置为 {phase} 状态")
                return True
            else:
                log.warn(f"⚠ 任务状态更新返回非零状态: {result}")
                return False
        else:
            error_msg = f"任务状态更新失败，状态码: {response.status_code}"
            log.error(error_msg)
            log.error(f"响应: {response.text}")
            return False
    
    def pause_task(self, task_id: str):
        """
        暂停任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            操作是否成功 (True/False)
        """
        return self._update_task_phase(task_id, "pause")
    
    def resume_task(self, task_id: str):
        """
        恢复任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            操作是否成功 (True/False)
        """
        return self._update_task_phase(task_id, "running")
    
    def delete_task(self, task_id: str, delete_files: bool = False):
        """
        删除下载任务
        
        Args:
            task_id: 任务ID
            delete_files: 是否同时删除文件，True=删除任务和文件，False=只删除任务
            
        Returns:
            操作是否成功 (True/False)
        """
        log.info(f"删除任务: {task_id}, 删除文件: {delete_files}")
        
        if delete_files:
            # 删除任务包括文件 - 使用 PATCH 方法，设置 phase 为 "delete"
            return self._update_task_phase(task_id, "delete")
        else:
            # 只删除任务不删除文件 - 使用 DELETE 方法
            # 获取 device_id
            try:
                device_id = self.get_device_id()
            except Exception as e:
                log.warn(f"获取 device_id 失败，使用默认值: {e}")
                device_id = "7abd3182d399f7bdda199550d8babede"
            
            # 获取 pan_token
            pan_token = self.get_pan_token()
            
            # 准备请求
            url = f"{self.base_url}/webman/3rdparty/pan-xunlei-com/index.cgi/method/delete/drive/v1/tasks"
            
            # 更新 headers
            self.headers.update({
                "Accept": "*/*",
                "content-type": "application/json",
                "device-space": "",
                "pan-auth": pan_token
            })
            
            # 构建查询参数
            params = {
                "space": f"device_id#{device_id}",
                "task_ids": task_id,
                "pan_auth": pan_token,
                "device_space": ""
            }
            
            # DELETE 请求，空数据体
            response = self.session.delete(url, headers=self.headers, params=params, verify=False)
            
            if response.status_code == 200:
                result = response.json()
                # 根据用户提供的示例，只删除任务不删除文件的响应是空对象 {}
                if result == {}:
                    log.debug(f"✓ 任务 {task_id} 已成功删除（保留文件）")
                    return True
                else:
                    log.warn(f"⚠ 删除任务返回非空响应: {result}")
                    return False
            else:
                error_msg = f"删除任务失败，状态码: {response.status_code}"
                log.error(error_msg)
                log.error(f"响应: {response.text}")
                return False
    
    def torrent_to_magnet(self, torrent_file_path: str):
        """
        将种子文件转换为磁力链接
        
        Args:
            torrent_file_path: 种子文件路径
            
        Returns:
            磁力链接字符串，如果转换失败则返回None
        """
        try:

            # 读取种子文件
            with open(torrent_file_path, 'rb') as f:
                torrent_data = f.read()
            
            # 解码种子文件
            torrent_dict = bencodepy.decode(torrent_data)
            
            # 计算 info_hash
            info = torrent_dict[b'info']
            info_encoded = bencodepy.encode(info)
            info_hash = hashlib.sha1(info_encoded).digest()
            
            # 转换为十六进制字符串
            info_hash_hex = info_hash.hex()
            
            # 构建磁力链接
            magnet_link = f"magnet:?xt=urn:btih:{info_hash_hex}"
            
            # 添加 tracker（如果有）
            if b'announce' in torrent_dict:
                announce = torrent_dict[b'announce'].decode('utf-8', errors='ignore')
                magnet_link += f"&tr={announce}"
            
            # 添加名称（如果有）
            if b'name' in info:
                name = info[b'name'].decode('utf-8', errors='ignore')
                magnet_link += f"&dn={name}"
            
            log.debug(f"种子文件 {torrent_file_path} 转换为磁力链接: {magnet_link[:80]}...")
            return magnet_link
            
        except Exception as e:
            log.error(f"种子文件转换失败: {e}")
            return None