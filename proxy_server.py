import socket
import threading
import select
import subprocess
import fcntl
import os
import logging
import argparse
import pty
import termios
import struct
import time
from typing import Dict, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TshSession:
    """管理单个TSH会话的类"""
    def __init__(self, identifier: str, tsh_path: str):
        self.identifier = identifier
        self.tsh_path = tsh_path
        self.master_fd: Optional[int] = None
        self.slave_fd: Optional[int] = None
        self.tsh_process: Optional[subprocess.Popen] = None
        self.client_socket: Optional[socket.socket] = None
        self.running = False
        self.lock = threading.Lock()

    def start(self):
        """启动TSH进程和PTY"""
        try:
            # 创建PTY
            self.master_fd, self.slave_fd = pty.openpty()
            
            # 设置master fd为非阻塞模式
            fl = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            
            # 启动TSH进程
            logger.info(f"Starting TSH for session {self.identifier}")
            self.tsh_process = subprocess.Popen(
                [self.tsh_path, self.identifier],
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                preexec_fn=os.setsid
            )
            
            # 等待进程启动
            time.sleep(1)
            if self.tsh_process.poll() is not None:
                raise Exception(f"TSH process exited with code {self.tsh_process.returncode}")
            
            self.running = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to start TSH session {self.identifier}: {e}")
            self.cleanup()
            return False

    def cleanup(self):
        """清理会话资源"""
        self.running = False
        
        if self.tsh_process:
            try:
                self.tsh_process.terminate()
                self.tsh_process.wait(timeout=5)
            except:
                self.tsh_process.kill()
        
        if self.master_fd:
            try:
                os.close(self.master_fd)
            except:
                pass
                
        if self.slave_fd:
            try:
                os.close(self.slave_fd)
            except:
                pass
            
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass

class MultiTshProxy:
    """管理多个TSH会话的代理服务器"""
    def __init__(self, proxy_port: int, tsh_path: str = "./tsh"):
        self.proxy_port = proxy_port
        self.tsh_path = tsh_path
        self.sessions: Dict[str, TshSession] = {}
        self.sessions_lock = threading.Lock()
        self.running = True

    def handle_session_io(self, session: TshSession):
        """处理单个会话的IO转发"""
        try:
            while session.running:
                # 等待socket或PTY的数据
                rd_list = [session.client_socket, session.master_fd]
                rd, _, _ = select.select(rd_list, [], [], 0.1)
                
                for fd in rd:
                    try:
                        if fd == session.client_socket:
                            # 从客户端读取数据并写入TSH
                            data = session.client_socket.recv(4096)
                            if not data:
                                raise Exception("Client closed connection")
                            os.write(session.master_fd, data)
                            logger.debug(f"Write to {session.identifier} TSH: {data}")
                            
                        elif fd == session.master_fd:
                            # 从TSH读取数据并发送给客户端
                            data = os.read(session.master_fd, 4096)
                            if data:
                                logger.debug(f"Read from {session.identifier} TSH: {data}")
                            if not data:
                                raise Exception("TSH closed connection")
                            session.client_socket.send(data)
                    except (BlockingIOError, OSError) as e:
                        if e.errno == 11:  # EAGAIN/EWOULDBLOCK
                            continue
                        raise
                        
        except Exception as e:
            logger.error(f"Session {session.identifier} IO error: {e}")
        finally:
            logger.info(f"Cleaning up session {session.identifier}")
            with self.sessions_lock:
                if session.identifier in self.sessions:
                    del self.sessions[session.identifier]
            session.cleanup()

    def handle_client(self, client_socket: socket.socket, addr: tuple):
        """处理新的客户端连接"""
        try:
            # 首先接收16字节的标识符
            identifier = client_socket.recv(16).decode('ascii')
            if not identifier or len(identifier) != 16:
                logger.error(f"Invalid identifier from {addr}")
                client_socket.close()
                return
                
            logger.info(f"New client connection from {addr} with identifier {identifier}")
            
            # 创建新的会话
            with self.sessions_lock:
                if identifier in self.sessions:
                    logger.error(f"Session {identifier} already exists")
                    client_socket.close()
                    return
                    
                session = TshSession(identifier, self.tsh_path)
                if not session.start():
                    client_socket.close()
                    return
                    
                session.client_socket = client_socket
                self.sessions[identifier] = session
            
            # 启动IO处理线程
            io_thread = threading.Thread(
                target=self.handle_session_io,
                args=(session,)
            )
            io_thread.daemon = True
            io_thread.start()
            
        except Exception as e:
            logger.error(f"Error handling client {addr}: {e}")
            client_socket.close()

    def run(self):
        """运行代理服务器"""
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('0.0.0.0', self.proxy_port))
            server.listen(5)
            
            logger.info(f"Multi-session proxy server listening on port {self.proxy_port}")
            
            while self.running:
                try:
                    client_socket, addr = server.accept()
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, addr)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                except Exception as e:
                    logger.error(f"Error accepting connection: {e}")
                    
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.running = False
            with self.sessions_lock:
                for session in self.sessions.values():
                    session.cleanup()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Multi-Session TSH Proxy Server')
    parser.add_argument('--port', type=int, default=8082, help='Proxy listening port')
    parser.add_argument('--tsh-path', default='./tsh', help='Path to tsh executable')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    if args.debug:
        logger.setLevel(logging.DEBUG)
        
    proxy = MultiTshProxy(args.port, args.tsh_path)
    proxy.run()