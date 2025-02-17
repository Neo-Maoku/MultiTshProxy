FROM alpine:3.18

# 使用阿里云镜像源
RUN sed -i 's/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g' /etc/apk/repositories

# 安装基础工具和依赖
RUN apk add --no-cache \
    build-base \
    musl-dev \
    linux-headers \
    openssl-dev \
    openssl-libs-static \
    zlib-dev \
    zlib-static \
    make \
    cmake \
    gcc \
    libtool \
    autoconf \
    automake \
    git \
    pkgconfig \
    libcap-dev \
    libcap-static \
    libuv-dev \
    libuv-static

# 创建工作目录
WORKDIR /build

# 复制本地的 util-linux 源码包到容器
COPY util-linux-2.38.tar.gz /tmp/

# 编译安装 util-linux 静态库
RUN cd /tmp && \
    tar xzf util-linux-2.38.tar.gz && \
    cd util-linux-2.38 && \
    ./configure --enable-static --disable-shared && \
    make && \
    make install && \
    cd / && \
    rm -rf /tmp/util-linux*

# 编译安装 libwebsockets 静态库
RUN cd /tmp && \
    git clone https://github.com/warmcat/libwebsockets.git && \
    cd libwebsockets && \
    git checkout v4.3.2 && \
    mkdir build && \
    cd build && \
    cmake -DLWS_WITH_SSL=ON \
          -DLWS_STATIC_PIC=ON \
          -DLWS_WITH_SHARED=OFF \
          -DLWS_WITH_STATIC=ON \
          -DLWS_WITHOUT_TESTAPPS=ON \
          -DLWS_WITHOUT_TEST_SERVER=ON \
          -DLWS_WITHOUT_TEST_PING=ON \
          -DLWS_WITHOUT_TEST_CLIENT=ON \
          .. && \
    make && \
    make install && \
    cd / && \
    rm -rf /tmp/libwebsockets*

WORKDIR /build

CMD ["/bin/sh"]