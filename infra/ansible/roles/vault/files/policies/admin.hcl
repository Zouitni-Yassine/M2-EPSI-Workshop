# Administrateurs de Vault : compte de secours "breakglass" (userpass) et, à terme, groupe
# Keycloak infra-admins (OIDC). Remplace le token root, qui est révoqué : chaque action est
# rattachée à une identité dans le journal d'audit.
path "*" {
  capabilities = ["create", "read", "update", "patch", "delete", "list", "sudo"]
}
