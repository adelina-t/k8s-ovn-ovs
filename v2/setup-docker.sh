#!/bin/bash

set -o errexit
set -o pipefail

DOCKER_VERSION="${1}"
DOCKER_APT_KEY="https://download.docker.com/linux/ubuntu/gpg"
DOCKER_APT_REPO="https://download.docker.com/linux/ubuntu"

# Install Docker
curl -fsSL "${DOCKER_APT_KEY}" | sudo apt-key add -
sudo add-apt-repository "deb [arch=amd64] ${DOCKER_APT_REPO} $(lsb_release -cs) stable"
sudo apt update
sudo apt install -y docker-ce="${DOCKER_VERSION}" docker-ce-cli="${DOCKER_VERSION}" containerd.io

exit 0
