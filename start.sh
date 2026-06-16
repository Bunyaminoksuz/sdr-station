#!/bin/bash
# =============================================================================
# METEOR Station — Quick Start Script (Pi 3B+ Optimized)
#
# Manuel başlatma için: ./start.sh
# Kapatmak için: Ctrl+C
#
# Systemd servisleri kuruluysa bunun yerine:
#   sudo systemctl start meteor-scheduler meteor-web
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/venv"
LOG_FILE="${SCRIPT_DIR}/logs/meteor_station.log"

# Colors
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${CYAN}🛰️  METEOR Autonomous Station — Başlatılıyor${NC}"
echo ""

# =============================================================================
# Pre-flight Checks
# =============================================================================

# Check Python venv
if [ ! -d "${VENV_DIR}" ]; then
    echo -e "${YELLOW}[!] Python venv bulunamadı, oluşturuluyor...${NC}"
    python3 -m venv "${VENV_DIR}"
    "${VENV_DIR}/bin/pip" install --upgrade pip
    "${VENV_DIR}/bin/pip" install -r "${SCRIPT_DIR}/requirements.txt"
    echo -e "${GREEN}[✓] Python venv hazır${NC}"
fi

PYTHON="${VENV_DIR}/bin/python"
UVICORN="${VENV_DIR}/bin/uvicorn"

# Check satdump
if ! command -v satdump &>/dev/null; then
    echo -e "${RED}[✗] satdump bulunamadı! Lütfen önce satdump kurun.${NC}"
    echo "    sudo apt install satdump"
    echo "    veya: https://github.com/SatDump/SatDump"
    exit 1
fi
echo -e "${GREEN}[✓] satdump: $(which satdump)${NC}"

# Check RTL-SDR
if command -v rtl_test &>/dev/null; then
    if rtl_test -t 2>&1 | head -5 | grep -q "Found 1 device"; then
        echo -e "${GREEN}[✓] RTL-SDR cihazı algılandı${NC}"
    else
        echo -e "${YELLOW}[!] RTL-SDR cihazı algılanamadı (takılı değilse sorun yok)${NC}"
    fi
else
    echo -e "${YELLOW}[!] rtl_test bulunamadı (rtl-sdr paketi kurulu mu?)${NC}"
fi

# Swap check
SWAP_TOTAL=$(free -m | awk '/^Swap:/ {print $2}')
if [ "${SWAP_TOTAL}" -lt 100 ]; then
    echo -e "${YELLOW}[!] Swap alanı az (${SWAP_TOTAL}MB). 256MB swap önerilir:${NC}"
    echo "    sudo fallocate -l 256M /swapfile"
    echo "    sudo chmod 600 /swapfile"
    echo "    sudo mkswap /swapfile"
    echo "    sudo swapon /swapfile"
    echo "    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab"
fi

# RAM check
MEM_AVAIL=$(free -m | awk '/^Mem:/ {print $7}')
MEM_TOTAL=$(free -m | awk '/^Mem:/ {print $2}')
echo -e "${GREEN}[✓] RAM: ${MEM_AVAIL}MB boş / ${MEM_TOTAL}MB toplam${NC}"

if [ "${MEM_AVAIL}" -lt 300 ]; then
    echo -e "${RED}[!] Uyarı: Düşük RAM (${MEM_AVAIL}MB boş). OOM riski var!${NC}"
fi

# NTP Time Sync
echo -e "${CYAN}[*] Saat senkronizasyonu kontrol ediliyor...${NC}"
sudo timedatectl set-ntp true 2>/dev/null || true
sudo systemctl restart systemd-timesyncd 2>/dev/null || true
# chrony varsa onu da dene
sudo systemctl restart chrony 2>/dev/null || true

SYNC_OK=0
for i in $(seq 1 30); do
    if timedatectl status 2>/dev/null | grep -qi "synchronized: yes"; then
        SYNC_OK=1
        break
    fi
    sleep 1
done

if [ "$SYNC_OK" -eq 1 ]; then
    echo -e "${GREEN}[✓] Saat senkronize edildi ($(date '+%H:%M:%S %Z'))${NC}"
else
    echo -e "${YELLOW}[!] Saat senkronizasyonu tamamlanamadı — internet bağlantısını kontrol edin${NC}"
    echo -e "${YELLOW}    Mevcut saat: $(date)${NC}"
fi

# Create dirs
mkdir -p "${SCRIPT_DIR}"/{passes,tle,logs,run}

echo ""
echo -e "${CYAN}RAM Bütçesi (tahmini):${NC}"
echo "  OS + sistem:    ~100 MB"
echo "  Scheduler:      ~60 MB"
echo "  Web panel:      ~50 MB"
echo "  satdump (2 th): ~250 MB (kayıt sırasında)"
echo "  ─────────────────────"
echo "  Toplam:         ~460 MB / ${MEM_TOTAL} MB"
echo ""

# =============================================================================
# Start Services
# =============================================================================

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}Servisler durduruluyor...${NC}"
    kill $WEB_PID 2>/dev/null || true
    kill $SCHED_PID 2>/dev/null || true
    wait $WEB_PID 2>/dev/null || true
    wait $SCHED_PID 2>/dev/null || true
    echo -e "${GREEN}Servisler durduruldu.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start web panel (background)
echo -e "${CYAN}🌐 Web panel başlatılıyor (port 8080)...${NC}"
cd "${SCRIPT_DIR}"
"${UVICORN}" web.server:app \
    --host 0.0.0.0 \
    --port 8080 \
    --workers 1 \
    --limit-max-requests 1000 \
    --log-level warning \
    &
WEB_PID=$!
sleep 2

if kill -0 $WEB_PID 2>/dev/null; then
    IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
    echo -e "${GREEN}[✓] Web panel çalışıyor: http://${IP}:8080${NC}"
else
    echo -e "${RED}[✗] Web panel başlatılamadı!${NC}"
fi

# Start scheduler (foreground)
echo -e "${CYAN}📡 Zamanlayıcı başlatılıyor...${NC}"
echo ""

"${PYTHON}" "${SCRIPT_DIR}/scheduler.py" &
SCHED_PID=$!

echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✅ METEOR Station çalışıyor!            ║${NC}"
echo -e "${GREEN}║  🌐 http://${IP}:8080              ║${NC}"
echo -e "${GREEN}║  📋 Log: tail -f ${LOG_FILE}       ║${NC}"
echo -e "${GREEN}║  ⏹️  Kapatmak için: Ctrl+C               ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""

# Wait for either to exit
wait $SCHED_PID $WEB_PID
