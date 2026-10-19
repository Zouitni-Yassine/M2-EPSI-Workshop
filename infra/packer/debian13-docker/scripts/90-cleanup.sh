#!/usr/bin/env bash
# Généralisation du template : chaque clone doit avoir son identité propre
export DEBIAN_FRONTEND=noninteractive

apt-get -y autoremove --purge
apt-get clean
rm -rf /var/lib/apt/lists/*

# Docker : pas d'engine-id, d'image ni de réseau partagés entre clones
systemctl stop docker.socket docker containerd
rm -rf /var/lib/docker/* /var/lib/containerd/*

# cloud-init se relancera au premier boot du clone (hostname, IP, clés)
cloud-init clean --logs --machine-id
rm -f /etc/ssh/ssh_host_*
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id

# Journaux et historiques
journalctl --rotate
journalctl --vacuum-time=1s
find /var/log -type f -name '*.gz' -delete
find /var/log -type f -exec truncate -s 0 {} \;
rm -f /root/.bash_history /home/*/.bash_history

fstrim -av || true
sync
