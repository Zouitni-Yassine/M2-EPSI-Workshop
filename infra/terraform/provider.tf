provider "proxmox" {
  endpoint = "https://10.0.1.100:8006/"
  insecure = true # certificat auto-signé

  ssh {
    agent       = false
    username    = "root"
    private_key = file("/root/.ssh/id_ed25519_proxmox")

    node {
      name    = "ceph01"
      address = "10.0.1.100"
    }
    node {
      name    = "ceph02"
      address = "10.0.1.101"
    }
    node {
      name    = "ceph03"
      address = "10.0.1.102"
    }
  }
}
