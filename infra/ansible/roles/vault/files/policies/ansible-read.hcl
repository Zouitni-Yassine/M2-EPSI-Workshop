# Ansible (AppRole "ansible", depuis le poste de contrôle) : lecture seule des secrets d'infra.
# Pas d'accès à secret/breakglass/* (comptes de secours des humains).
path "secret/data/infra/*" {
  capabilities = ["read"]
}

path "secret/metadata/infra/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/infra" {
  capabilities = ["list"]
}
