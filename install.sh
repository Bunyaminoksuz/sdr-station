#!/bin/bash
# =============================================================================
# METEOR Autonomous Station — Kurulum Scripti
# Raspberry Pi 3B+ Rev 1.3 | Pi OS 64-bit Lite | 1GB RAM
#
# Kullanım:
#   chmod +x install.sh
#   sudo ./install.sh
#
# NOT: satdump haricen kurulmuş kabul edilir (make -j1 ile).
#      Bu script satdump derlemesi YAPMAZ.
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Proje dizinini tespit et (script neredeyse orası)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Hedef dizin (Pi üzerinde nereye kurulacak)
# Eğer script zaten /home/pi altındaysa aynı yeri kullan
STATION_DIR="${SCRIPT_DIR}"
VENV_DIR="${STATION_DIR}/venv"

# Kullanıcı tespiti (sudo ile çalışıyorsa asıl kullanıcıyı bul)
if [ -n "${SUDO_USER}" ]; then
    USER_NAME="${SUDO_USER}"
else
    USER_NAME="$(whoami)"
fi
USER_HOME=$(eval echo "~${USER_NAME}")

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_ok()   { echo -e "${GREEN}[ OK ]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err()  { echo -e "${RED}[FAIL]${NC} $1"; }

# =============================================================================
# Root kontrolü
# =============================================================================
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_err "Root olarak çalıştır: sudo ./install.sh"
        exit 1
    fi
}

# =============================================================================
# 1. Sistem paketlerini kur
# =============================================================================
step_system_packages() {
    log_info "1/8 — Sistem paketleri kuruluyor..."

    apt-get update -y -qq
    apt-get install -y -qq \
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        librtlsdr-dev \
        rtl-sdr \
        libusb-1.0-0-dev \
        curl \
        jq \
        > /dev/null 2>&1

    log_ok "Sistem paketleri kuruldu"
}

# =============================================================================
# 2. DVB kernel modülü engelle (RTL-SDR erişimi için)
# =============================================================================
step_blacklist_dvb() {
    log_info "2/8 — DVB kernel modülü engelleniyor..."

    cat > /etc/modprobe.d/blacklist-rtlsdr.conf << 'EOF'
blacklist dvb_usb_rtl28xxu
blacklist dvb_usb_rtl2832u
blacklist rtl2832
blacklist rtl2832_sdr
blacklist dvb_usb_v2
blacklist dvb_core
EOF

    modprobe -r dvb_usb_rtl28xxu 2>/dev/null || true
    log_ok "DVB modülü engellendi"
}

# =============================================================================
# 3. RTL-SDR udev kuralları
# =============================================================================
step_udev_rules() {
    log_info "3/8 — RTL-SDR udev kuralları..."

    cat > /etc/udev/rules.d/20-rtlsdr.rules << 'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", GROUP="plugdev", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2832", GROUP="plugdev", MODE="0666"
EOF

    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger 2>/dev/null || true
    usermod -aG plugdev "${USER_NAME}" 2>/dev/null || true

    log_ok "udev kuralları ayarlandı"
}

# =============================================================================
# 4. Swap oluştur (256MB — OOM koruması)
# =============================================================================
step_setup_swap() {
    log_info "4/8 — Swap alanı ayarlanıyor..."

    SWAP_TOTAL=$(free -m | awk '/^Swap:/ {print $2}')
    if [ "${SWAP_TOTAL}" -ge 200 ]; then
        log_ok "Swap zaten mevcut (${SWAP_TOTAL}MB)"
        return
    fi

    SWAP_FILE="/swapfile"
    if [ -f "${SWAP_FILE}" ]; then
        swapoff "${SWAP_FILE}" 2>/dev/null || true
        rm -f "${SWAP_FILE}"
    fi

    fallocate -l 1G "${SWAP_FILE}"
    chmod 600 "${SWAP_FILE}"
    mkswap "${SWAP_FILE}" > /dev/null
    swapon "${SWAP_FILE}"

    if ! grep -q "${SWAP_FILE}" /etc/fstab; then
        echo "${SWAP_FILE} none swap sw 0 0" >> /etc/fstab
    fi

    # Swappiness düşük tut (sadece acil durumda kullan)
    sysctl -w vm.swappiness=10 > /dev/null
    if ! grep -q "vm.swappiness" /etc/sysctl.conf; then
        echo "vm.swappiness=10" >> /etc/sysctl.conf
    fi

    log_ok "1GB swap oluşturuldu (swappiness=10)"
}

# =============================================================================
# 5. Dizin yapısını oluştur ve tmpfs (RAM Disk) ayarla
# =============================================================================
step_create_dirs() {
    log_info "5/9 — Dizin yapısı ve RAM disk ayarlanıyor..."

    mkdir -p "${STATION_DIR}"/{passes,tle,logs,run}
    chown -R "${USER_NAME}:${USER_NAME}" "${STATION_DIR}"

    # Log dizini için tmpfs (25MB)
    if ! grep -q "${STATION_DIR}/logs" /etc/fstab; then
        echo "tmpfs ${STATION_DIR}/logs tmpfs nodev,nosuid,size=25M 0 0" >> /etc/fstab
    fi
    mount "${STATION_DIR}/logs" 2>/dev/null || true

    # State dosyası için tmpfs (5MB)
    if ! grep -q "${STATION_DIR}/run" /etc/fstab; then
        echo "tmpfs ${STATION_DIR}/run tmpfs nodev,nosuid,size=5M 0 0" >> /etc/fstab
    fi
    mount "${STATION_DIR}/run" 2>/dev/null || true

    log_ok "Dizinler hazır (logs ve run tmpfs olarak ayarlandı)"
}

# =============================================================================
# 6. Python sanal ortam + bağımlılıklar
# =============================================================================
step_python_venv() {
    log_info "6/8 — Python venv oluşturuluyor..."

    if [ -d "${VENV_DIR}" ]; then
        log_info "  Mevcut venv bulundu, güncelleniyor..."
    else
        sudo -u "${USER_NAME}" python3 -m venv "${VENV_DIR}"
    fi

    sudo -u "${USER_NAME}" "${VENV_DIR}/bin/pip" install -q --upgrade pip
    sudo -u "${USER_NAME}" "${VENV_DIR}/bin/pip" install -q -r "${STATION_DIR}/requirements.txt"

    log_ok "Python venv hazır ($(${VENV_DIR}/bin/python --version))"
}

# =============================================================================
# 7. Systemd servisleri kur
# =============================================================================
step_systemd() {
    log_info "7/8 — Systemd servisleri kuruluyor..."

    # Service dosyalarındaki yolları güncelle
    for svc_file in "${STATION_DIR}"/systemd/*.service; do
        svc_name=$(basename "${svc_file}")
        # Yolları ve kullanıcıyı güncelleyerek kopyala
        sed -e "s|/home/pi/meteor-station|${STATION_DIR}|g" \
            -e "s|User=pi|User=${USER_NAME}|g" \
            -e "s|Group=pi|Group=${USER_NAME}|g" \
            "${svc_file}" > "/etc/systemd/system/${svc_name}"
        log_info "  ${svc_name} kuruldu"
    done

    systemctl daemon-reload
    systemctl enable meteor-scheduler.service 2>/dev/null
    systemctl enable meteor-web.service 2>/dev/null

    log_ok "Systemd servisleri aktifleştirildi"
}

# =============================================================================
# 8. Hardware Watchdog ayarla (Kernel Panic koruması)
# =============================================================================
step_hardware_watchdog() {
    log_info "8/9 — Hardware Watchdog ayarlanıyor..."

    # systemd yapılandırması
    if ! grep -q "^RuntimeWatchdogSec=" /etc/systemd/system.conf; then
        sed -i 's/#RuntimeWatchdogSec=.*/RuntimeWatchdogSec=30/' /etc/systemd/system.conf 2>/dev/null || \
        echo "RuntimeWatchdogSec=30" >> /etc/systemd/system.conf
    fi

    # Raspberry Pi için bcm2835_wdt modülünün yüklü olmasını sağla
    if ! grep -q "bcm2835_wdt" /etc/modules; then
        echo "bcm2835_wdt" >> /etc/modules
    fi

    systemctl daemon-reload
    log_ok "Hardware Watchdog (30sn) aktif edildi"
}

# =============================================================================
# 9. Journald log limitlerini ayarla (SD kart koruma)
# =============================================================================
step_journald() {
    log_info "9/9 — Journald limitleri ayarlanıyor..."

    mkdir -p /etc/systemd/journald.conf.d
    cat > /etc/systemd/journald.conf.d/meteor-station.conf << 'EOF'
[Journal]
SystemMaxUse=50M
SystemMaxFileSize=10M
MaxRetentionSec=7day
EOF

    systemctl restart systemd-journald 2>/dev/null || true
    log_ok "Journald: max 50MB, 7 gün"
}

# =============================================================================
# satdump kontrolü
# =============================================================================
check_satdump() {
    echo ""
    if command -v satdump &>/dev/null; then
        log_ok "satdump bulundu: $(which satdump)"
    else
        log_warn "satdump bulunamadı!"
        echo ""
        echo -e "  satdump'ı haricen kur:"
        echo -e "    ${CYAN}git clone https://github.com/SatDump/SatDump.git${NC}"
        echo -e "    ${CYAN}cd SatDump && mkdir build && cd build${NC}"
        echo -e "    ${CYAN}cmake -DCMAKE_BUILD_TYPE=Release -DBUILD_GUI=OFF ..${NC}"
        echo -e "    ${CYAN}make -j1${NC}   ← Pi 3B+ için tek çekirdek"
        echo -e "    ${CYAN}sudo make install${NC}"
        echo ""
    fi
}

# =============================================================================
# RTL-SDR testi
# =============================================================================
check_rtlsdr() {
    if command -v rtl_test &>/dev/null; then
        if rtl_test -t 2>&1 | head -3 | grep -q "Found 1 device"; then
            log_ok "RTL-SDR cihazı algılandı ✅"
        else
            log_warn "RTL-SDR cihazı algılanamadı (takılı değilse normal)"
        fi
    fi
}

# =============================================================================
# Servisleri başlat
# =============================================================================
start_services() {
    echo ""
    log_info "Servisler başlatılıyor..."

    systemctl start meteor-web.service 2>/dev/null || true
    sleep 2
    systemctl start meteor-scheduler.service 2>/dev/null || true
    sleep 2

    # Durum kontrolü
    echo ""
    if systemctl is-active --quiet meteor-web.service; then
        IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
        log_ok "🌐 Web panel çalışıyor → http://${IP}:8080"
    else
        log_warn "Web panel başlatılamadı"
        echo "  Kontrol: sudo journalctl -u meteor-web -n 20"
    fi

    if systemctl is-active --quiet meteor-scheduler.service; then
        log_ok "📡 Zamanlayıcı çalışıyor"
    else
        log_warn "Zamanlayıcı başlatılamadı"
        echo "  Kontrol: sudo journalctl -u meteor-scheduler -n 20"
    fi
}

# =============================================================================
# MAIN
# =============================================================================
main() {
    echo ""
    echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║  🛰️  METEOR Station — Pi 3B+ Kurulum Scripti       ║${NC}"
    echo -e "${BOLD}${CYAN}║  1GB RAM | 32GB SD | Pi OS 64-bit Lite              ║${NC}"
    echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  Kullanıcı:  ${BOLD}${USER_NAME}${NC}"
    echo -e "  Dizin:      ${BOLD}${STATION_DIR}${NC}"
    echo ""

    check_root

    step_system_packages
    step_blacklist_dvb
    step_udev_rules
    step_setup_swap
    step_create_dirs
    step_python_venv
    step_systemd
    step_hardware_watchdog
    step_journald

    check_satdump
    check_rtlsdr
    start_services

    # RAM durumu
    echo ""
    echo -e "${CYAN}📊 Bellek Durumu:${NC}"
    free -h | head -3
    echo ""

    echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  ✅ KURULUM TAMAMLANDI!                             ║${NC}"
    echo -e "${GREEN}╠══════════════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║                                                      ║${NC}"
    IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "???")
    echo -e "${GREEN}║  🌐 Web Panel: ${BOLD}http://${IP}:8080${NC}${GREEN}            ║${NC}"
    echo -e "${GREEN}║                                                      ║${NC}"
    echo -e "${GREEN}║  📋 Komutlar:                                        ║${NC}"
    echo -e "${GREEN}║    Durum:    systemctl status meteor-web              ║${NC}"
    echo -e "${GREEN}║             systemctl status meteor-scheduler         ║${NC}"
    echo -e "${GREEN}║    Loglar:   journalctl -u meteor-scheduler -f        ║${NC}"
    echo -e "${GREEN}║    Durdur:   sudo systemctl stop meteor-scheduler     ║${NC}"
    echo -e "${GREEN}║    Başlat:   sudo systemctl start meteor-scheduler    ║${NC}"
    echo -e "${GREEN}║    Manuel:   ./start.sh                               ║${NC}"
    echo -e "${GREEN}║                                                      ║${NC}"
    echo -e "${GREEN}║  ⚠️  İlk kez kuruluyorsa sistemi yeniden başlat:     ║${NC}"
    echo -e "${GREEN}║      sudo reboot                                      ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""
}

main "$@"
