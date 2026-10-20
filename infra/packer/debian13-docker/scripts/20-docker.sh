#!/usr/bin/env bash
# Docker CE depuis le dépôt officiel Docker
export DEBIAN_FRONTEND=noninteractive

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

. /etc/os-release
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/debian
Suites: ${VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

apt-get update
apt-get -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Modules nécessaires à l'overlay Swarm
cat > /etc/modules-load.d/docker-swarm.conf <<'EOF'
overlay
br_netfilter
EOF

# - live-restore doit rester désactivé : incompatible avec le mode Swarm
# - rotation des logs pour ne pas saturer le disque
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "live-restore": false,
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "userland-proxy": false
}
EOF

systemctl enable docker containerd
systemctl restart docker

# Vérification
docker version
docker run --rm hello-world
