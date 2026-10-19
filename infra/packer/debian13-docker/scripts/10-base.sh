#!/usr/bin/env bash
# Paquets de base et mises à jour
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get -y full-upgrade
apt-get -y install \
  qemu-guest-agent \
  ca-certificates curl gnupg \
  chrony \
  unattended-upgrades apt-listchanges \
  jq vim htop

systemctl enable --now qemu-guest-agent
systemctl enable chrony

# Mises à jour de sécurité automatiques
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
