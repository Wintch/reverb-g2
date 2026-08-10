#!/bin/bash
set -u
LOG=/tmp/check-accountsservice.log
exec > >(tee "$LOG") 2>&1
echo "=== /var/lib/AccountsService/users/iam ==="
cat /var/lib/AccountsService/users/iam 2>&1
