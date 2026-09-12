#!/bin/sh
# Synthetic fixtures only; Kubernetes command must explicitly enter the launcher.
set -eu
umask 077
# Prove the candidate's kubelet message channel is inaccessible to this UID.
test ! -x /root
test ! -w /root/restore-termination-log
if (printf '%s\n' 'SYNTHETIC_TERMINATION_CANARY' > /root/restore-termination-log) 2>/dev/null; then
  exit 1
fi
awk '$5 == "/" {root++; if ($6 !~ /(^|,)ro(,|$)/) exit 1} END {if (root != 1) exit 1}' /proc/self/mountinfo
awk '
  /^Uid:/ {if ($2 != 65534 || $3 != 65534 || $4 != 65534 || $5 != 65534) exit 1; uid=1}
  /^Gid:/ {if ($2 != 65534 || $3 != 65534 || $4 != 65534 || $5 != 65534) exit 1; gid=1}
  /^CapInh:|^CapPrm:|^CapEff:|^CapBnd:|^CapAmb:/ {if ($2 !~ /^0+$/) exit 1; caps++}
  /^NoNewPrivs:/ {if ($2 != 1) exit 1; nnp=1}
  /^Seccomp:/ {if ($2 != 2) exit 1; seccomp=1}
  /^Seccomp_filters:/ {if ($2 < 2) exit 1; filters=$2}
  END {if (!(uid && gid && caps == 5 && nnp && seccomp && filters >= 2)) exit 1;
    printf "RESTORE_PROFILE {\"uid\":65534,\"gid\":65534,\"capabilities\":0,\"no_new_privs\":1,\"seccomp\":2,\"filters\":%d}\n", filters}
' /proc/1/status
for mode in denied inherit relax alternate-abi; do
  /tests/probe "$mode"
done
for mode in seccomp socketpair; do
  if /tests/fault "$mode" >"/work/fault-$mode.out" 2>"/work/fault-$mode.err"; then
    exit 1
  else
    test "$?" = 1
  fi
  test ! -s "/work/fault-$mode.out"
  case "$mode" in
    seccomp) message='restore-no-network: cannot install filter; refusing command' ;;
    socketpair) message='restore-no-network: Unix socket self-test failed' ;;
  esac
  test "$(cat "/work/fault-$mode.err")" = "$message"
done
/bin/sh /tests/postgres.sh
printf '%s\n' 'RESTORE_TALOS_SYNTHETIC_PASSED'
