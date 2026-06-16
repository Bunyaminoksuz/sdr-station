<div align="center">
  <h1>🛰️ Autonomous METEOR Station</h1>
  <p><b>A fully autonomous METEOR-M weather satellite ground station built for Raspberry Pi and RTL-SDR.</b></p>

  <p>
    <a href="https://github.com/Bunyaminoksuz/sdr-station/stargazers"><img src="https://img.shields.io/github/stars/Bunyaminoksuz/sdr-station?style=for-the-badge&color=yellow" alt="Stars Badge"/></a>
    <a href="https://github.com/Bunyaminoksuz/sdr-station/network/members"><img src="https://img.shields.io/github/forks/Bunyaminoksuz/sdr-station?style=for-the-badge&color=blue" alt="Forks Badge"/></a>
    <img src="https://img.shields.io/badge/python-3.11-blue?style=for-the-badge" alt="Python Badge">
    <img src="https://img.shields.io/badge/platform-RaspberryPi-red?style=for-the-badge" alt="Raspberry Pi Badge">
    <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" alt="License Badge">
  </p>

  <p>
    <a href="README.md">🇬🇧 English</a> • 
    <a href="README_TR.md">🇹🇷 Türkçe</a>
  </p>
</div>

---

![Dashboard Screenshot](docs/dashboard.png)
*(Note: Please upload your dashboard screenshot to `docs/dashboard.png`)*

## 🚀 Features

* **Autonomous satellite pass prediction** (Skyfield TLE tracking)
* **Automatic IQ recording and decoding** (Baseband recording + SatDump)
* **METEOR-M N2-3 / N2-4 support** (137 MHz VHF)
* **Hardware watchdog recovery** (`bcm2835_wdt` kernel module)
* **RAM and SD card protection** (tmpfs mounting and Swap tuning for 1GB Pi 3B+)
* **Real-time web dashboard** (FastAPI + Vanilla JS)
* **Optimized for Raspberry Pi 3B+** (SRE standards & Cgroup Limits)

## 🏗️ Architecture

The system operates in a fully decoupled pipeline to prevent hardware bottlenecks during satellite passes:

```text
  [RTL-SDR (RF Capture)]
           ↓ (rtl_sdr @ 50kHz DC Offset)
  [Baseband IQ Recording]
           ↓ (Offline Processing)
      [SatDump CLI]
           ↓ (Telemetry & Imagery)
    [SQLite (WAL Mode)]
           ↓ (REST API)
    [Web UI Dashboard]
```

## 🔧 Supported Hardware

* **SBC:** Raspberry Pi 3B+ Rev 1.3 (or better)
* **OS:** Pi OS 64-bit Lite (Trixie/Bookworm)
* **SDR:** RTL-SDR Blog v4 (with Bias-T support)
* **Antenna:** V-Dipole or QFH (resonant at 137 MHz)
* **Storage:** 32GB+ High-Endurance SD Card

---

## ⚡ Quick Start

### 1. Prerequisite (SatDump Installation)
This project relies on `satdump` to process signals. Install it on your 64-bit Pi OS:
```bash
wget https://github.com/SatDump/SatDump/releases/download/1.2.2/satdump_1.2.2_arm64.deb
sudo dpkg -i satdump_1.2.2_arm64.deb
sudo apt install -f  # Fix missing dependencies
```

### 2. Download and Setup
```bash
git clone https://github.com/Bunyaminoksuz/sdr-station.git
cd sdr-station
chmod +x install.sh start.sh setup_swap.sh
sudo ./install.sh
```
*This script automatically configures the virtual env, udev rules, systemd services, hardware watchdog, and tmpfs mounts.*

### 3. Boot & Use
Reboot your device (`sudo reboot`). Once booted, open a web browser and connect to:
👉 `http://YOUR_RASPBERRY_PI_IP:8080`

Click the **Settings** icon to update your GPS coordinates (Latitude/Longitude) on your first run.

---

## 🛠️ Management Commands

If you SSH into the system, these are the essential commands:

**Service Control:**
```bash
sudo systemctl stop meteor-scheduler    # Stops the autonomous scheduler
sudo systemctl start meteor-scheduler   # Starts the scheduler
sudo systemctl restart meteor-scheduler # Restarts the system
sudo systemctl status meteor-scheduler  # Shows running status
```

**Monitor Live Logs:**
```bash
journalctl -u meteor-scheduler -f
# or
tail -f ~/sdr-station/logs/meteor_station.log
```
