#!/bin/bash
# =============================================================================
# METEOR Station — Swap Setup (Pi 3B+ 1GB RAM)
# Run once: sudo ./setup_swap.sh
# =============================================================================

set -e

SWAP_FILE="/swapfile"
SWAP_SIZE="1G"    # 1GB — SatDump decode sırasında 400-500MB RAM kullanabilir

echo "🔧 Swap alanı oluşturuluyor (${SWAP_SIZE})..."

# Remove old swap if exists
if [ -f "${SWAP_FILE}" ]; then
    sudo swapoff "${SWAP_FILE}" 2>/dev/null || true
    sudo rm "${SWAP_FILE}"
fi

# Create swap
sudo fallocate -l ${SWAP_SIZE} ${SWAP_FILE}
sudo chmod 600 ${SWAP_FILE}
sudo mkswap ${SWAP_FILE}
sudo swapon ${SWAP_FILE}

# Persist across reboots
if ! grep -q "${SWAP_FILE}" /etc/fstab; then
    echo "${SWAP_FILE} none swap sw 0 0" | sudo tee -a /etc/fstab
fi

# Set swappiness low (only use swap as emergency)
sudo sysctl vm.swappiness=10
if ! grep -q "vm.swappiness" /etc/sysctl.conf; then
    echo "vm.swappiness=10" | sudo tee -a /etc/sysctl.conf
fi

echo ""
echo "✅ Swap aktif:"
free -h | head -3
echo ""
echo "Swappiness: $(cat /proc/sys/vm/swappiness) (düşük = daha az swap kullanılır)"
