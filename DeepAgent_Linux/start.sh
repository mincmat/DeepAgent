#!/usr/bin/env bash
set -e

DEPENDENCIES_MET=true

if ! command -v python3 &>/dev/null; then
  DEPENDENCIES_MET=false
  echo "[DeepAgent] python3 not installed. Installing..."
  if command -v apt &>/dev/null; then
    sudo apt update && sudo apt install -y python3
  elif command -v dnf &>/dev/null; then
    sudo dnf install -y python3
  elif command -v yum &>/dev/null; then
    sudo yum install -y python3
  elif command -v pacman &>/dev/null; then
    sudo pacman -Sy --noconfirm python
  elif command -v zypper &>/dev/null; then
    sudo zypper install -y python3
  elif command -v apk &>/dev/null; then
    sudo apk add python3
  elif command -v emerge &>/dev/null; then
    sudo emerge dev-lang/python
  else
    echo "[DeepAgent] Could not detect package manager. Install python3 manually and run again."
    exit 1
  fi
fi

chmod +x "$(dirname "$0")/bridge_server.py"
exec python3 "$(dirname "$0")/bridge_server.py"
