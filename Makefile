CLIENT_OBJ=pel.c aes.c sha1.c tsh.c
SERVER_OBJ=pel.c aes.c sha1.c tshd.c

# 编译选项
STATIC_FLAGS=-static
PIE_FLAGS=-fPIE -pie
HARDENING_FLAGS=-fstack-protector-strong -D_FORTIFY_SOURCE=2

# Debug/Release 配置
ifdef DEBUG
    COMMON_FLAGS=-O0 -g -W -Wall $(STATIC_FLAGS) $(PIE_FLAGS) $(HARDENING_FLAGS) -DDEBUG
else
    COMMON_FLAGS=-O2 -W -Wall $(STATIC_FLAGS) $(PIE_FLAGS) $(HARDENING_FLAGS)
endif

all:
	@echo
	@echo "Please specify one of these targets:"
	@echo
	@echo "	make linux           - build release version"
	@echo "	make linux DEBUG=1   - build debug version"
	@echo

clean:
	rm -f *.o tsh tshd

linux:
	gcc $(COMMON_FLAGS) -o tsh $(CLIENT_OBJ)
	gcc $(COMMON_FLAGS) -o tshd-tcp $(SERVER_OBJ) -lutil -DLINUX
ifndef DEBUG
	strip tsh tshd-tcp
endif

.PHONY: all clean linux