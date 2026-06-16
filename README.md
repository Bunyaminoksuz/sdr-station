<div align="center">
  <h1>🛰️ Autonomous METEOR Station</h1>
  <p><b>v2.3 (Production Ready / Edge Computing HA)</b></p>
  <p>
    <a href="#tr-türkçe">🇹🇷 Türkçe</a> • 
    <a href="#en-english">🇬🇧 English</a>
  </p>
</div>

---

<h2 id="tr-türkçe">🇹🇷 TÜRKÇE</h2>

### 📡 Bu Proje Ne Yapıyor?
Autonomous METEOR Station, bir Raspberry Pi ve RTL-SDR cihazını kullanarak uzaydaki **METEOR-M** (Rus hava durumu uyduları) uydularından tam otonom (insansız) bir şekilde sinyal alan, bu sinyalleri kaydeden ve hava durumu fotoğraflarına/telemetri verilerine dönüştüren bir gömülü sistem (edge computing) yazılımıdır. 

### 🚀 Neden Kullanmalıyım?
Sıradan uydu takip scriptlerinden farklı olarak bu proje **Endüstriyel Cihaz (SRE)** standartlarında yazılmıştır:
* **Tam Otonom:** Elektrik geldiğinde kendi başlar, güneş/uydu verilerini hesaplar ve uydu geçerken otomatik kayıt alır.
* **1GB RAM Koruması:** Raspberry Pi 3B+ gibi kısıtlı cihazlarda OOM (Out Of Memory) çökmesini engellemek için RAM limitörleri ve Swap stratejileri kullanır.
* **SD Kart Koruması:** Saniyede onlarca kez güncellenen sistem loglarını ve state dosyalarını SD kart yerine **RAM Disk'e (tmpfs)** yazar. SD kartınız yıllarca bozulmaz.
* **Donanımsal Watchdog:** İşletim sistemi veya USB portları kitlenirse cihaz kendini donanımsal olarak yeniden başlatır. Dağ başına kursanız bile yanına gitmenize gerek kalmaz.
* **Şık Web Dashboard:** Cihazın ürettiği görselleri, uydu ısı telemetrilerini ve sistem sağlığını anlık olarak web tarayıcınızdan izleyebilirsiniz.

### 🔧 Desteklenen Donanım & Uydular
Bu proje belirli donanımlar ve uydular için test edilmiş ve optimize edilmiştir:

**Donanım:**
* **SBC:** Raspberry Pi 3B+ Rev 1.3 (veya daha iyisi)
* **OS:** Pi OS 64-bit Lite (Trixie/Bookworm)
* **SDR:** RTL-SDR Blog v4 (Bias-T destekli)
* **Anten:** V-Dipol veya QFH (137 MHz rezonanslı)
* **Depolama:** 32GB+ Kaliteli SD Kart

**Desteklenen Uydular:**
* **METEOR-M N2-4** (NORAD: 59051, Frekans: 137.1 MHz)
* **METEOR-M N2-3** (NORAD: 57166, Frekans: 137.9 MHz)
*(Not: NOAA-15/18/19 uyduları ömürlerini tamamladığı için destek listesinden çıkarılmıştır).*

### ⚙️ Nasıl Kurarım?
Proje Raspberry Pi OS (64-bit Lite) üzerinde çalışacak şekilde optimize edilmiştir.

**1. Ön Gereksinim (SatDump Kurulumu):** 
Bu proje sinyalleri işlemek için `satdump` kullanır. Sisteminizde (özellikle 64-bit Pi OS'da) şu komutlarla hızlıca kurabilirsiniz:
```bash
wget https://github.com/SatDump/SatDump/releases/download/1.2.2/satdump_1.2.2_arm64.deb
sudo dpkg -i satdump_1.2.2_arm64.deb
sudo apt install -f  # Eksik bağımlılıkları tamamlar
```

**2. İndirme ve Kurulum:**
Terminalinizi açın ve Raspberry Pi'nize bağlanın:
```bash
git clone https://github.com/KULLANICI_ADIN/REPO_ADIN.git sdr-station
cd sdr-station
chmod +x install.sh start.sh setup_swap.sh
sudo ./install.sh
```
*Bu script her şeyi (sanal ortam, udev kuralları, systemd servisleri, watchdog) otomatik kuracaktır.*

**3. Sistemi Başlatın:**
Cihazı yeniden başlatın (`sudo reboot`). Cihaz açıldığında sistem arka planda otomatik çalışmaya başlayacaktır.

### 💻 Nasıl Kullanırım?
Kurulum bittikten sonra telefonunuzdan veya bilgisayarınızdan Raspberry Pi'nin IP adresine 8080 portuyla bağlanın:
👉 `http://RASPBERRY_PI_IP_ADRESI:8080`

Karşınıza karanlık temalı (Dark UI) bir kontrol paneli çıkacaktır. Buradan:
- Gelecek uydu geçişlerini görebilirsiniz.
- Cihazın o anki CPU/RAM/Sıcaklık durumunu takip edebilirsiniz.
- Geçmişte kaydedilmiş uydu fotoğraflarına ve telemetri verilerine bakabilirsiniz.
- Ayarlar ikonuna tıklayarak GPS koordinatlarınızı girebilirsiniz. (Lütfen ilk kullanımda kendi Enlem/Boylam değerlerinizi girin).

### 🛠️ Temel Komutlar (Yönetim)

Eğer sisteme SSH ile bağlanırsanız şu komutları bilmeniz işinizi kolaylaştırır:

**Sistemi Durdurma / Başlatma:**
```bash
sudo systemctl stop meteor-scheduler    # Uydu dinlemeyi durdurur
sudo systemctl start meteor-scheduler   # Uydu dinlemeyi başlatır
sudo systemctl restart meteor-scheduler # Sistemi yeniden başlatır
sudo systemctl status meteor-scheduler  # Sistemin açık/kapalı durumunu gösterir
```

**Canlı Logları (Ne Yaptığını) İzleme:**
```bash
journalctl -u meteor-scheduler -f
# veya
tail -f ~/sdr-station/logs/meteor_station.log
```

**Dosya (Kod) Yükleme / Güncelleme:**
PC'nizde kodlarda bir değişiklik yapıp Raspberry'e atmak isterseniz (SCP ile):
```bash
# Sadece server.py dosyasını güncellemek:
scp web/server.py pi@RASPBERRY_IP:~/sdr-station/web/

# Tüm projeyi baştan atmak (passes.db veritabanını ezmemeye dikkat edin):
scp -r * pi@RASPBERRY_IP:~/sdr-station/
```

**Eski Uydu Verilerini Silme:**
Disk dolarsa sistem eski dosyaları otomatik siler. Ancak siz manuel olarak bir geçişi tamamen silmek isterseniz:
```bash
# Tüm geçmişi silmek için passes klasörünün içini boşaltın:
rm -rf ~/sdr-station/passes/*
```

---
<br><br>

<h2 id="en-english">🇬🇧 ENGLISH</h2>

### 📡 What Does This Project Do?
Autonomous METEOR Station is an edge computing software that transforms a Raspberry Pi and an RTL-SDR dongle into a fully autonomous ground station. It listens for **METEOR-M** (Russian weather) satellites, records their signals when they fly over, and decodes them into weather imagery and telemetry data without any human intervention.

### 🚀 Why Should I Use It?
Unlike basic script-based satellite trackers, this project is built with **Site Reliability Engineering (SRE)** standards:
* **Fully Autonomous:** Boots up automatically, calculates satellite passes, and records baseband IQ automatically.
* **1GB RAM Protection:** Utilizes cgroup limiters and Swap strategies to prevent Out-Of-Memory (OOM) crashes on constrained devices like the Pi 3B+.
* **SD Card Protection:** Prevents SD card wear by mounting high-frequency I/O directories (logs, state files) directly to a RAM Disk (`tmpfs`).
* **Hardware Watchdog:** If the OS freezes or USB/SDR drivers deadlock, the `bcm2835_wdt` hardware watchdog physically restarts the Pi. You can deploy it on a remote mountain and forget about it.
* **Sleek Web Dashboard:** You can monitor system health, satellite thermal telemetry, and generated images live from your web browser.

### 🔧 Supported Hardware & Satellites
This project has been tested and optimized for specific hardware and satellites:

**Hardware:**
* **SBC:** Raspberry Pi 3B+ Rev 1.3 (or better)
* **OS:** Pi OS 64-bit Lite (Trixie/Bookworm)
* **SDR:** RTL-SDR Blog v4 (with Bias-T support)
* **Antenna:** V-Dipole or QFH (resonant at 137 MHz)
* **Storage:** 32GB+ High-Endurance SD Card

**Supported Satellites:**
* **METEOR-M N2-4** (NORAD: 59051, Frequency: 137.1 MHz)
* **METEOR-M N2-3** (NORAD: 57166, Frequency: 137.9 MHz)
*(Note: NOAA-15/18/19 satellites have been decommissioned and are no longer supported).*

### ⚙️ How to Install?
The project is optimized for Raspberry Pi OS (64-bit Lite).

**1. Prerequisite (SatDump Installation):** 
This project relies on `satdump` to process signals. You can quickly install it on a 64-bit Pi OS using:
```bash
wget https://github.com/SatDump/SatDump/releases/download/1.2.2/satdump_1.2.2_arm64.deb
sudo dpkg -i satdump_1.2.2_arm64.deb
sudo apt install -f  # Fix missing dependencies
```

**2. Download and Setup:**
Open your terminal and connect to your Raspberry Pi:
```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git sdr-station
cd sdr-station
chmod +x install.sh start.sh setup_swap.sh
sudo ./install.sh
```
*This script automatically configures everything (virtual env, udev rules, systemd services, hardware watchdog, tmpfs mounts).*

**3. Boot the System:**
Reboot your device (`sudo reboot`). Once booted, the station will run quietly in the background.

### 💻 How to Use?
After installation, open a web browser on your phone or PC and connect to the Pi's IP address on port 8080:
👉 `http://YOUR_RASPBERRY_PI_IP:8080`

You will be greeted with a Dark UI dashboard where you can:
- View upcoming satellite passes.
- Monitor CPU, RAM, Temperature, and Disk usage.
- Browse the gallery of historical satellite images and telemetry logs.
- Click the Settings icon to update your GPS coordinates (Please set your observer Latitude/Longitude on first run).

### 🛠️ Basic Commands (Management)

If you SSH into the system, these are the essential commands you should know:

**Stop / Start the System:**
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

**Upload / Update Code:**
If you made changes on your PC and want to push them to the Pi (using SCP):
```bash
# Update a single file:
scp web/server.py pi@RASPBERRY_IP:~/sdr-station/web/

# Update the entire project (be careful not to overwrite passes.db):
scp -r * pi@RASPBERRY_IP:~/sdr-station/
```

**Delete Old Satellite Data:**
The system automatically deletes old passes when the disk gets full. If you want to manually clear all history:
```bash
# Delete everything inside the passes directory:
rm -rf ~/sdr-station/passes/*
```
