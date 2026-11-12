#!/bin/bash
# NETsync terminal setup. Run once as root on each Linux server NETsync users should open terminals on.
#
# What it does:
#  * a "netsync" account whose key (held only by the NETsync SSH gateway) works only from __SOURCE__ and
#    can only run /usr/local/sbin/netsync-account, which manages the ns-* accounts of NETsync users
#  * groups netsync-users (every managed account), netsync-write (sudo for service/package commands) and
#    netsync-full (full sudo); sudo always asks for the user's own password
#  * ns-* accounts may log in with a password only from __SOURCE__, so they are reachable only through NETsync
# Undo: userdel -r netsync; rm /usr/local/sbin/netsync-account* /etc/sudoers.d/netsync /etc/ssh/sshd_config.d/50-netsync.conf
set -euo pipefail
SOURCE="__SOURCE__"
PUBKEY="__PUBKEY__"
[ "$(id -u)" = 0 ] || { echo "Run as root (sudo bash)"; exit 1; }

if ! command -v sudo >/dev/null; then
  echo "Installing sudo..."
  (apt-get update -qq && apt-get install -y -qq sudo) || dnf -y -q install sudo || yum -y -q install sudo || apk add -q sudo
fi

for g in netsync-users netsync-write netsync-full; do getent group "$g" >/dev/null || groupadd "$g"; done

if ! id netsync >/dev/null 2>&1; then
  useradd -r -m -d /var/lib/netsync -s /bin/sh -c "NETsync gateway" netsync
fi
passwd -l netsync >/dev/null 2>&1 || true
install -d -m 700 -o netsync -g netsync /var/lib/netsync/.ssh
printf 'restrict,from="%s",command="/usr/local/sbin/netsync-account-ssh" %s\n' "$SOURCE" "$PUBKEY" > /var/lib/netsync/.ssh/authorized_keys
chown netsync:netsync /var/lib/netsync/.ssh/authorized_keys
chmod 600 /var/lib/netsync/.ssh/authorized_keys

cat > /usr/local/sbin/netsync-account <<'NETSYNC_ACCOUNT'
__ACCOUNT_SCRIPT__
NETSYNC_ACCOUNT
chown root:root /usr/local/sbin/netsync-account
chmod 700 /usr/local/sbin/netsync-account

cat > /usr/local/sbin/netsync-account-ssh <<'NETSYNC_WRAPPER'
#!/bin/sh
# Forced command of the NETsync key: only "netsync-account <args>" is allowed.
set -f
set -- $SSH_ORIGINAL_COMMAND
[ "${1:-}" = "netsync-account" ] || { echo '{"ok":false,"error":"not allowed"}'; exit 1; }
shift
exec sudo -n /usr/local/sbin/netsync-account "$@"
NETSYNC_WRAPPER
chmod 755 /usr/local/sbin/netsync-account-ssh

SUDOERS=$(mktemp)
cat > "$SUDOERS" <<'NETSYNC_SUDOERS'
# Managed by NETsync
netsync ALL=(root) NOPASSWD: /usr/local/sbin/netsync-account
%netsync-full ALL=(ALL:ALL) ALL
Cmnd_Alias NETSYNC_WRITE = /usr/bin/systemctl, /bin/systemctl, /usr/sbin/service, /usr/bin/journalctl, /bin/journalctl, /usr/bin/apt, /usr/bin/apt-get, /usr/bin/dnf, /usr/bin/yum, /usr/sbin/reboot, /sbin/reboot
%netsync-write ALL=(root) NETSYNC_WRITE
NETSYNC_SUDOERS
visudo -cf "$SUDOERS" >/dev/null
install -m 440 -o root -g root "$SUDOERS" /etc/sudoers.d/netsync
rm -f "$SUDOERS"

MATCH="# Managed by NETsync: NETsync user accounts log in with a password, and only through NETsync
Match Group netsync-users Address $SOURCE
    PasswordAuthentication yes
    KbdInteractiveAuthentication yes
Match Group netsync-users Address *,!$SOURCE
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PubkeyAuthentication no
Match all"
if grep -Eq '^\s*Include\s+/etc/ssh/sshd_config.d/\*\.conf' /etc/ssh/sshd_config 2>/dev/null; then
  printf '%s\n' "$MATCH" > /etc/ssh/sshd_config.d/50-netsync.conf
else
  sed -i '/^# Managed by NETsync/,/^Match all$/d' /etc/ssh/sshd_config
  printf '\n%s\n' "$MATCH" >> /etc/ssh/sshd_config
fi
SSHD=$(command -v sshd || echo /usr/sbin/sshd)
"$SSHD" -t
systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || service ssh reload 2>/dev/null || kill -HUP "$(cat /var/run/sshd.pid)"

echo "NETsync terminal setup done on $(hostname). NETsync connects from $SOURCE."
