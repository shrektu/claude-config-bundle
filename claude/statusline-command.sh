#!/usr/bin/env bash
# Claude Code status line, converted from ~/.bashrc PS1:
#   PS1='${debian_chroot:+($debian_chroot)}\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
# Renders as: <bold green>user@host<reset>:<bold blue>cwd<reset>

cat >/dev/null

user=$(whoami)
host=$(hostname -s)
cwd=$(pwd)

printf '\033[01;32m%s@%s\033[0m:\033[01;34m%s\033[0m' "$user" "$host" "$cwd"
