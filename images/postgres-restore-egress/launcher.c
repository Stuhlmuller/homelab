#define _GNU_SOURCE
#include <errno.h>
#include <limits.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/io_uring.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#if defined(__x86_64__) && !defined(__ILP32__)
#define NATIVE_ARCH AUDIT_ARCH_X86_64
#elif defined(__aarch64__)
#define NATIVE_ARCH AUDIT_ARCH_AARCH64
#else
#error Only native 64-bit x86 and ARM Linux ABIs are supported
#endif

#define DENY(n) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_##n, 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM)

static void fail(const char *message)
{
    fprintf(stderr, "restore-no-network: %s\n", message);
    exit(EXIT_FAILURE);
}

static void install_filter(void)
{
    struct sock_filter instructions[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, NATIVE_ARCH, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
#if defined(__x86_64__)
        /* x32 shares AUDIT_ARCH_X86_64 but has different syscall numbers. */
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, 0x40000000U, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
#endif
        /* io_uring can create/connect sockets without a socket syscall. */
        DENY(io_uring_setup), DENY(io_uring_enter), DENY(io_uring_register),
        DENY(ptrace), DENY(process_vm_readv), DENY(process_vm_writev),
        DENY(pidfd_getfd), DENY(bpf), DENY(setns), DENY(unshare),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_socket, 1, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_socketpair, 0, 3),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AF_UNIX, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {
        .len = (unsigned short)(sizeof instructions / sizeof instructions[0]),
        .filter = instructions,
    };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) ||
        syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, 0, &program))
        fail("cannot install filter; refusing command");
}

static void verify_filter(void)
{
    const int families[] = {AF_INET, AF_INET6, AF_PACKET, AF_NETLINK, AF_VSOCK};
    for (size_t i = 0; i < sizeof families / sizeof families[0]; i++) {
        const int types[] = {SOCK_STREAM, SOCK_DGRAM};
        for (size_t j = 0; j < sizeof types / sizeof types[0]; j++) {
            errno = 0;
            if (socket(families[i], types[j], 0) != -1 || errno != EPERM)
                fail("forbidden socket self-test failed");
            int descriptors[2];
            errno = 0;
            if (socketpair(families[i], types[j], 0, descriptors) != -1 || errno != EPERM)
                fail("forbidden socketpair self-test failed");
        }
    }
    struct io_uring_params parameters = {0};
    errno = 0;
    if (syscall(SYS_io_uring_setup, 1, &parameters) != -1 || errno != EPERM)
        fail("io_uring self-test failed");
    int pair[2];
    char received = 0;
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, pair))
        fail("Unix socket self-test failed");
    if (write(pair[0], "x", 1) != 1 || read(pair[1], &received, 1) != 1 || received != 'x')
        fail("Unix communication self-test failed");
    close(pair[0]);
    close(pair[1]);
    if (prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1)
        fail("no_new_privs verification failed");
}

int main(int argc, char **argv)
{
    if (argc < 2 || argv[1][0] != '/')
        fail("an absolute command is required");
    /* Runtime stdio must be pipes/files, never preconnected network sockets. */
    for (int fd = 0; fd <= 2; fd++) {
        struct stat status;
        if (fstat(fd, &status) == 0) {
            if (S_ISSOCK(status.st_mode))
                fail("socket-backed standard descriptor rejected");
        } else if (errno != EBADF) {
            fail("cannot inspect standard descriptors");
        }
    }
    /* No inherited internet socket or io_uring descriptor may survive exec. */
    if (syscall(SYS_close_range, 3U, UINT_MAX, 0))
        fail("cannot close inherited descriptors");
    install_filter();
    verify_filter();
    execv(argv[1], argv + 1);
    fail("cannot execute command");
}
