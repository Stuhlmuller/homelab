#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/capability.h>
#include <linux/filter.h>
#include <linux/io_uring.h>
#include <linux/seccomp.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/eventfd.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/time.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <unistd.h>

static void require(int ok, const char *message)
{
    if (!ok) {
        fprintf(stderr, "network probe: %s\n", message);
        exit(1);
    }
}

static void denied(void)
{
    const int families[] = {AF_INET, AF_INET6, AF_PACKET, AF_NETLINK, AF_VSOCK};
    const int types[] = {SOCK_STREAM, SOCK_DGRAM};
    for (size_t i = 0; i < sizeof families / sizeof families[0]; i++) {
        for (size_t j = 0; j < sizeof types / sizeof types[0]; j++) {
            errno = 0;
            require(socket(families[i], types[j], 0) == -1 && errno == EPERM,
                    "non-Unix socket did not fail with EPERM");
            int pair[2];
            errno = 0;
            require(socketpair(families[i], types[j], 0, pair) == -1 && errno == EPERM,
                    "non-Unix socketpair did not fail with EPERM");
        }
    }
    struct io_uring_params parameters = {0};
    errno = 0;
    require(syscall(SYS_io_uring_setup, 1, &parameters) == -1 && errno == EPERM,
            "io_uring setup not denied");
    errno = 0;
    require(syscall(SYS_io_uring_enter, -1, 0, 0, 0, NULL, 0) == -1 && errno == EPERM,
            "io_uring enter not denied");
    errno = 0;
    require(syscall(SYS_io_uring_register, -1, 0, NULL, 0) == -1 && errno == EPERM,
            "io_uring register not denied");
    errno = 0;
    require(syscall(SYS_recvmsg, -1, NULL, 0) == -1 && errno == EPERM,
            "recvmsg not denied");
    errno = 0;
    require(syscall(SYS_recvmmsg, -1, NULL, 0, 0, NULL) == -1 && errno == EPERM,
            "recvmmsg not denied");
    require(prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) == 1, "no_new_privs not inherited");
    int pair[2];
    char received = 0;
    require(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0, "Unix socketpair rejected");
    require(write(pair[0], "x", 1) == 1 && read(pair[1], &received, 1) == 1 && received == 'x',
            "Unix socket communication failed");
    close(pair[0]);
    close(pair[1]);
}

static void wait_success(pid_t child)
{
    int status = 0;
    require(child > 0 && waitpid(child, &status, 0) == child && WIFEXITED(status) &&
            WEXITSTATUS(status) == 0, "child did not succeed");
}

static int descriptor_count(void)
{
    DIR *directory = opendir("/proc/self/fd");
    require(directory != NULL, "cannot inspect received descriptors");
    int count = 0;
    struct dirent *entry;
    while ((entry = readdir(directory))) {
        char *end;
        long fd = strtol(entry->d_name, &end, 10);
        if (end != entry->d_name && *end == '\0' && fd != dirfd(directory))
            count++;
    }
    require(closedir(directory) == 0, "descriptor inspection close failed");
    return count;
}

static void receive_rights(const char *method, const char *expected,
                          const char *state, const char *port)
{
    int channel = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un address = {.sun_family = AF_UNIX, .sun_path = "/tests/broker.sock"};
    require(channel >= 0 && connect(channel, (struct sockaddr *)&address, sizeof address) == 0,
            "Unix broker connection failed");
    /* This connection and readiness byte occur after launcher startup/exec. */
    require(write(channel, "R", 1) == 1, "broker readiness failed");
    struct pollfd pending = {.fd = channel, .events = POLLIN};
    require(poll(&pending, 1, 5000) == 1 && (pending.revents & POLLIN),
            "broker did not deliver a rights message");
    int before = descriptor_count();
    char data = 0;
    struct iovec bytes = {.iov_base = &data, .iov_len = 1};
    union {
        struct cmsghdr alignment;
        char bytes[CMSG_SPACE(sizeof(int))];
    } control = {0};
    struct msghdr message = {.msg_iov = &bytes, .msg_iovlen = 1,
                            .msg_control = control.bytes, .msg_controllen = sizeof control.bytes};
    ssize_t result;
    errno = 0;
    if (strcmp(method, "recvmsg") == 0) {
        result = recvmsg(channel, &message, MSG_CMSG_CLOEXEC);
    } else if (strcmp(method, "recvmmsg") == 0) {
        struct mmsghdr batch = {.msg_hdr = message};
        int received = recvmmsg(channel, &batch, 1, MSG_CMSG_CLOEXEC, NULL);
        result = received == 1 ? (ssize_t)batch.msg_len : received;
        message = batch.msg_hdr;
    } else if (strcmp(method, "read") == 0) {
        result = read(channel, &data, 1);
    } else {
        require(strcmp(method, "recvfrom") == 0, "unknown broker receive method");
        result = recvfrom(channel, &data, 1, 0, NULL, NULL);
    }
    if (strcmp(expected, "deny") == 0) {
        require(result == -1 && errno == EPERM, "ancillary receive was not denied");
        require(descriptor_count() == before, "denied call imported a descriptor");
    } else if (strcmp(expected, "discard") == 0) {
        require(result == 1 && data == 'x', "ordinary Unix payload receive failed");
        require(descriptor_count() == before, "ordinary receive imported a descriptor");
    } else {
        require(strcmp(expected, "allow") == 0 && result == 1 && data == 'x',
                "positive ancillary receive failed");
        struct cmsghdr *rights = CMSG_FIRSTHDR(&message);
        require(rights && rights->cmsg_level == SOL_SOCKET && rights->cmsg_type == SCM_RIGHTS &&
                rights->cmsg_len == CMSG_LEN(sizeof(int)) && !(message.msg_flags & MSG_CTRUNC),
                "positive broker did not pass exactly one descriptor");
        int imported;
        memcpy(&imported, CMSG_DATA(rights), sizeof imported);
        require(descriptor_count() == before + 1, "positive descriptor was not installed");
        int family = 0;
        socklen_t length = sizeof family;
        require(getsockopt(imported, SOL_SOCKET, SO_DOMAIN, &family, &length) == 0 && family == AF_INET,
                "positive broker did not pass an INET socket");
        struct sockaddr_in endpoint = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
        length = sizeof endpoint;
        errno = 0;
        int connected = getpeername(imported, (struct sockaddr *)&endpoint, &length);
        if (strcmp(state, "unconnected") == 0) {
            require(connected == -1 && errno == ENOTCONN, "donor socket was already connected");
            endpoint.sin_family = AF_INET;
            endpoint.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            endpoint.sin_port = htons((unsigned short)atoi(port));
            require(connect(imported, (struct sockaddr *)&endpoint, sizeof endpoint) == 0,
                    "imported socket could not connect");
        } else {
            require(strcmp(state, "connected") == 0 && connected == 0,
                    "donor socket was not preconnected");
        }
        require(write(imported, "n", 1) == 1, "imported socket could not send data");
        close(imported);
    }
    close(channel);
}

int main(int argc, char **argv)
{
    require(argc >= 2, "mode required");
    require(geteuid() == 65534 && getegid() == 65534, "non-root identity changed");
    require(prctl(PR_GET_SECCOMP, 0, 0, 0, 0) == SECCOMP_MODE_FILTER,
            "container RuntimeDefault seccomp is missing");
    require(prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) == 1,
            "container no_new_privs is missing");
    struct __user_cap_header_struct header = {.version = _LINUX_CAPABILITY_VERSION_3};
    struct __user_cap_data_struct capabilities[2] = {{0}};
    require(syscall(SYS_capget, &header, capabilities) == 0, "capability inspection failed");
    for (int i = 0; i < 2; i++)
        require(capabilities[i].effective == 0 && capabilities[i].permitted == 0 &&
                capabilities[i].inheritable == 0, "capabilities were not dropped");
    if (strcmp(argv[1], "rights-receiver") == 0) {
        require(argc == 6, "broker receive method, expectation, state and port required");
        receive_rights(argv[2], argv[3], argv[4], argv[5]);
    } else if (strcmp(argv[1], "denied") == 0) {
        denied();
    } else if (strcmp(argv[1], "inherit") == 0) {
        denied();
        pid_t child = fork();
        require(child != -1, "fork failed");
        if (child == 0) {
            execl(argv[0], argv[0], "denied", NULL);
            _exit(2);
        }
        wait_success(child);
    } else if (strcmp(argv[1], "relax") == 0) {
        struct sock_filter allow[] = {BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)};
        struct sock_fprog program = {.len = 1, .filter = allow};
        require(syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, 0, &program) == 0,
                "permissive additional filter installation failed");
        denied();
    } else if (strcmp(argv[1], "alternate-abi") == 0) {
#if defined(__x86_64__)
        for (int abi = 0; abi < 2; abi++) {
            pid_t child = fork();
            require(child != -1, "fork failed");
            if (child == 0) {
                if (abi == 0)
                    syscall(SYS_socket | 0x40000000U, AF_INET, SOCK_STREAM, 0);
                else
                    __asm__ volatile("int $0x80" : : "a"(102), "b"(1), "c"(0) : "memory");
                _exit(2);
            }
            int status = 0;
            require(waitpid(child, &status, 0) == child && WIFSIGNALED(status) &&
                    WTERMSIG(status) == SIGSYS, "alternate ABI did not terminate process");
        }
#else
        /* ARM32 is a different audit architecture and cannot be executed here. */
        denied();
#endif
    } else if (strcmp(argv[1], "inherited-fd") == 0) {
        require(argc == 3, "launcher path required");
        int fd = socket(AF_INET, SOCK_STREAM, 0);
        require(fd >= 0 && dup2(fd, 9) == 9, "unfiltered socket setup failed");
        execl(argv[2], argv[2], argv[0], "closed-fd", NULL);
        require(0, "launcher exec failed");
    } else if (strcmp(argv[1], "closed-fd") == 0) {
        errno = 0;
        require(fcntl(9, F_GETFD) == -1 && errno == EBADF, "inherited descriptor survived");
        denied();
    } else if (strcmp(argv[1], "socket-stdio") == 0 || strcmp(argv[1], "anonymous-stdio") == 0) {
        require(argc == 3, "launcher path required");
        int pair[2];
        if (strcmp(argv[1], "socket-stdio") == 0) {
            require(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0, "socketpair setup failed");
        } else {
            /* eventfd exercises anonymous-inode rejection without depending on
             * RuntimeDefault permitting unfiltered io_uring creation. */
            pair[0] = eventfd(0, EFD_CLOEXEC);
            require(pair[0] >= 0, "anonymous descriptor setup failed");
        }
        pid_t child = fork();
        require(child != -1, "fork failed");
        if (child == 0) {
            require(dup2(pair[0], 0) == 0, "stdio setup failed");
            execl(argv[2], argv[2], "/bin/true", NULL);
            _exit(2);
        }
        int status = 0;
        require(waitpid(child, &status, 0) == child && WIFEXITED(status) &&
                WEXITSTATUS(status) == 1, "unsupported stdio was not rejected");
    } else if (strcmp(argv[1], "positive") == 0) {
        require(argc == 5, "numeric gateway and TCP/UDP ports required");
        for (int i = 0; i < 2; i++) {
            int fd = socket(AF_INET, i == 0 ? SOCK_STREAM : SOCK_DGRAM, 0);
            require(fd >= 0, "positive IPv4 socket failed");
            struct sockaddr_in address = {.sin_family = AF_INET};
            address.sin_port = htons((unsigned short)atoi(argv[3 + i]));
            require(inet_pton(AF_INET, argv[2], &address.sin_addr) == 1, "invalid gateway");
            require(connect(fd, (struct sockaddr *)&address, sizeof address) == 0,
                    "positive fixture connection failed");
            struct timeval timeout = {.tv_sec = 5};
            require(setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof timeout) == 0,
                    "timeout setup failed");
            char received = 0;
            require(write(fd, "x", 1) == 1 && read(fd, &received, 1) == 1 && received == 'x',
                    "positive fixture did not echo");
            close(fd);
            fd = socket(AF_INET6, i == 0 ? SOCK_STREAM : SOCK_DGRAM, 0);
            require(fd >= 0, "positive IPv6 socket failed");
            close(fd);
        }
    } else {
        require(0, "unknown mode");
    }
    return 0;
}
