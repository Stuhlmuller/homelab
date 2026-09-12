#define _GNU_SOURCE
#include <errno.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

/* Synthetic-only child: add a restriction beneath the already active launcher.
 * The next, unchanged launcher must fail before reaching its command sentinel. */
int main(int argc, char **argv)
{
    if (argc != 2 || geteuid() != 65534 || getegid() != 65534 ||
        prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1 ||
        prctl(PR_GET_SECCOMP, 0, 0, 0, 0) != SECCOMP_MODE_FILTER)
        return 2;
    int call;
    if (strcmp(argv[1], "seccomp") == 0)
        call = SYS_seccomp;
    else if (strcmp(argv[1], "socketpair") == 0)
        call = SYS_socketpair;
    else
        return 2;
    struct sock_filter instructions[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (unsigned int)call, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {.len = sizeof instructions / sizeof instructions[0], .filter = instructions};
    if (syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, 0, &program)) {
        fputs("fault-injector: injection failed\n", stderr);
        return 2;
    }
    char *command[] = {"/usr/local/bin/restore-no-network", "/bin/echo", "UNSAFE_COMMAND_EXECUTED", NULL};
    execv(command[0], command);
    fputs("fault-injector: exec failed\n", stderr);
    return 2;
}
