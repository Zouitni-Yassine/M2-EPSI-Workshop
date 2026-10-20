#!/usr/bin/env bash
# Attend la fin du premier boot cloud-init (apt, growpart, clés SSH...)
cloud-init status --wait || true
