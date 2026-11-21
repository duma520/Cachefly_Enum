# Cachefly_Enum.py
import sys
import os
import json
import threading
import requests
import socket
import subprocess
import re
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QPushButton, QLineEdit, QTextEdit, 
                               QProgressBar, QLabel, QGroupBox, QGridLayout, 
                               QSpinBox, QCheckBox, QMessageBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QHeaderView,
                               QComboBox, QTabWidget, QDialog, QDialogButtonBox,
                               QListWidget, QListWidgetItem, QMenu, QAbstractItemView)
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QTimer, QUrl
from PySide6.QtGui import QFont, QIcon, QColor, QTextCursor, QAction


class SpeedTestThread(QThread):
    """测速线程类"""
    progress_signal = Signal(str, str)  # URL, 状态
    result_signal = Signal(str, dict)   # URL, 测速结果
    completed_signal = Signal()
    
    def __init__(self, urls, test_type="http", proxy_enabled=False, proxy_host="127.0.0.1", 
                 proxy_port=20808, proxy_type="http"):
        super().__init__()
        self.urls = urls
        self.test_type = test_type  # http, ping, ip, all
        self.is_running = True
        self.proxy_enabled = proxy_enabled
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.proxy_type = proxy_type
        self.session = None
        
    def get_session(self):
        """获取带代理配置的会话"""
        if self.session is None:
            self.session = requests.Session()
            if self.proxy_enabled:
                proxy_url = f"{self.proxy_type}://{self.proxy_host}:{self.proxy_port}"
                self.session.proxies = {
                    'http': proxy_url,
                    'https': proxy_url
                }
        return self.session
        
    def run(self):
        for url in self.urls:
            if not self.is_running:
                break
                
            result = {}
            if self.test_type == "http":
                result = self.test_http_speed(url)
            elif self.test_type == "ping":
                result = self.test_ping_latency(url)
            elif self.test_type == "ip":
                result = self.get_ip_info(url)
            elif self.test_type == "all":
                # 全部检测
                result = self.test_http_speed(url)
                result.update(self.test_ping_latency(url))
                result.update(self.get_ip_info(url))
                
            self.result_signal.emit(url, result)
            self.msleep(100)
        
        self.completed_signal.emit()
    
    def test_http_speed(self, url):
        """测试HTTP下载速度（支持代理）"""
        import time
        
        result = {
            'http_download_speed': 'N/A',
            'http_response_time': 'N/A',
            'http_status': 'N/A'
        }
        
        try:
            session = self.get_session()
            start_time = time.time()
            response = session.get(url, timeout=10, stream=True)
            result['http_status'] = response.status_code
            
            if response.status_code == 200:
                # 下载前1MB测速
                chunk_size = 1024 * 1024  # 1MB
                downloaded = 0
                start_download = time.time()
                
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if downloaded >= chunk_size:
                        break
                    downloaded += len(chunk)
                
                download_time = time.time() - start_download
                if download_time > 0:
                    speed_mbps = (downloaded * 8) / (download_time * 1024 * 1024)
                    result['http_download_speed'] = f"{speed_mbps:.2f} Mbps"
                
                result['http_response_time'] = f"{(time.time() - start_time) * 1000:.0f} ms"
        except requests.exceptions.ProxyError as e:
            result['http_status'] = f"代理错误: {str(e)[:50]}"
        except Exception as e:
            result['http_status'] = f"错误: {str(e)[:50]}"
        
        return result
    
    def test_ping_latency(self, url):
        """测试Ping延迟（Ping命令不支持代理，直接连接）"""
        result = {
            'ping_min': 'N/A',
            'ping_avg': 'N/A',
            'ping_max': 'N/A',
            'ping_loss': 'N/A'
        }
        
        # 从URL提取主机名
        hostname = self.extract_hostname(url)
        
        try:
            # 使用系统ping命令（ping命令不支持代理，直接连接）
            param = '-n' if sys.platform == 'win32' else '-c'
            command = ['ping', param, '4', hostname]
            
            output = subprocess.check_output(command, timeout=15, 
                                            stderr=subprocess.STDOUT, 
                                            universal_newlines=True)
            
            # 解析ping结果
            if sys.platform == 'win32':
                times = re.findall(r'时间[=<](\d+)ms', output)
                loss_match = re.search(r'\((\d+)% 丢失\)', output)
            else:
                times = re.findall(r'time[= ](\d+(?:\.\d+)?) ms', output)
                loss_match = re.search(r'(\d+)% packet loss', output)
            
            if times:
                times_ms = [float(t) for t in times]
                result['ping_min'] = f"{min(times_ms):.0f} ms"
                result['ping_avg'] = f"{sum(times_ms)/len(times_ms):.0f} ms"
                result['ping_max'] = f"{max(times_ms):.0f} ms"
            
            if loss_match:
                result['ping_loss'] = f"{loss_match.group(1)}%"
                
        except subprocess.TimeoutExpired:
            result['ping_avg'] = "超时"
        except Exception:
            result['ping_avg'] = "错误"
        
        return result
    
    def extract_hostname(self, url):
        """从URL提取主机名"""
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        return parsed.hostname or url
    
    def get_ip_info(self, url):
        """获取IP信息（支持代理）"""
        result = {
            'entry_ip': 'N/A',
            'exit_ip': 'N/A',
            'country': 'N/A',
            'isp': 'N/A'
        }
        
        hostname = self.extract_hostname(url)
        
        try:
            # 获取入口IP（域名解析，不使用代理）
            entry_ip = socket.gethostbyname(hostname)
            result['entry_ip'] = entry_ip
            
            # 获取出口IP（通过外部服务，使用代理设置）
            try:
                session = self.get_session()
                ip_response = session.get('https://api.ipify.org?format=json', timeout=5)
                if ip_response.status_code == 200:
                    result['exit_ip'] = ip_response.json().get('ip', 'N/A')
            except Exception:
                result['exit_ip'] = '获取失败'
            
            # 获取IP地理位置信息（不使用代理，因为是本地IP查询）
            try:
                geo_response = requests.get(f'http://ip-api.com/json/{entry_ip}', timeout=5)
                if geo_response.status_code == 200:
                    geo_data = geo_response.json()
                    if geo_data.get('status') == 'success':
                        result['country'] = geo_data.get('country', 'N/A')
                        result['isp'] = geo_data.get('isp', 'N/A')
            except Exception:
                pass
                
        except socket.gaierror:
            result['entry_ip'] = '解析失败'
        
        return result
    
    def stop(self):
        self.is_running = False


class DiscoveredFilesListWidget(QWidget):
    """已发现文件列表组件"""
    
    # 定义信号，当列表变化时通知主窗口保存
    list_changed = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.speed_test_thread = None
        self.current_test_type = "http"
        self.proxy_settings = {
            'enabled': False,
            'host': '127.0.0.1',
            'port': 20808,
            'type': 'http'
        }
        self.config_manager = None  # 将在主窗口设置
        
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # 工具栏
        toolbar_layout = QHBoxLayout()
        
        self.select_all_button = QPushButton("全选")
        self.select_all_button.clicked.connect(self.select_all)
        toolbar_layout.addWidget(self.select_all_button)
        
        self.deselect_all_button = QPushButton("取消全选")
        self.deselect_all_button.clicked.connect(self.deselect_all)
        toolbar_layout.addWidget(self.deselect_all_button)
        
        self.delete_selected_button = QPushButton("删除选中")
        self.delete_selected_button.clicked.connect(self.delete_selected)
        self.delete_selected_button.setStyleSheet("QPushButton { background-color: #f44336; color: white; }")
        toolbar_layout.addWidget(self.delete_selected_button)
        
        self.clear_all_button = QPushButton("一键清空")
        self.clear_all_button.clicked.connect(self.clear_all)
        self.clear_all_button.setStyleSheet("QPushButton { background-color: #ff9800; color: white; }")
        toolbar_layout.addWidget(self.clear_all_button)
        
        toolbar_layout.addStretch()
        
        # 代理状态显示
        self.proxy_indicator = QLabel()
        self.proxy_indicator.setStyleSheet("QLabel { font-size: 10px; padding: 2px 5px; border-radius: 3px; }")
        toolbar_layout.addWidget(self.proxy_indicator)
        
        # 测速选项
        self.test_type_combo = QComboBox()
        self.test_type_combo.addItems(["HTTP测速", "Ping延迟", "IP信息检测", "全部检测"])
        toolbar_layout.addWidget(QLabel("测试类型:"))
        toolbar_layout.addWidget(self.test_type_combo)
        
        self.start_test_button = QPushButton("开始测速")
        self.start_test_button.clicked.connect(self.start_speed_test)
        self.start_test_button.setStyleSheet("QPushButton { background-color: #2196F3; color: white; }")
        toolbar_layout.addWidget(self.start_test_button)
        
        self.stop_test_button = QPushButton("停止测速")
        self.stop_test_button.clicked.connect(self.stop_speed_test)
        self.stop_test_button.setEnabled(False)
        toolbar_layout.addWidget(self.stop_test_button)
        
        layout.addLayout(toolbar_layout)
        
        # 文件列表
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.show_context_menu)
        layout.addWidget(self.file_list)
        
        # 测速结果显示区域
        self.speed_result_group = QGroupBox("测速结果")
        speed_layout = QVBoxLayout(self.speed_result_group)
        
        self.speed_result_text = QTextEdit()
        self.speed_result_text.setReadOnly(True)
        self.speed_result_text.setMaximumHeight(200)
        self.speed_result_text.setFont(QFont("Consolas", 9))
        speed_layout.addWidget(self.speed_result_text)
        
        layout.addWidget(self.speed_result_group)
    
    def set_config_manager(self, config_manager):
        """设置配置管理器"""
        self.config_manager = config_manager
    
    def save_to_config(self):
        """保存列表数据到配置"""
        if self.config_manager:
            files_data = []
            for i in range(self.file_list.count()):
                item = self.file_list.item(i)
                data = item.data(Qt.UserRole)
                if data:
                    files_data.append(data)
            self.config_manager.current_config['discovered_files'] = files_data
            self.config_manager.save_config()
    
    def update_proxy_indicator(self):
        """更新代理状态指示器"""
        if self.proxy_settings.get('enabled', False):
            self.proxy_indicator.setText(f"🌐 代理: {self.proxy_settings['host']}:{self.proxy_settings['port']}")
            self.proxy_indicator.setStyleSheet("QLabel { background-color: #4CAF50; color: white; font-size: 10px; padding: 2px 5px; border-radius: 3px; }")
        else:
            self.proxy_indicator.setText("🔌 直连模式")
            self.proxy_indicator.setStyleSheet("QLabel { background-color: #9E9E9E; color: white; font-size: 10px; padding: 2px 5px; border-radius: 3px; }")
    
    def set_proxy_settings(self, settings):
        """设置代理配置"""
        self.proxy_settings = settings.copy()
        self.update_proxy_indicator()
        
    def add_file(self, size_mb, url, response_time):
        """添加文件到列表"""
        # 检查是否已存在
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            data = item.data(Qt.UserRole)
            if data and data['url'] == url:
                return
        
        item_text = f"[{size_mb}MB] {url} (响应: {response_time}ms)"
        item = QListWidgetItem(item_text)
        item.setData(Qt.UserRole, {
            'size': size_mb,
            'url': url,
            'response_time': response_time,
            'discovered_at': datetime.now().isoformat()
        })
        self.file_list.addItem(item)
        
        # 保存到配置文件
        self.save_to_config()
        
    def load_from_data(self, files_data):
        """从数据加载文件列表"""
        self.file_list.clear()
        for file_info in files_data:
            item_text = f"[{file_info['size']}MB] {file_info['url']} (响应: {file_info['response_time']}ms)"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, file_info)
            self.file_list.addItem(item)
        
    def select_all(self):
        """全选"""
        for i in range(self.file_list.count()):
            self.file_list.item(i).setSelected(True)
            
    def deselect_all(self):
        """取消全选"""
        self.file_list.clearSelection()
        
    def delete_selected(self):
        """删除选中项"""
        for item in self.file_list.selectedItems():
            row = self.file_list.row(item)
            self.file_list.takeItem(row)
        # 删除后保存
        self.save_to_config()
            
    def clear_all(self):
        """一键清空"""
        reply = QMessageBox.question(self, "确认清空", "确定要清空所有已发现文件吗？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.file_list.clear()
            self.speed_result_text.clear()
            self.save_to_config()
            
    def get_selected_urls(self):
        """获取选中的URL列表"""
        urls = []
        for item in self.file_list.selectedItems():
            data = item.data(Qt.UserRole)
            if data:
                urls.append(data['url'])
        return urls
    
    def get_all_urls(self):
        """获取所有URL列表"""
        urls = []
        for i in range(self.file_list.count()):
            data = self.file_list.item(i).data(Qt.UserRole)
            if data:
                urls.append(data['url'])
        return urls
    
    def show_context_menu(self, position):
        """显示右键菜单"""
        menu = QMenu()
        
        test_http_action = QAction("HTTP测速", self)
        test_http_action.triggered.connect(lambda: self.test_selected("http"))
        menu.addAction(test_http_action)
        
        test_ping_action = QAction("Ping延迟测试", self)
        test_ping_action.triggered.connect(lambda: self.test_selected("ping"))
        menu.addAction(test_ping_action)
        
        test_ip_action = QAction("IP信息检测", self)
        test_ip_action.triggered.connect(lambda: self.test_selected("ip"))
        menu.addAction(test_ip_action)
        
        test_all_action = QAction("全部检测", self)
        test_all_action.triggered.connect(lambda: self.test_selected("all"))
        menu.addAction(test_all_action)
        
        menu.addSeparator()
        
        copy_url_action = QAction("复制URL", self)
        copy_url_action.triggered.connect(self.copy_selected_urls)
        menu.addAction(copy_url_action)
        
        menu.addSeparator()
        
        delete_action = QAction("删除", self)
        delete_action.triggered.connect(self.delete_selected)
        menu.addAction(delete_action)
        
        menu.exec(self.file_list.mapToGlobal(position))
        
    def test_selected(self, test_type):
        """测试选中的文件"""
        urls = self.get_selected_urls()
        if not urls:
            QMessageBox.warning(self, "警告", "请先选择要测试的文件")
            return
        
        # 根据选择的测试类型设置
        if test_type == "all":
            self.current_test_type = "all"
        elif test_type == "http":
            self.current_test_type = "http"
        elif test_type == "ping":
            self.current_test_type = "ping"
        elif test_type == "ip":
            self.current_test_type = "ip"
            
        self.start_speed_test()
        
    def start_speed_test(self):
        """开始测速"""
        urls = self.get_selected_urls()
        if not urls:
            QMessageBox.warning(self, "警告", "请先选择要测试的文件")
            return
        
        test_type_map = {
            "HTTP测速": "http",
            "Ping延迟": "ping",
            "IP信息检测": "ip",
            "全部检测": "all"
        }
        
        selected_type = self.test_type_combo.currentText()
        test_type = test_type_map.get(selected_type, "http")
        
        # 显示代理状态信息
        proxy_info = "使用代理" if self.proxy_settings.get('enabled') else "直连"
        
        self.speed_result_text.clear()
        self.speed_result_text.append("=" * 60)
        self.speed_result_text.append(f"开始测速 - 测试类型: {selected_type}")
        self.speed_result_text.append(f"测试文件数: {len(urls)}")
        self.speed_result_text.append(f"网络模式: {proxy_info}")
        if self.proxy_settings.get('enabled'):
            self.speed_result_text.append(f"代理服务器: {self.proxy_settings['host']}:{self.proxy_settings['port']}")
        self.speed_result_text.append("=" * 60)
        
        self.start_test_button.setEnabled(False)
        self.stop_test_button.setEnabled(True)
        
        # 创建测速线程，传入代理设置
        self.speed_test_thread = SpeedTestThread(
            urls, test_type,
            self.proxy_settings.get('enabled', False),
            self.proxy_settings.get('host', '127.0.0.1'),
            self.proxy_settings.get('port', 20808),
            self.proxy_settings.get('type', 'http')
        )
        self.speed_test_thread.result_signal.connect(self.on_test_result)
        self.speed_test_thread.completed_signal.connect(self.on_test_completed)
        self.speed_test_thread.start()
        
    def stop_speed_test(self):
        """停止测速"""
        if self.speed_test_thread and self.speed_test_thread.isRunning():
            self.speed_test_thread.stop()
            self.speed_test_thread.wait()
            self.speed_result_text.append("\n测速已停止")
            self.on_test_completed()
            
    def on_test_result(self, url, result):
        """处理测速结果"""
        # 简化URL显示
        short_url = url if len(url) <= 80 else url[:77] + "..."
        self.speed_result_text.append(f"\n📁 {short_url}")
        self.speed_result_text.append("-" * 40)
        
        has_result = False
        for key, value in result.items():
            if value != 'N/A':
                display_key = {
                    'http_download_speed': '下载速度',
                    'http_response_time': '响应时间',
                    'http_status': 'HTTP状态',
                    'ping_min': '最小延迟',
                    'ping_avg': '平均延迟',
                    'ping_max': '最大延迟',
                    'ping_loss': '丢包率',
                    'entry_ip': '入口IP',
                    'exit_ip': '出口IP',
                    'country': '地理位置',
                    'isp': 'ISP提供商'
                }.get(key, key)
                
                self.speed_result_text.append(f"  {display_key}: {value}")
                has_result = True
        
        if not has_result:
            self.speed_result_text.append("  无可用数据")
                
        self.speed_result_text.append("")
        
        # 自动滚动
        cursor = self.speed_result_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.speed_result_text.setTextCursor(cursor)
        
    def on_test_completed(self):
        """测速完成"""
        self.start_test_button.setEnabled(True)
        self.stop_test_button.setEnabled(False)
        self.speed_result_text.append("\n" + "=" * 60)
        self.speed_result_text.append("测速完成！")
        
    def copy_selected_urls(self):
        """复制选中的URL"""
        urls = self.get_selected_urls()
        if urls:
            clipboard = QApplication.clipboard()
            clipboard.setText("\n".join(urls))
            QMessageBox.information(self, "复制成功", f"已复制 {len(urls)} 个URL到剪贴板")


class EnumerationWorkerThread(QThread):
    """枚举工作线程类"""
    progress_signal = Signal(int, int)  # 当前进度，总进度
    status_signal = Signal(str)  # 状态信息
    file_result_signal = Signal(str, int, bool, int)  # URL，大小(MB)，是否存在，响应时间(ms)
    enumeration_completed_signal = Signal(bool, str)  # 完成状态，消息
    
    def __init__(self, base_url, start_size, end_size, step_size, timeout=3, max_retries=1, 
                 proxy_enabled=False, proxy_host="127.0.0.1", proxy_port=20808):
        super().__init__()
        self.base_url = base_url
        self.start_size = start_size
        self.end_size = end_size
        self.step_size = step_size
        self.timeout = timeout
        self.max_retries = max_retries
        self.proxy_enabled = proxy_enabled
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.is_running = True
        self.paused = False
        self.session = None
        
    def get_session(self):
        """获取带代理配置的会话"""
        if self.session is None:
            self.session = requests.Session()
            if self.proxy_enabled:
                proxy_url = f"http://{self.proxy_host}:{self.proxy_port}"
                self.session.proxies = {
                    'http': proxy_url,
                    'https': proxy_url
                }
        return self.session
        
    def run(self):
        """运行枚举过程"""
        try:
            total_attempts = ((self.end_size - self.start_size) // self.step_size) + 1
            current_index = 0
            found_count = 0
            
            for size_mb in range(self.start_size, self.end_size + 1, self.step_size):
                while self.paused and self.is_running:
                    self.msleep(100)
                
                if not self.is_running:
                    break
                
                file_url = f"{self.base_url}{size_mb}mb.test"
                current_index += 1
                
                self.status_signal.emit(f"正在检查: {size_mb}MB 文件...")
                self.progress_signal.emit(current_index, total_attempts)
                
                # 检查文件是否存在
                exists, response_time = self.check_file_exists(file_url)
                
                if exists:
                    found_count += 1
                    self.file_result_signal.emit(file_url, size_mb, True, response_time)
                    self.status_signal.emit(f"✓ 找到文件: {size_mb}MB (响应时间: {response_time}ms)")
                else:
                    self.file_result_signal.emit(file_url, size_mb, False, response_time)
                    self.status_signal.emit(f"✗ 未找到: {size_mb}MB (响应时间: {response_time}ms)")
                
                # 短暂延迟，避免请求过快
                self.msleep(50)
                
            if self.is_running:
                self.enumeration_completed_signal.emit(True, f"枚举完成！共检查 {total_attempts} 个文件，找到 {found_count} 个有效文件")
            else:
                self.enumeration_completed_signal.emit(False, "枚举已取消")
                
        except Exception as e:
            self.enumeration_completed_signal.emit(False, f"枚举过程出错: {str(e)}")
        finally:
            if self.session:
                self.session.close()
    
    def check_file_exists(self, url):
        """检查文件是否存在"""
        import time
        start_time = time.time()
        session = self.get_session()
        
        for attempt in range(self.max_retries + 1):
            try:
                # 使用HEAD请求检查文件是否存在
                response = session.head(url, timeout=self.timeout, allow_redirects=True)
                response_time = int((time.time() - start_time) * 1000)
                
                if response.status_code == 200:
                    return True, response_time
                elif response.status_code == 404:
                    return False, response_time
                else:
                    # 其他状态码，重试
                    if attempt < self.max_retries:
                        continue
                    return False, response_time
                    
            except requests.exceptions.Timeout:
                if attempt < self.max_retries:
                    continue
                response_time = int((time.time() - start_time) * 1000)
                return False, response_time
            except requests.exceptions.ProxyError as e:
                if attempt < self.max_retries:
                    continue
                response_time = int((time.time() - start_time) * 1000)
                self.status_signal.emit(f"代理错误: {str(e)[:100]}")
                return False, response_time
            except requests.exceptions.RequestException:
                if attempt < self.max_retries:
                    continue
                response_time = int((time.time() - start_time) * 1000)
                return False, response_time
        
        response_time = int((time.time() - start_time) * 1000)
        return False, response_time
    
    def stop(self):
        """停止工作线程"""
        self.is_running = False
    
    def toggle_pause(self):
        """切换暂停状态"""
        self.paused = not self.paused


class ProxySettingsDialog(QDialog):
    """代理设置对话框类"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("代理设置")
        self.setMinimumWidth(400)
        self.setup_ui()
        
    def setup_ui(self):
        """设置界面"""
        layout = QVBoxLayout(self)
        
        # 启用代理
        self.enable_proxy_check = QCheckBox("启用代理")
        self.enable_proxy_check.setChecked(True)
        layout.addWidget(self.enable_proxy_check)
        
        # 代理设置组
        proxy_group = QGroupBox("代理服务器设置")
        proxy_layout = QGridLayout(proxy_group)
        
        proxy_layout.addWidget(QLabel("代理主机:"), 0, 0)
        self.proxy_host_edit = QLineEdit("127.0.0.1")
        proxy_layout.addWidget(self.proxy_host_edit, 0, 1)
        
        proxy_layout.addWidget(QLabel("代理端口:"), 1, 0)
        self.proxy_port_spin = QSpinBox()
        self.proxy_port_spin.setRange(1, 65535)
        self.proxy_port_spin.setValue(20808)
        proxy_layout.addWidget(self.proxy_port_spin, 1, 1)
        
        proxy_layout.addWidget(QLabel("代理类型:"), 2, 0)
        self.proxy_type_combo = QComboBox()
        self.proxy_type_combo.addItems(["HTTP", "HTTPS", "SOCKS5"])
        proxy_layout.addWidget(self.proxy_type_combo, 2, 1)
        
        layout.addWidget(proxy_group)
        
        # 测试按钮
        test_button = QPushButton("测试代理连接")
        test_button.clicked.connect(self.test_proxy_connection)
        layout.addWidget(test_button)
        
        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
    def test_proxy_connection(self):
        """测试代理连接"""
        if not self.enable_proxy_check.isChecked():
            QMessageBox.warning(self, "警告", "请先启用代理")
            return
        
        proxy_host = self.proxy_host_edit.text().strip()
        proxy_port = self.proxy_port_spin.value()
        proxy_type = self.proxy_type_combo.currentText().lower()
        
        proxy_url = f"{proxy_type}://{proxy_host}:{proxy_port}"
        proxies = {
            'http': proxy_url,
            'https': proxy_url
        }
        
        try:
            # 测试连接到百度
            response = requests.get("http://www.baidu.com", proxies=proxies, timeout=5)
            QMessageBox.information(self, "测试成功", f"代理连接正常！\n响应时间: {response.elapsed.total_seconds()*1000:.0f}ms")
        except Exception as e:
            QMessageBox.critical(self, "测试失败", f"代理连接失败:\n{str(e)}")
    
    def get_proxy_settings(self):
        """获取代理设置"""
        return {
            'enabled': self.enable_proxy_check.isChecked(),
            'host': self.proxy_host_edit.text().strip(),
            'port': self.proxy_port_spin.value(),
            'type': self.proxy_type_combo.currentText().lower()
        }
    
    def set_proxy_settings(self, settings):
        """设置代理设置"""
        self.enable_proxy_check.setChecked(settings.get('enabled', True))
        self.proxy_host_edit.setText(settings.get('host', '127.0.0.1'))
        self.proxy_port_spin.setValue(settings.get('port', 20808))
        
        proxy_type = settings.get('type', 'http')
        index = self.proxy_type_combo.findText(proxy_type.upper())
        if index >= 0:
            self.proxy_type_combo.setCurrentIndex(index)


class ConfigurationManagerClass:
    """配置管理器类"""
    def __init__(self, config_file='enumeration_config.json'):
        self.config_file = config_file
        self.default_config = {
            'base_url': 'http://cachefly.cachefly.net/',
            'start_size': 1,
            'end_size': 10240,
            'step_size': 1,
            'timeout': 3,
            'max_retries': 1,
            'auto_scroll': True,
            'display_filter': 'all',
            'window_geometry': None,
            'window_state': None,
            'last_results': [],
            'discovered_files': [],
            'proxy_settings': {
                'enabled': True,
                'host': '127.0.0.1',
                'port': 20808,
                'type': 'http'
            }
        }
        self.current_config = self.load_config()
    
    def load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    config = self.default_config.copy()
                    if 'proxy_settings' in loaded_config:
                        config['proxy_settings'].update(loaded_config['proxy_settings'])
                    config.update(loaded_config)
                    return config
        except Exception:
            pass
        return self.default_config.copy()
    
    def save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.current_config, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
    
    def get(self, key):
        """获取配置值"""
        return self.current_config.get(key, self.default_config.get(key))
    
    def set(self, key, value):
        """设置配置值"""
        self.current_config[key] = value
        self.save_config()
    
    def get_proxy_settings(self):
        """获取代理设置"""
        return self.current_config.get('proxy_settings', self.default_config['proxy_settings'])
    
    def set_proxy_settings(self, settings):
        """设置代理设置"""
        self.current_config['proxy_settings'] = settings
        self.save_config()
    
    def add_discovered_file(self, file_info):
        """添加已发现文件"""
        discovered = self.current_config.get('discovered_files', [])
        # 避免重复添加
        if not any(f['url'] == file_info['url'] for f in discovered):
            discovered.append(file_info)
            self.current_config['discovered_files'] = discovered
            self.save_config()
    
    def clear_discovered_files(self):
        """清空已发现文件列表"""
        self.current_config['discovered_files'] = []
        self.save_config()
    
    def get_discovered_files(self):
        """获取已发现文件列表"""
        return self.current_config.get('discovered_files', [])


class MainEnumerationWindow(QMainWindow):
    """主枚举窗口类"""
    
    def __init__(self):
        super().__init__()
        self.config_manager = ConfigurationManagerClass()
        self.enumeration_thread = None
        self.results_data = []
        self.discovered_files_widget = None
        self.setup_user_interface()
        self.load_saved_settings()
        self.setup_window_icon()
        
    def setup_user_interface(self):
        """设置用户界面"""
        self.setWindowTitle("文件枚举检测工具 - CacheFly 文件探测器")
        self.setMinimumSize(1300, 800)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局 - 使用水平分割器
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(8, 8, 8, 8)
        
        # 左侧面板 - 标签页
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建标签页
        tab_widget = QTabWidget()
        
        # 枚举标签页
        enumeration_tab = self.create_enumeration_tab()
        tab_widget.addTab(enumeration_tab, "文件枚举")
        
        # 结果统计标签页
        statistics_tab = self.create_statistics_tab()
        tab_widget.addTab(statistics_tab, "统计信息")
        
        # 设置标签页
        settings_tab = self.create_settings_tab()
        tab_widget.addTab(settings_tab, "高级设置")
        
        left_layout.addWidget(tab_widget)
        
        # 右侧面板 - 已发现文件列表
        right_panel = QGroupBox("📋 已发现文件列表")
        right_layout = QVBoxLayout(right_panel)
        
        self.discovered_files_widget = DiscoveredFilesListWidget()
        self.discovered_files_widget.set_config_manager(self.config_manager)
        right_layout.addWidget(self.discovered_files_widget)
        
        # 使用分割器
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([800, 500])
        
        main_layout.addWidget(splitter)
        
    def create_enumeration_tab(self):
        """创建枚举标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        
        # 控制区域
        control_group = QGroupBox("枚举控制")
        control_layout = QGridLayout(control_group)
        control_layout.setSpacing(8)
        
        # URL设置
        control_layout.addWidget(QLabel("基础URL:"), 0, 0)
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("http://cachefly.cachefly.net/")
        self.base_url_edit.setMinimumHeight(30)
        control_layout.addWidget(self.base_url_edit, 0, 1, 1, 3)
        
        # 代理状态显示
        self.proxy_status_label = QLabel()
        self.proxy_status_label.setStyleSheet("QLabel { color: #4CAF50; }")
        control_layout.addWidget(self.proxy_status_label, 0, 4)
        
        # 大小范围设置
        control_layout.addWidget(QLabel("起始大小(MB):"), 1, 0)
        self.start_size_spin = QSpinBox()
        self.start_size_spin.setRange(1, 999999999)
        self.start_size_spin.setSuffix(" MB")
        self.start_size_spin.setMinimumHeight(30)
        control_layout.addWidget(self.start_size_spin, 1, 1)
        
        control_layout.addWidget(QLabel("结束大小(MB):"), 1, 2)
        self.end_size_spin = QSpinBox()
        self.end_size_spin.setRange(1, 999999999)
        self.end_size_spin.setSuffix(" MB")
        self.end_size_spin.setValue(10240)
        self.end_size_spin.setMinimumHeight(30)
        control_layout.addWidget(self.end_size_spin, 1, 3)
        
        control_layout.addWidget(QLabel("步进大小(MB):"), 2, 0)
        self.step_size_spin = QSpinBox()
        self.step_size_spin.setRange(1, 10000)
        self.step_size_spin.setSuffix(" MB")
        self.step_size_spin.setMinimumHeight(30)
        control_layout.addWidget(self.step_size_spin, 2, 1)
        
        # 结果显示过滤选项
        control_layout.addWidget(QLabel("显示过滤:"), 2, 2)
        self.display_filter_combo = QComboBox()
        self.display_filter_combo.addItems(["全部显示", "只显示存在的文件", "只显示不存在的文件"])
        self.display_filter_combo.currentIndexChanged.connect(self.apply_display_filter)
        self.display_filter_combo.setMinimumHeight(30)
        control_layout.addWidget(self.display_filter_combo, 2, 3)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("开始枚举")
        self.start_button.clicked.connect(self.start_enumeration)
        self.start_button.setMinimumHeight(38)
        self.start_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        
        self.pause_button = QPushButton("暂停")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.pause_button.setEnabled(False)
        self.pause_button.setMinimumHeight(38)
        
        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self.stop_enumeration)
        self.stop_button.setEnabled(False)
        self.stop_button.setMinimumHeight(38)
        self.stop_button.setStyleSheet("QPushButton { background-color: #f44336; color: white; }")
        
        self.clear_button = QPushButton("清空结果")
        self.clear_button.clicked.connect(self.clear_results)
        self.clear_button.setMinimumHeight(38)
        
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.pause_button)
        button_layout.addWidget(self.stop_button)
        button_layout.addWidget(self.clear_button)
        control_layout.addLayout(button_layout, 3, 0, 1, 5)
        
        # 进度显示
        control_layout.addWidget(QLabel("枚举进度:"), 4, 0)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(25)
        control_layout.addWidget(self.progress_bar, 4, 1, 1, 4)
        
        self.progress_label = QLabel("就绪")
        control_layout.addWidget(self.progress_label, 5, 0, 1, 5)
        
        layout.addWidget(control_group)
        
        # 结果表格
        results_group = QGroupBox("枚举结果")
        results_layout = QVBoxLayout(results_group)
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(["文件大小(MB)", "文件URL", "状态", "响应时间(ms)", "完整路径"])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)
        
        results_layout.addWidget(self.results_table)
        layout.addWidget(results_group, 1)
        
        # 日志区域
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setMaximumHeight(150)
        
        self.auto_scroll_check = QCheckBox("自动滚动日志")
        self.auto_scroll_check.setChecked(True)
        
        clear_log_button = QPushButton("清空日志")
        clear_log_button.clicked.connect(self.clear_log)
        
        log_control_layout = QHBoxLayout()
        log_control_layout.addWidget(self.auto_scroll_check)
        log_control_layout.addStretch()
        log_control_layout.addWidget(clear_log_button)
        
        log_layout.addWidget(self.log_text)
        log_layout.addLayout(log_control_layout)
        layout.addWidget(log_group)
        
        return tab
    
    def create_statistics_tab(self):
        """创建统计信息标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # 统计信息显示
        stats_group = QGroupBox("统计信息")
        stats_layout = QGridLayout(stats_group)
        
        self.total_checked_label = QLabel("总检查文件数: 0")
        self.total_checked_label.setFont(QFont("Arial", 11, QFont.Bold))
        stats_layout.addWidget(self.total_checked_label, 0, 0)
        
        self.found_files_label = QLabel("找到文件数: 0")
        self.found_files_label.setFont(QFont("Arial", 11, QFont.Bold))
        self.found_files_label.setStyleSheet("color: #4CAF50;")
        stats_layout.addWidget(self.found_files_label, 0, 1)
        
        self.not_found_label = QLabel("未找到文件数: 0")
        self.not_found_label.setFont(QFont("Arial", 11))
        self.not_found_label.setStyleSheet("color: #f44336;")
        stats_layout.addWidget(self.not_found_label, 0, 2)
        
        self.success_rate_label = QLabel("成功率: 0%")
        self.success_rate_label.setFont(QFont("Arial", 11, QFont.Bold))
        stats_layout.addWidget(self.success_rate_label, 1, 0)
        
        self.avg_response_label = QLabel("平均响应时间: 0ms")
        self.avg_response_label.setFont(QFont("Arial", 11))
        stats_layout.addWidget(self.avg_response_label, 1, 1)
        
        self.min_response_label = QLabel("最小响应时间: 0ms")
        stats_layout.addWidget(self.min_response_label, 1, 2)
        
        self.max_response_label = QLabel("最大响应时间: 0ms")
        stats_layout.addWidget(self.max_response_label, 2, 0)
        
        layout.addWidget(stats_group)
        
        # 存在的文件列表
        existing_group = QGroupBox("存在的文件列表")
        existing_layout = QVBoxLayout(existing_group)
        
        self.existing_files_list = QTextEdit()
        self.existing_files_list.setReadOnly(True)
        self.existing_files_list.setFont(QFont("Consolas", 10))
        existing_layout.addWidget(self.existing_files_list)
        
        # 导出按钮
        export_button = QPushButton("导出结果到文件")
        export_button.clicked.connect(self.export_results)
        export_button.setMinimumHeight(35)
        existing_layout.addWidget(export_button)
        
        layout.addWidget(existing_group)
        
        return tab
    
    def create_settings_tab(self):
        """创建设置标签页"""
        tab = QWidget()
        layout = QGridLayout(tab)
        layout.setSpacing(10)
        
        # 网络设置
        network_group = QGroupBox("网络设置")
        network_layout = QGridLayout(network_group)
        
        network_layout.addWidget(QLabel("请求超时(秒):"), 0, 0)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 30)
        self.timeout_spin.setSuffix(" 秒")
        network_layout.addWidget(self.timeout_spin, 0, 1)
        
        network_layout.addWidget(QLabel("最大重试次数:"), 1, 0)
        self.max_retries_spin = QSpinBox()
        self.max_retries_spin.setRange(0, 5)
        self.max_retries_spin.setSuffix(" 次")
        network_layout.addWidget(self.max_retries_spin, 1, 1)
        
        layout.addWidget(network_group, 0, 0)
        
        # 代理设置
        proxy_group = QGroupBox("代理设置")
        proxy_layout = QVBoxLayout(proxy_group)
        
        self.proxy_status_text = QLabel()
        self.proxy_status_text.setText("加载中...")
        proxy_layout.addWidget(self.proxy_status_text)
        
        proxy_button = QPushButton("配置代理")
        proxy_button.clicked.connect(self.configure_proxy)
        proxy_button.setMinimumHeight(30)
        proxy_layout.addWidget(proxy_button)
        
        layout.addWidget(proxy_group, 1, 0)
        
        # 显示设置
        display_group = QGroupBox("显示设置")
        display_layout = QGridLayout(display_group)
        
        self.highlight_existing_check = QCheckBox("高亮显示存在的文件")
        self.highlight_existing_check.setChecked(True)
        display_layout.addWidget(self.highlight_existing_check, 0, 0)
        
        self.show_timestamp_check = QCheckBox("显示时间戳")
        self.show_timestamp_check.setChecked(True)
        display_layout.addWidget(self.show_timestamp_check, 0, 1)
        
        layout.addWidget(display_group, 2, 0)
        
        # 保存设置按钮
        save_settings_button = QPushButton("保存所有设置")
        save_settings_button.clicked.connect(self.save_all_settings)
        save_settings_button.setMinimumHeight(35)
        layout.addWidget(save_settings_button, 3, 0)
        
        layout.setRowStretch(4, 1)
        
        return tab
    
    def update_proxy_status_display(self):
        """更新代理状态显示"""
        proxy_settings = self.config_manager.get_proxy_settings()
        if proxy_settings.get('enabled', False):
            status_text = f"✓ 代理已启用: {proxy_settings.get('host', '')}:{proxy_settings.get('port', '')} ({proxy_settings.get('type', 'http').upper()})"
            self.proxy_status_text.setText(status_text)
            self.proxy_status_text.setStyleSheet("color: #4CAF50;")
            if hasattr(self, 'proxy_status_label'):
                self.proxy_status_label.setText(f"代理: {proxy_settings.get('host', '')}:{proxy_settings.get('port', '')}")
                self.proxy_status_label.setStyleSheet("color: #4CAF50;")
        else:
            status_text = "✗ 代理未启用 (直接连接)"
            self.proxy_status_text.setText(status_text)
            self.proxy_status_text.setStyleSheet("color: #f44336;")
            if hasattr(self, 'proxy_status_label'):
                self.proxy_status_label.setText("代理: 未启用")
                self.proxy_status_label.setStyleSheet("color: #f44336;")
        
        # 同步代理设置到右侧列表组件
        if self.discovered_files_widget is not None:
            self.discovered_files_widget.set_proxy_settings(proxy_settings)
    
    def configure_proxy(self):
        """配置代理"""
        dialog = ProxySettingsDialog(self)
        dialog.set_proxy_settings(self.config_manager.get_proxy_settings())
        
        if dialog.exec() == QDialog.Accepted:
            new_settings = dialog.get_proxy_settings()
            self.config_manager.set_proxy_settings(new_settings)
            self.update_proxy_status_display()
            self.log_message(f"代理设置已更新: {'已启用' if new_settings['enabled'] else '已禁用'}")
            QMessageBox.information(self, "设置成功", "代理设置已保存！")
    
    def setup_window_icon(self):
        """设置窗口图标"""
        if os.path.exists("icon.ico"):
            self.setWindowIcon(QIcon("icon.ico"))
    
    def load_saved_settings(self):
        """加载保存的设置"""
        self.base_url_edit.setText(self.config_manager.get('base_url'))
        self.start_size_spin.setValue(self.config_manager.get('start_size'))
        self.end_size_spin.setValue(self.config_manager.get('end_size'))
        self.step_size_spin.setValue(self.config_manager.get('step_size'))
        self.timeout_spin.setValue(self.config_manager.get('timeout'))
        self.max_retries_spin.setValue(self.config_manager.get('max_retries'))
        self.auto_scroll_check.setChecked(self.config_manager.get('auto_scroll'))
        
        # 加载显示过滤设置
        filter_setting = self.config_manager.get('display_filter')
        if filter_setting == 'existing_only':
            self.display_filter_combo.setCurrentIndex(1)
        elif filter_setting == 'non_existing_only':
            self.display_filter_combo.setCurrentIndex(2)
        else:
            self.display_filter_combo.setCurrentIndex(0)
        
        # 更新代理状态显示
        self.update_proxy_status_display()
        
        # 恢复窗口大小和位置
        geometry = self.config_manager.get('window_geometry')
        if geometry:
            try:
                self.restoreGeometry(bytes(geometry))
            except:
                pass
        
        window_state = self.config_manager.get('window_state')
        if window_state:
            try:
                self.restoreState(bytes(window_state))
            except:
                pass
        
        # 加载上次结果
        last_results = self.config_manager.get('last_results')
        if last_results:
            for result in last_results:
                self.add_result_to_table(result['url'], result['size'], 
                                        result['exists'], result['response_time'])
            self.update_statistics()
        
        # 加载已发现文件列表
        if self.discovered_files_widget is not None:
            discovered_files = self.config_manager.get_discovered_files()
            self.discovered_files_widget.load_from_data(discovered_files)
    
    def save_all_settings(self):
        """保存所有设置"""
        self.config_manager.set('base_url', self.base_url_edit.text())
        self.config_manager.set('start_size', self.start_size_spin.value())
        self.config_manager.set('end_size', self.end_size_spin.value())
        self.config_manager.set('step_size', self.step_size_spin.value())
        self.config_manager.set('timeout', self.timeout_spin.value())
        self.config_manager.set('max_retries', self.max_retries_spin.value())
        self.config_manager.set('auto_scroll', self.auto_scroll_check.isChecked())
        
        # 保存显示过滤设置
        filter_index = self.display_filter_combo.currentIndex()
        if filter_index == 1:
            self.config_manager.set('display_filter', 'existing_only')
        elif filter_index == 2:
            self.config_manager.set('display_filter', 'non_existing_only')
        else:
            self.config_manager.set('display_filter', 'all')
        
        # 保存结果数据
        results_to_save = []
        for row in range(self.results_table.rowCount()):
            result = {
                'url': self.results_table.item(row, 1).text(),
                'size': int(self.results_table.item(row, 0).text()),
                'exists': self.results_table.item(row, 2).text() == "存在",
                'response_time': int(self.results_table.item(row, 3).text())
            }
            results_to_save.append(result)
        self.config_manager.set('last_results', results_to_save)
        
        # 保存已发现文件列表（由组件自己保存，但这里再确保一次）
        if self.discovered_files_widget:
            self.discovered_files_widget.save_to_config()
        
        self.log_message("所有设置已保存")
        QMessageBox.information(self, "保存成功", "设置已成功保存！")
    
    def apply_display_filter(self):
        """应用显示过滤"""
        filter_text = self.display_filter_combo.currentText()
        
        for row in range(self.results_table.rowCount()):
            status_item = self.results_table.item(row, 2)
            if status_item:
                is_existing = status_item.text() == "存在"
                
                if filter_text == "只显示存在的文件":
                    self.results_table.setRowHidden(row, not is_existing)
                elif filter_text == "只显示不存在的文件":
                    self.results_table.setRowHidden(row, is_existing)
                else:  # 全部显示
                    self.results_table.setRowHidden(row, False)
    
    def start_enumeration(self):
        """开始枚举"""
        # 验证输入
        base_url = self.base_url_edit.text().strip()
        if not base_url:
            QMessageBox.warning(self, "警告", "请输入基础URL")
            return
        
        if not base_url.endswith('/'):
            base_url += '/'
            self.base_url_edit.setText(base_url)
        
        start_size = self.start_size_spin.value()
        end_size = self.end_size_spin.value()
        step_size = self.step_size_spin.value()
        
        if start_size > end_size:
            QMessageBox.warning(self, "警告", "起始大小不能大于结束大小")
            return
        
        # 获取代理设置
        proxy_settings = self.config_manager.get_proxy_settings()
        
        # 清空现有结果（可选）
        reply = QMessageBox.question(self, "确认", "是否清空现有结果？", 
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            self.clear_results()
        
        # 创建并启动工作线程
        self.enumeration_thread = EnumerationWorkerThread(
            base_url, start_size, end_size, step_size, 
            self.timeout_spin.value(), self.max_retries_spin.value(),
            proxy_settings.get('enabled', False),
            proxy_settings.get('host', '127.0.0.1'),
            proxy_settings.get('port', 20808)
        )
        
        # 连接信号
        self.enumeration_thread.progress_signal.connect(self.update_progress)
        self.enumeration_thread.status_signal.connect(self.log_message)
        self.enumeration_thread.file_result_signal.connect(self.add_result)
        self.enumeration_thread.enumeration_completed_signal.connect(self.enumeration_completed)
        
        # 启动线程
        self.enumeration_thread.start()
        
        # 更新按钮状态
        self.start_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        
        proxy_info = "使用代理" if proxy_settings.get('enabled') else "直连"
        self.log_message(f"开始枚举文件... ({proxy_info})")
    
    def toggle_pause(self):
        """切换暂停状态"""
        if self.enumeration_thread:
            self.enumeration_thread.toggle_pause()
            if self.enumeration_thread.paused:
                self.pause_button.setText("继续")
                self.log_message("枚举已暂停")
            else:
                self.pause_button.setText("暂停")
                self.log_message("枚举继续")
    
    def stop_enumeration(self):
        """停止枚举"""
        if self.enumeration_thread and self.enumeration_thread.isRunning():
            self.enumeration_thread.stop()
            self.log_message("正在停止枚举...")
    
    def update_progress(self, current, total):
        """更新进度条"""
        if total > 0:
            progress = int((current / total) * 100)
            self.progress_bar.setValue(progress)
            self.progress_label.setText(f"进度: {current}/{total} ({progress}%)")
    
    def add_result(self, url, size_mb, exists, response_time):
        """添加结果到表格"""
        self.add_result_to_table(url, size_mb, exists, response_time)
        self.update_statistics()
        
        # 如果文件存在，添加到右侧已发现文件列表
        if exists and self.discovered_files_widget is not None:
            self.discovered_files_widget.add_file(size_mb, url, response_time)
            # 更新统计标签页的现有文件列表
            self.existing_files_list.append(f"{size_mb}MB - {url} (响应时间: {response_time}ms)\n")
            if self.auto_scroll_check.isChecked():
                cursor = self.existing_files_list.textCursor()
                cursor.movePosition(QTextCursor.End)
                self.existing_files_list.setTextCursor(cursor)
        
        # 应用当前过滤
        self.apply_display_filter()
    
    def add_result_to_table(self, url, size_mb, exists, response_time):
        """添加结果到表格的实现"""
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        
        # 大小
        size_item = QTableWidgetItem(str(size_mb))
        size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.results_table.setItem(row, 0, size_item)
        
        # URL（简化显示）
        url_item = QTableWidgetItem(url)
        self.results_table.setItem(row, 1, url_item)
        
        # 状态
        status = "存在" if exists else "不存在"
        status_item = QTableWidgetItem(status)
        if exists and self.highlight_existing_check.isChecked():
            status_item.setBackground(QColor(200, 255, 200))
            status_item.setForeground(QColor(0, 100, 0))
        else:
            status_item.setBackground(QColor(255, 200, 200))
            status_item.setForeground(QColor(150, 0, 0))
        status_item.setTextAlignment(Qt.AlignCenter)
        self.results_table.setItem(row, 2, status_item)
        
        # 响应时间
        time_item = QTableWidgetItem(str(response_time))
        time_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.results_table.setItem(row, 3, time_item)
        
        # 完整路径
        path_item = QTableWidgetItem(url)
        self.results_table.setItem(row, 4, path_item)
        
        # 保存数据
        self.results_data.append({
            'url': url, 'size': size_mb, 'exists': exists, 'response_time': response_time
        })
    
    def update_statistics(self):
        """更新统计信息"""
        total = self.results_table.rowCount()
        existing = 0
        total_response_time = 0
        min_time = float('inf')
        max_time = 0
        
        for row in range(total):
            status_item = self.results_table.item(row, 2)
            time_item = self.results_table.item(row, 3)
            
            if status_item and status_item.text() == "存在":
                existing += 1
            
            if time_item:
                response_time = int(time_item.text())
                total_response_time += response_time
                min_time = min(min_time, response_time)
                max_time = max(max_time, response_time)
        
        not_found = total - existing
        success_rate = (existing / total * 100) if total > 0 else 0
        avg_response = (total_response_time / total) if total > 0 else 0
        
        self.total_checked_label.setText(f"总检查文件数: {total}")
        self.found_files_label.setText(f"找到文件数: {existing}")
        self.not_found_label.setText(f"未找到文件数: {not_found}")
        self.success_rate_label.setText(f"成功率: {success_rate:.1f}%")
        self.avg_response_label.setText(f"平均响应时间: {avg_response:.0f}ms")
        self.min_response_label.setText(f"最小响应时间: {min_time if min_time != float('inf') else 0}ms")
        self.max_response_label.setText(f"最大响应时间: {max_time}ms")
    
    def enumeration_completed(self, success, message):
        """枚举完成处理"""
        self.log_message(message)
        
        # 恢复按钮状态
        self.start_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.pause_button.setText("暂停")
        
        if success:
            QMessageBox.information(self, "枚举完成", message)
    
    def clear_results(self):
        """清空结果"""
        self.results_table.setRowCount(0)
        self.results_data.clear()
        self.existing_files_list.clear()
        self.progress_bar.setValue(0)
        self.progress_label.setText("就绪")
        self.update_statistics()
        self.log_message("已清空所有结果")
    
    def clear_log(self):
        """清空日志"""
        self.log_text.clear()
    
    def export_results(self):
        """导出结果到文件"""
        if self.results_table.rowCount() == 0:
            QMessageBox.warning(self, "警告", "没有结果可导出")
            return
        
        from PySide6.QtWidgets import QFileDialog
        
        file_path, _ = QFileDialog.getSaveFileName(self, "导出结果", "", "文本文件 (*.txt);;CSV文件 (*.csv);;JSON文件 (*.json)")
        
        if file_path:
            try:
                if file_path.endswith('.csv'):
                    self.export_to_csv(file_path)
                elif file_path.endswith('.json'):
                    self.export_to_json(file_path)
                else:
                    self.export_to_text(file_path)
                
                QMessageBox.information(self, "导出成功", f"结果已导出到: {file_path}")
                self.log_message(f"结果已导出到: {file_path}")
                
            except Exception as e:
                QMessageBox.critical(self, "导出失败", f"导出过程中出错: {str(e)}")
    
    def export_to_text(self, file_path):
        """导出为文本文件"""
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write("CacheFly 文件枚举结果\n")
            f.write("=" * 80 + "\n\n")
            
            for row in range(self.results_table.rowCount()):
                if not self.results_table.isRowHidden(row):
                    size = self.results_table.item(row, 0).text()
                    url = self.results_table.item(row, 1).text()
                    status = self.results_table.item(row, 2).text()
                    response_time = self.results_table.item(row, 3).text()
                    
                    f.write(f"大小: {size}MB\n")
                    f.write(f"URL: {url}\n")
                    f.write(f"状态: {status}\n")
                    f.write(f"响应时间: {response_time}ms\n")
                    f.write("-" * 40 + "\n")
    
    def export_to_csv(self, file_path):
        """导出为CSV文件"""
        import csv
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["文件大小(MB)", "文件URL", "状态", "响应时间(ms)", "完整路径"])
            
            for row in range(self.results_table.rowCount()):
                if not self.results_table.isRowHidden(row):
                    writer.writerow([
                        self.results_table.item(row, 0).text(),
                        self.results_table.item(row, 1).text(),
                        self.results_table.item(row, 2).text(),
                        self.results_table.item(row, 3).text(),
                        self.results_table.item(row, 4).text()
                    ])
    
    def export_to_json(self, file_path):
        """导出为JSON文件"""
        import json
        export_data = []
        for row in range(self.results_table.rowCount()):
            if not self.results_table.isRowHidden(row):
                export_data.append({
                    'size_mb': int(self.results_table.item(row, 0).text()),
                    'url': self.results_table.item(row, 1).text(),
                    'exists': self.results_table.item(row, 2).text() == "存在",
                    'response_time_ms': int(self.results_table.item(row, 3).text()),
                    'full_url': self.results_table.item(row, 4).text()
                })
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
    
    def log_message(self, message):
        """记录日志消息"""
        if self.show_timestamp_check.isChecked():
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            formatted_message = f"[{timestamp}] {message}"
        else:
            formatted_message = message
        
        self.log_text.append(formatted_message)
        
        if self.auto_scroll_check.isChecked():
            cursor = self.log_text.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.log_text.setTextCursor(cursor)
    
    def closeEvent(self, event):
        """关闭事件处理"""
        # 保存窗口几何信息
        geometry = self.saveGeometry()
        self.config_manager.set('window_geometry', list(geometry))
        
        window_state = self.saveState()
        self.config_manager.set('window_state', list(window_state))
        
        # 保存已发现文件列表
        if self.discovered_files_widget:
            self.discovered_files_widget.save_to_config()
        
        # 停止工作线程
        if self.enumeration_thread and self.enumeration_thread.isRunning():
            self.enumeration_thread.stop()
            self.enumeration_thread.wait(2000)
        
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 创建主窗口
    window = MainEnumerationWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()