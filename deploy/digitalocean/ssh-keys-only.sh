#!/usr/bin/env bash
# Turn OFF ssh password logins (keys only). For a droplet you created with a root PASSWORD: add your SSH key first, test it, then run this.
#
#   bash deploy/digitalocean/ssh-keys-only.sh          asks you to confirm
#   bash deploy/digitalocean/ssh-keys-only.sh --yes    does not ask
#
# Safety: it REFUSES to run when no valid SSH key is installed for root, it asks sshd itself whether the new setting took effect (and undoes it if
# not), and sessions that are already open stay open. See docs/DIGITALOCEAN.md ("I created the droplet with a password").
set -euo pipefail

AK=/root/.ssh/authorized_keys
DROPIN=/etc/ssh/sshd_config.d/00-ojaloom.conf   # "00-" so it is read BEFORE cloud-init's 50-cloud-init.conf (sshd uses the first value it finds)

die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }

[ "$(id -u)" -eq 0 ] || die "run as root:  sudo bash $0"
command -v sshd >/dev/null 2>&1 || die "sshd is not installed on this machine"
grep -Eq '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config \
  || die "/etc/ssh/sshd_config has no 'Include /etc/ssh/sshd_config.d/*.conf' line, so this script cannot do the change safely. Edit /etc/ssh/sshd_config by hand."

# 1. there must be a real, parseable key (otherwise turning passwords off would lock you out)
if [ ! -s "$AK" ] || [ "$(ssh-keygen -l -f "$AK" 2>/dev/null | wc -l)" -lt 1 ]; then
  cat >&2 <<EOF
ERROR: no valid SSH key found in $AK, so passwords were NOT turned off (you would be locked out).

Add your key first. On YOUR computer:   ssh-keygen -t ed25519      (press Enter at each question; this makes ~/.ssh/id_ed25519.pub)
Then log in to the droplet with your password, and here run:   nano $AK
and paste the single line from your id_ed25519.pub file, save with Ctrl+O, Enter, Ctrl+X. Then run this script again.
EOF
  exit 1
fi
# sshd silently ignores keys when these folders are too open, which would also lock you out
chmod 700 /root/.ssh
chmod 600 "$AK"
echo "Found $(ssh-keygen -l -f "$AK" | wc -l) SSH key(s) for root:"
ssh-keygen -l -f "$AK" | sed 's/^/  /'

# 2. make the person confirm the key really works
if [ "${1:-}" != "--yes" ]; then
  [ -t 0 ] || die "no terminal to ask you on. Run it again with --yes if you are sure"
  cat <<'EOF'

BEFORE you continue: open a SECOND terminal window on your computer and run   ssh root@YOUR_DROPLET_IP
It must log you in WITHOUT asking for the droplet's password (it may ask for your key's passphrase, if you set one).
Keep this window open until that works.
EOF
  read -r -p "Did the key login work in the second window? Type YES to turn passwords off: " answer
  [ "$answer" = "YES" ] || die "stopped. Nothing was changed"
fi

# 3. apply, and check with sshd itself
install -d -m 0755 /etc/ssh/sshd_config.d
cat > "$DROPIN" <<'EOF'
# Written by deploy/digitalocean/ssh-keys-only.sh. Remove this file and run "systemctl reload ssh" to allow password logins again.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
chmod 0644 "$DROPIN"

undo() { rm -f "$DROPIN"; }
sshd -t || { undo; die "sshd rejected the configuration. Change undone"; }
effective="$(sshd -T 2>/dev/null | grep -E '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin) ' | sort | tr '\n' ' ')"
case "$effective" in
  *"kbdinteractiveauthentication no"*"passwordauthentication no"*"permitrootlogin without-password"*) : ;;
  *"kbdinteractiveauthentication no"*"passwordauthentication no"*"permitrootlogin prohibit-password"*) : ;;
  *) undo; die "sshd did not apply the setting (it reports: $effective). Change undone. Another file in /etc/ssh/sshd_config.d/ may override it" ;;
esac

systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || { undo; die "could not reload the ssh service. Change undone"; }

echo
echo "Done: ssh now accepts keys only. Password logins are off ($effective)."
echo "Test from your computer in a new window:  ssh root@YOUR_DROPLET_IP   (it must still log you in)."
echo "To undo:  rm $DROPIN && systemctl reload ssh      (use the DigitalOcean web Console if you are ever locked out)"
