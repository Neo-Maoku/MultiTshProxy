# MultiTshProxy
![Language](https://img.shields.io/badge/language-c-blue.svg) ![Language](https://img.shields.io/badge/language-python-blue.svg) [![GitHub Stars](https://img.shields.io/github/stars/Neo-Maoku/MultiTshProxy.svg)](https://github.com/Neo-Maoku/MultiTshProxy/stargazers)

Linux Shell，Tsh多终端代理通信

### 项目演示
https://github.com/user-attachments/assets/f63cff76-f988-44bb-bd62-d53d914f2efc

### 项目编译

- 在tsh.h文件中修改服务端配置信息
- docker-compose up --build

### 项目部署

- 运行proxy_server.py启动tsh代理服务端，默认监听端口8082

### Shell连接

- 被控端执行tshd-tcp：/tshd-tcp 1234123412341234（16位的身份验证）
- 启动tsh代理客户端（代理控制端）：python3 proxy_client.py 服务端ip --port 服务端端口 --identifier 1234123412341234（16位的身份验证）

### 项目特点

- 代理控制端python脚本支持windows，linux，mac系统
- 支持同时多个tsh连接
- 修复了tsh项目中客户端窗口大小变动后被控端无法响应缺陷
- 操作方便，只需要在服务器部署代理服务端，就能在本机代理操作tsh客户端输入输出

### 微信公众号文章地址

https://mp.weixin.qq.com/s/tgaETUl_84wTfRSZmomoHQ
