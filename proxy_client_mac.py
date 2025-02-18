#编译elf, Mach-O文件，# 1. 安装必要的包
# sudo apt install python3-full python3-pip python3-venv

# # 2. 创建项目目录并进入，不能选择共享文件夹
# mkdir tsh_project 
# cd tsh_project

# # 3. 创建虚拟环境
# python3 -m venv venv

# # 4. 激活虚拟环境
# source venv/bin/activate

# # 5. 安装 pyinstaller
# pip install pyinstaller

# # 6. 复制你的 Python 脚本到当前目录
# cp /path/to/proxy_client_mac.py .

# # 7. 运行打包命令
# pyinstaller --onefile --name tsh_proxy_client proxy_client_mac.py

# # 8. 完成后可以退出虚拟环境
# deactivate

#!/usr/bin/env python3
import socket
import sys
import argparse
import signal
import logging
import threading
from queue import Queue
import struct
import time
import termios
import fcntl
import os
import tty
import select

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TerminalSize:
    def __init__(self, rows=0, cols=0):
        self.rows = rows
        self.cols = cols

class UnixPtyClient:
    def __init__(self, host: str, port: int, identifier: str):
        self.host = host
        self.port = port
        self.identifier = identifier
        self.socket = None
        self.input_queue = Queue()
        self.output_queue = Queue()
        self.running = False
        self.terminal_size = TerminalSize()
        self.output_buffer = bytearray()
        self.old_settings = None

    def connect(self):
        """连接到代理服务器并发送会话标识符"""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
        
        # 首先发送标识符
        self.socket.send(self.identifier.encode('ascii'))
        
        self.socket.setblocking(False)
        logger.debug(f"Connected to proxy server with identifier {self.identifier}")

    def send_terminal_size(self, size):
        """Send terminal size using ANSI escape sequence"""
        if self.socket:
            try:
                size_data = bytearray(8)
                size_data[0] = 0xFF  # 标记
                size_data[1] = 0xFF
                size_data[2] = 0xFF
                size_data[3] = 0xFF
                size_data[4] = (size.rows >> 8) & 0xFF    # 行数高字节
                size_data[5] = size.rows & 0xFF           # 行数低字节
                size_data[6] = (size.cols >> 8) & 0xFF    # 列数高字节
                size_data[7] = size.cols & 0xFF           # 列数低字节
                self.socket.send(size_data)
                logger.debug(f"Sent terminal size: {size.rows}x{size.cols}")
            except Exception as e:
                logger.error(f"Failed to send terminal size: {e}")

    def get_terminal_size(self):
        """获取终端大小"""
        try:
            size = struct.unpack('HHHH', fcntl.ioctl(sys.stdout.fileno(),
                               termios.TIOCGWINSZ, struct.pack('HHHH', 0, 0, 0, 0)))
            return TerminalSize(size[0], size[1])
        except:
            return TerminalSize(24, 80)  # 默认值

    def setup_terminal(self):
        """设置终端为原始模式"""
        fd = sys.stdin.fileno()
        self.old_settings = termios.tcgetattr(fd)
        tty.setraw(fd)
        # 设置标准输入为非阻塞模式
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def restore_terminal(self):
        """恢复终端设置"""
        if self.old_settings:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.old_settings)

    def input_handler(self):
        """处理输入"""
        try:
            while self.running:
                try:
                    # 使用 select 进行非阻塞读取
                    r, _, _ = select.select([sys.stdin], [], [], 0.1)
                    if r:
                        char = sys.stdin.buffer.read1(1)
                        if char:
                            self.input_queue.put(char)
                except (IOError, select.error):
                    time.sleep(0.01)
                    continue
        except Exception as e:
            logger.error(f"Input handler error: {e}")
            self.running = False

    def output_handler(self):
        """处理输出"""
        try:
            while self.running:
                try:
                    data = self.socket.recv(4096)
                    if not data:
                        break

                    try:
                        decoded_data = data.decode('utf-8', errors='ignore')
                        if decoded_data in ['\r\nexit\r\n', 'exit\r\n', 'exit', '\r\nexit']:
                            self.running = False
                            time.sleep(0.5)
                            self.cleanup()
                            sys.exit(0)
                    except UnicodeDecodeError:
                        pass

                    if "Connected with correct identifier." in data.decode('utf-8', errors='ignore'):
                        self.terminal_size = self.get_terminal_size()
                        self.send_terminal_size(self.terminal_size)
                        continue

                    self.output_queue.put(data)
                except (BlockingIOError, socket.error):
                    time.sleep(0.01)
                    continue
        except Exception as e:
            logger.error(f"Output handler error: {e}")
            self.running = False

    def display_handler(self):
        """处理显示输出"""
        try:
            while self.running:
                try:
                    data = self.output_queue.get(timeout=0.1)
                    if data:
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Display handler error: {e}")
            self.running = False

    def network_handler(self):
        """处理网络通信"""
        try:
            while self.running:
                try:
                    data = self.input_queue.get(timeout=0.1)
                    if data == b'\x03':  # Ctrl+C
                        self.running = False
                        break
                    self.socket.send(data)
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Network handler error: {e}")
            self.running = False

    def cleanup(self):
        """清理资源"""
        self.restore_terminal()
        if self.socket:
            self.socket.close()

    def run(self):
        """运行客户端"""
        try:
            self.connect()
            self.setup_terminal()
            self.running = True
            
            threads = [
                threading.Thread(target=self.input_handler),
                threading.Thread(target=self.output_handler),
                threading.Thread(target=self.display_handler),
                threading.Thread(target=self.network_handler)
            ]
            
            for thread in threads:
                thread.daemon = True
                thread.start()
            
            while self.running:
                if self.terminal_size.rows != 0:
                    new_size = self.get_terminal_size()
                    if (new_size.rows != self.terminal_size.rows or 
                        new_size.cols != self.terminal_size.cols):
                        self.terminal_size = new_size
                        self.send_terminal_size(new_size)
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            logger.debug("\nReceived keyboard interrupt")
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        finally:
            self.running = False
            self.cleanup()
            logger.debug(f"Connection closed for session {self.identifier}")

def main():
    if sys.platform == 'win32':
        print("This client is for Unix-like systems (Linux/macOS) only!")
        sys.exit(1)
        
    parser = argparse.ArgumentParser(description='Unix PTY Client')
    parser.add_argument('host', help='Server host')
    parser.add_argument('--port', type=int, default=8080, help='Server port')
    parser.add_argument('--identifier', required=True, help='Unique 16-character session identifier')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    client = UnixPtyClient(args.host, args.port, args.identifier)
    
    def signal_handler(sig, frame):
        logger.debug("\nReceived interrupt signal")
        client.running = False
        client.restore_terminal()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    client.run()

if __name__ == "__main__":
    main()