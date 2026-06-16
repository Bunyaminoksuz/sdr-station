<div align="center">
  <h1>🛰️ Autonomous METEOR Station</h1>
  <p><b>Raspberry Pi için Tam Otonom METEOR-M Uydu Yer İstasyonu</b></p>
  <p>
    <a href="README.md">🇬🇧 English</a> • 
    <a href="README_TR.md">🇹🇷 Türkçe</a>
  </p>
</div>

---

### 📡 Bu Proje Ne Yapıyor?
Autonomous METEOR Station, bir Raspberry Pi ve RTL-SDR cihazını kullanarak uzaydaki **METEOR-M** (Rus hava durumu uyduları) uydularından tam otonom (insansız) bir şekilde sinyal alan, bu sinyalleri kaydeden ve hava durumu fotoğraflarına/telemetri verilerine dönüştüren bir gömülü sistem (edge computing) yazılımıdır. 

### 🚀 Neden Kullanmalıyım?
Sıradan uydu takip scriptlerinden farklı olarak bu proje **Endüstriyel Cihaz (SRE)** standartlarında yazılmıştır:
* **Tam Otonom:** Elektrik geldiğinde kendi başlar, güneş/uydu verilerini hesaplar ve uydu geçerken otomatik kayıt alır.
* **1GB RAM Koruması:** Raspberry Pi 3B+ gibi kısıtlı cihazlarda OOM (Out Of Memory) çökmesini engellemek için RAM limitörleri ve Swap stratejileri kullanır.
* **SD Kart Koruması:** Saniyede onlarca kez güncellenen sistem loglarını ve state dosyalarını SD kart yerine **RAM Disk'e (tmpfs)** yazar. SD kart ömrünü uzatır.
* **Donanımsal Watchdog:** İşletim sistemi veya USB portları kitlenirse cihaz kendini donanımsal olarak (bcm2835_wdt) yeniden başlatır. Otonom hata kurtarma sağlar.
* **Şık Web Dashboard:** Cihazın ürettiği görselleri, uydu ısı telemetrilerini ve sistem sağlığını anlık olarak web tarayıcınızdan izleyebilirsiniz.

### 🔧 Desteklenen Donanım & Uydular

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
git clone https://github.com/KULLANICI_ADIN/sdr-station.git
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
scp web/server.py pi@RASPBERRY_IP:~/sdr-station/web/
scp -r * pi@RASPBERRY_IP:~/sdr-station/
```

**Eski Uydu Verilerini Silme:**
Disk dolarsa sistem eski dosyaları otomatik siler. Ancak siz manuel olarak bir geçişi tamamen silmek isterseniz:
```bash
rm -rf ~/sdr-station/passes/*
```
