#使用python38编译成exe打包命令 pyinstaller --onefile --name tsh_proxy_client proxy_client.py

import socket
import sys
import argparse
import signal
import logging
import threading
from queue import Queue
import struct
import time
import msvcrt
import ctypes
from ctypes import wintypes
import re

# Windows控制台处理
kernel32 = ctypes.windll.kernel32
STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
ENABLE_WINDOW_INPUT = 0x0008
ENABLE_MOUSE_INPUT = 0x0010
ENABLE_INSERT_MODE = 0x0020
ENABLE_QUICK_EDIT_MODE = 0x0040

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TerminalSize:
    def __init__(self, rows=0, cols=0):
        self.rows = rows
        self.cols = cols

class WindowsPtyClient:
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
                # Send terminal size using VT100 sequence
                size_data = bytearray(8)
                size_data[0] = 0xFF #标记
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
        h = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        csbi = ctypes.create_string_buffer(22)
        res = kernel32.GetConsoleScreenBufferInfo(h, csbi)
        if res:
            (_, _, _, _, _, left, top, right, bottom, _, _) = struct.unpack("hhhhHhhhhhh", csbi.raw)
            columns = right - left + 1
            rows = bottom - top + 1
            return TerminalSize(rows, columns)
        return TerminalSize()

    def setup_terminal(self):
        # Enable VT100 for input
        h_in = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        mode = wintypes.DWORD()
        kernel32.GetConsoleMode(h_in, ctypes.byref(mode))
        orig_mode = mode.value
        new_mode = (orig_mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING) & ~(ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT)
        kernel32.SetConsoleMode(h_in, new_mode)

        # Enable VT100 for output
        h_out = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = wintypes.DWORD()
        kernel32.GetConsoleMode(h_out, ctypes.byref(mode))
        orig_mode = mode.value
        new_mode = orig_mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel32.SetConsoleMode(h_out, new_mode)

    def restore_terminal(self):
        h_in = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        mode = wintypes.DWORD()
        kernel32.GetConsoleMode(h_in, ctypes.byref(mode))
        mode = mode.value | ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT
        kernel32.SetConsoleMode(h_in, mode)

    def input_handler(self):
        try:
            while self.running:
                if msvcrt.kbhit():
                    char = msvcrt.getch()
                    if char in [b'\x00', b'\xe0']:
                        char2 = msvcrt.getch()
                        if char2 == b'H':  # Up arrow
                            self.input_queue.put(b'\x1bOA')
                        elif char2 == b'P':  # Down arrow
                            self.input_queue.put(b'\x1bOB')
                        elif char2 == b'M':  # Right arrow
                            self.input_queue.put(b'\x1bOC')
                        elif char2 == b'K':  # Left arrow
                            self.input_queue.put(b'\x1bOD')
                    else:
                        self.input_queue.put(char)
                time.sleep(0.01)
        except Exception as e:
            logger.error(f"Input handler error: {e}")
            self.running = False

    def output_handler(self):
        try:
            while self.running:
                try:
                    data = self.socket.recv(4096)
                    if not data:
                        break

                    # 检查是否包含 exit 消息
                    try:
                        decoded_data = data.decode('utf-8', errors='ignore')
                        if decoded_data == '\r\nexit\r\n' or decoded_data == 'exit\r\n' or decoded_data == 'exit' or decoded_data == '\r\nexit':
                            self.running = False
                            # 确保最后的输出能够显示
                            # self.output_queue.put(data)
                            # 给其他线程一点时间来处理最后的数据
                            time.sleep(0.5)
                            # 清理并退出
                            self.cleanup()
                            sys.exit(0)
                    except UnicodeDecodeError:
                        pass

                    if "Connected with correct identifier." in decoded_data:
                        # Send initial terminal size
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

    def filter_terminal_responses(self, data):
        try:
            text = data.decode('utf-8', errors='ignore')
            text = re.sub(r';[0-9]+;[0-9]+t', '', text)
            text = text.replace('\x07', '')
            return text.encode('utf-8')
        except Exception as e:
            logger.debug(f"Error filtering data: {e}")
            return data

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

    def run(self):
        """运行客户端"""
        try:
            self.connect()
            self.setup_terminal()
            self.running = True
            
            # 启动处理线程
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
            self.restore_terminal()
            if self.socket:
                self.socket.close()
            logger.debug(f"Connection closed for session {self.identifier}")

def main():
    if sys.platform != 'win32':
        print("This client is for Windows only!")
        sys.exit(1)
        
    parser = argparse.ArgumentParser(description='Windows PTY Client')
    parser.add_argument('host', help='Server host')
    parser.add_argument('--port', type=int, default=8080, help='Server port')
    parser.add_argument('--identifier', required=True, help='Unique 16-character session identifier')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    client = WindowsPtyClient(args.host, args.port, args.identifier)
    
    def signal_handler(sig, frame):
        logger.debug("\nReceived interrupt signal")
        client.running = False
        client.restore_terminal()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    client.run()

if __name__ == "__main__":
    main()