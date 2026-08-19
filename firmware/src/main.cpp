#ifdef ARDUINO

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <SD_MMC.h>
#include <SPI.h>
#include <TinyGPSPlus.h>
#include <VescUart.h>
#include <WebServer.h>
#include <WiFi.h>
#include <Wire.h>
#include <ESPmDNS.h>
#include <mbedtls/sha256.h>

#include <algorithm>
#include <array>
#include <cmath>

#include "device_config.hpp"
#include "operating_mode.hpp"
#include "safety.hpp"
#include "telemetry.hpp"

namespace {

using jarred_drive::SafetyLevel;
using jarred_drive::TelemetrySample;

// Locked hardware map from DIY_Foil_Assist_Build_Wiring_Guide_v3.
constexpr int kMuxS0 = 7;
constexpr int kMuxS1 = 8;
constexpr int kMuxS2 = 9;
constexpr int kMuxAdc = 4;
constexpr int kWaterExcitation = 6;
constexpr int kVescRx = 44;
constexpr int kVescTx = 43;
// Reserved Phase-2 interface: GNSS TX -> ESP GPIO2 RX; GPIO3 TX is optional.
constexpr int kGnssRx = 2;
constexpr int kGnssTx = 3;
constexpr int kLcdDc = 41;
constexpr int kLcdCs = 42;
constexpr int kLcdSclk = 40;
constexpr int kLcdMosi = 45;
constexpr int kLcdReset = 39;
constexpr int kLcdBacklight = 46;
constexpr int kImuSda = 11;  // Confirm against the physical Type-B schematic before energizing.
constexpr int kImuScl = 10;
constexpr std::uint8_t kQmiAddress = 0x6B;
constexpr std::uint8_t kQmiWhoAmI = 0x00;
constexpr std::uint8_t kQmiCtrl1 = 0x02;
constexpr std::uint8_t kQmiCtrl2 = 0x03;
constexpr std::uint8_t kQmiCtrl3 = 0x04;
constexpr std::uint8_t kQmiCtrl7 = 0x08;
constexpr std::uint8_t kQmiAccelData = 0x35;
constexpr float kAdcFullScale = 4095.0F;
constexpr float kAdcVcc = 3.3F;
constexpr float kFixedResistance = 10000.0F;
constexpr float kNtcBeta = 3950.0F;
constexpr std::uint32_t kTelemetryPeriodMs = 100;
constexpr std::uint32_t kDisplayPeriodMs = 250;
constexpr std::uint32_t kFlushPeriodMs = 1000;
constexpr int kWetAdcThresholdBenchPlaceholder = 1800;

HardwareSerial vesc_serial(1);
HardwareSerial gnss_serial(2);
VescUart vesc;
TinyGPSPlus gnss;
Adafruit_ST7789 display(&SPI, kLcdCs, kLcdDc, kLcdReset);
File log_file;
WebServer sync_server(80);
TelemetrySample sample{};
jarred_drive::ModeController mode_controller;
bool imu_available = false;
bool water_latched = false;
std::uint8_t wet_count = 0;
std::uint32_t last_sample_ms = 0;
std::uint32_t last_display_ms = 0;
std::uint32_t last_flush_ms = 0;
String session_id;
String session_directory;
std::uint32_t session_start_ms = 0;
bool sync_server_started = false;

String json_escape(const String& value) {
  String escaped;
  for (std::size_t index = 0; index < value.length(); ++index) {
    const char character = value[index];
    if (character == '\\' || character == '"') escaped += '\\';
    escaped += character;
  }
  return escaped;
}

String sha256_file(const String& path) {
  File file = SD_MMC.open(path, FILE_READ);
  if (!file) return "";
  mbedtls_sha256_context context;
  mbedtls_sha256_init(&context);
  mbedtls_sha256_starts_ret(&context, 0);
  std::uint8_t buffer[1024];
  while (file.available()) {
    const std::size_t read = file.read(buffer, sizeof(buffer));
    mbedtls_sha256_update_ret(&context, buffer, read);
  }
  std::uint8_t digest[32];
  mbedtls_sha256_finish_ret(&context, digest);
  mbedtls_sha256_free(&context);
  file.close();
  String encoded;
  encoded.reserve(64);
  constexpr char hex[] = "0123456789abcdef";
  for (std::uint8_t byte : digest) {
    encoded += hex[byte >> 4];
    encoded += hex[byte & 0x0F];
  }
  return encoded;
}

void write_register(std::uint8_t reg, std::uint8_t value) {
  Wire.beginTransmission(kQmiAddress);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission();
}

bool read_registers(std::uint8_t reg, std::uint8_t* destination, std::size_t length) {
  Wire.beginTransmission(kQmiAddress);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  const std::size_t received = Wire.requestFrom(kQmiAddress, length);
  if (received != length) return false;
  for (std::size_t index = 0; index < length; ++index) destination[index] = Wire.read();
  return true;
}

bool initialize_imu() {
  Wire.begin(kImuSda, kImuScl);
  std::uint8_t identity = 0;
  if (!read_registers(kQmiWhoAmI, &identity, 1) || identity != 0x05) return false;
  // ±8 g, 250 Hz; ±512 dps, 250 Hz. Verify scaling using Waveshare's demo at Gate 4.
  write_register(kQmiCtrl1, 0x60);
  write_register(kQmiCtrl2, 0x23);
  write_register(kQmiCtrl3, 0x43);
  write_register(kQmiCtrl7, 0x03);
  return true;
}

std::int16_t little_endian_i16(const std::uint8_t* data) {
  return static_cast<std::int16_t>(static_cast<std::uint16_t>(data[0]) |
                                   (static_cast<std::uint16_t>(data[1]) << 8));
}

void read_imu(TelemetrySample& target) {
  if (!imu_available) return;
  std::uint8_t raw[12]{};
  if (!read_registers(kQmiAccelData, raw, sizeof(raw))) return;
  constexpr float accel_scale = 4096.0F;  // LSB/g for ±8 g.
  constexpr float gyro_scale = 64.0F;     // LSB/(degree/s) for ±512 dps.
  target.accel_x_g = little_endian_i16(raw) / accel_scale;
  target.accel_y_g = little_endian_i16(raw + 2) / accel_scale;
  target.accel_z_g = little_endian_i16(raw + 4) / accel_scale;
  target.gyro_x_dps = little_endian_i16(raw + 6) / gyro_scale;
  target.gyro_y_dps = little_endian_i16(raw + 8) / gyro_scale;
  target.gyro_z_dps = little_endian_i16(raw + 10) / gyro_scale;
}

void select_mux(std::uint8_t channel) {
  digitalWrite(kMuxS0, channel & 0x01);
  digitalWrite(kMuxS1, (channel >> 1) & 0x01);
  digitalWrite(kMuxS2, (channel >> 2) & 0x01);
  delayMicroseconds(120);
}

std::uint16_t averaged_adc(std::uint8_t channel) {
  select_mux(channel);
  std::uint32_t sum = 0;
  for (int index = 0; index < 8; ++index) sum += analogRead(kMuxAdc);
  return static_cast<std::uint16_t>(sum / 8);
}

float ntc_celsius(std::uint16_t adc) {
  const float voltage = static_cast<float>(adc) / kAdcFullScale * kAdcVcc;
  if (voltage <= 0.001F || voltage >= kAdcVcc - 0.001F) return NAN;
  const float resistance = kFixedResistance * voltage / (kAdcVcc - voltage);
  const float kelvin = 1.0F / (1.0F / 298.15F + logf(resistance / 10000.0F) / kNtcBeta);
  return kelvin - 273.15F;
}

void read_monitoring_board(TelemetrySample& target) {
  for (std::uint8_t index = 0; index < 6; ++index) target.pack_c[index] = ntc_celsius(averaged_adc(index));
  target.enclosure_c = ntc_celsius(averaged_adc(6));
  digitalWrite(kWaterExcitation, HIGH);
  delay(5);
  target.water_adc = averaged_adc(7);
  digitalWrite(kWaterExcitation, LOW);
  wet_count = target.water_adc < kWetAdcThresholdBenchPlaceholder
                  ? static_cast<std::uint8_t>(min(255, wet_count + 1))
                  : 0;
  if (wet_count >= 3) water_latched = true;
  target.water_alarm = water_latched;
}

void read_vesc(TelemetrySample& target) {
  if (!vesc.getVescValues()) return;
  target.vesc_vin_v = vesc.data.inpVoltage;
  target.vesc_battery_a = vesc.data.avgInputCurrent;
  target.vesc_motor_a = vesc.data.avgMotorCurrent;
  target.vesc_duty = vesc.data.dutyCycleNow;
  target.vesc_erpm = vesc.data.rpm;
  target.vesc_mosfet_c = vesc.data.tempMosfet;
  target.vesc_safety_ntc_c = vesc.data.tempMotor;
  target.amp_hours = vesc.data.ampHours;
  target.watt_hours = vesc.data.wattHours;
  target.fault_code = static_cast<std::uint8_t>(vesc.data.error);
}

void read_gnss(TelemetrySample& target) {
  if (!jarred_drive::kGnssEnabled) return;
  while (gnss_serial.available() > 0) gnss.encode(gnss_serial.read());
  target.gnss_valid = gnss.location.isValid() && gnss.location.age() < 2000;
  if (!target.gnss_valid) {
    target.gps_fix_quality = 0;
    return;
  }
  target.gps_lat = gnss.location.lat();
  target.gps_lon = gnss.location.lng();
  target.gps_speed_mps = static_cast<float>(gnss.speed.mps());
  target.gps_course_deg = static_cast<float>(gnss.course.deg());
  target.gps_fix_quality = 1;
}

void write_header(File& file) {
  file.print(
      "schema_version,timestamp_ms,session_id,config_id,vesc_vin_V,vesc_battery_A,"
      "vesc_motor_A,vesc_duty,vesc_erpm,vesc_mosfet_C,vesc_motor_or_safety_ntc_C,"
      "pack1_C,pack2_C,pack3_C,pack4_C,pack5_C,pack6_C,enclosure_C,water_adc,"
      "water_alarm,accel_x_g,accel_y_g,accel_z_g,gyro_x_dps,gyro_y_dps,gyro_z_dps,"
      "amp_hours,watt_hours,fault_code,remote_ok,sd_ok");
  if (jarred_drive::kGnssEnabled) {
    file.print(",gps_lat,gps_lon,gps_speed_mps,gps_course_deg,gps_fix_quality");
  }
  file.println();
}

void log_sample(const TelemetrySample& value) {
  if (!log_file) return;
  log_file.printf("%s,%lu,%s,%s", jarred_drive::kSchemaVersion,
                  static_cast<unsigned long>(value.timestamp_ms), session_id.c_str(),
                  jarred_drive::kConfigId);
  log_file.printf(",%.3f,%.3f,%.3f,%.4f,%.1f,%.2f,%.2f", value.vesc_vin_v,
                  value.vesc_battery_a, value.vesc_motor_a, value.vesc_duty, value.vesc_erpm,
                  value.vesc_mosfet_c, value.vesc_safety_ntc_c);
  for (float temperature : value.pack_c) log_file.printf(",%.2f", temperature);
  log_file.printf(",%.2f,%u,%u,%.4f,%.4f,%.4f,%.3f,%.3f,%.3f,%.5f,%.3f,%u,",
                  value.enclosure_c, value.water_adc, value.water_alarm, value.accel_x_g,
                  value.accel_y_g, value.accel_z_g, value.gyro_x_dps, value.gyro_y_dps,
                  value.gyro_z_dps, value.amp_hours, value.watt_hours, value.fault_code);
  if (value.remote_ok >= 0) log_file.print(value.remote_ok);
  log_file.printf(",%u", value.sd_ok);
  if (jarred_drive::kGnssEnabled) {
    if (value.gnss_valid) {
      log_file.printf(",%.8f,%.8f,%.3f,%.2f,%u", value.gps_lat, value.gps_lon,
                      value.gps_speed_mps, value.gps_course_deg, value.gps_fix_quality);
    } else {
      log_file.print(",,,,,0");
    }
  }
  log_file.println();
}

void draw_display(const TelemetrySample& value) {
  const auto safety = jarred_drive::evaluate_safety(value);
  const std::uint16_t accent = safety.level == SafetyLevel::kStop
                                   ? ST77XX_RED
                                   : (safety.level == SafetyLevel::kWarning ? ST77XX_ORANGE
                                                                            : ST77XX_CYAN);
  display.fillScreen(ST77XX_BLACK);
  display.setTextColor(accent);
  display.setTextSize(2);
  display.setCursor(8, 12);
  display.println(safety.level == SafetyLevel::kStop
                      ? "STOP SYSTEM"
                      : (safety.level == SafetyLevel::kWarning ? "WARNING" : "SYSTEM READY"));
  display.setTextColor(ST77XX_WHITE);
  display.setTextSize(2);
  display.setCursor(8, 50);
  display.printf("%4.1fV %4.0fA\n", value.vesc_vin_v, value.vesc_battery_a);
  display.setTextColor(ST77XX_CYAN);
  display.setTextSize(4);
  display.setCursor(8, 82);
  display.printf("%3.1fkW", value.vesc_vin_v * value.vesc_battery_a / 1000.0F);
  display.setTextColor(ST77XX_WHITE);
  display.setTextSize(2);
  display.setCursor(8, 135);
  display.printf("VESC %2.0fC\nPACK %2.0fC\n", value.vesc_mosfet_c,
                 *std::max_element(value.pack_c.begin(), value.pack_c.end()));
  display.setTextColor(value.water_alarm ? ST77XX_RED : ST77XX_GREEN);
  display.printf("WATER %s\n", value.water_alarm ? "WET" : "DRY");
  display.setTextColor(value.sd_ok ? ST77XX_GREEN : ST77XX_ORANGE);
  display.printf("SD    %s", value.sd_ok ? "OK" : "FAULT");
}

void write_session_config() {
  File config = SD_MMC.open(session_directory + "/config.json", FILE_WRITE);
  if (!config) return;
  config.printf(
      "{\n  \"vesc_config_id\": \"%s\",\n  \"write_policy\": \"read_only_snapshot\"\n}\n",
      jarred_drive::kConfigId);
  config.close();
}

void write_session_manifest() {
  const String telemetry_path = session_directory + "/telemetry.csv";
  const String config_path = session_directory + "/config.json";
  File telemetry = SD_MMC.open(telemetry_path, FILE_READ);
  File config = SD_MMC.open(config_path, FILE_READ);
  if (!telemetry || !config) return;
  const std::size_t telemetry_size = telemetry.size();
  const std::size_t config_size = config.size();
  telemetry.close();
  config.close();
  const String telemetry_hash = sha256_file(telemetry_path);
  const String config_hash = sha256_file(config_path);
  File manifest = SD_MMC.open(session_directory + "/manifest.json", FILE_WRITE);
  if (!manifest) return;
  manifest.printf(
      "{\n"
      "  \"schema_version\": \"1.0\",\n"
      "  \"telemetry_schema_version\": \"%s\",\n"
      "  \"device_id\": \"%s\",\n"
      "  \"session_id\": \"%s\",\n"
      "  \"start_time_utc\": \"\",\n"
      "  \"end_time_utc\": \"\",\n"
      "  \"duration_s\": %.3f,\n"
      "  \"firmware_version\": \"%s\",\n"
      "  \"hardware_revision\": \"%s\",\n"
      "  \"vesc_config_id\": \"%s\",\n"
      "  \"vesc_config_hash\": \"%s\",\n"
      "  \"files\": [\n"
      "    {\"name\": \"telemetry.csv\", \"size\": %u, \"sha256\": \"%s\"},\n"
      "    {\"name\": \"config.json\", \"size\": %u, \"sha256\": \"%s\"}\n"
      "  ]\n"
      "}\n",
      jarred_drive::kSchemaVersion, jarred_drive::kDeviceId, session_id.c_str(),
      static_cast<double>(millis() - session_start_ms) / 1000.0,
      jarred_drive::kFirmwareVersion, jarred_drive::kHardwareRevision, jarred_drive::kConfigId,
      config_hash.c_str(), static_cast<unsigned>(telemetry_size), telemetry_hash.c_str(),
      static_cast<unsigned>(config_size), config_hash.c_str());
  manifest.close();
}

void start_session() {
  if (!mode_controller.start_recording()) return;
  WiFi.mode(WIFI_OFF);
  sync_server_started = false;
  digitalWrite(kLcdBacklight, LOW);
  session_id = String("BOOT-") + String(millis());
  session_directory = String("/sessions/") + session_id;
  SD_MMC.mkdir("/sessions");
  SD_MMC.mkdir(session_directory);
  write_session_config();
  log_file = SD_MMC.open(session_directory + "/telemetry.csv", FILE_WRITE);
  if (log_file) write_header(log_file);
  session_start_ms = millis();
}

void stop_and_finalize_session() {
  if (!mode_controller.stop_recording()) return;
  if (log_file) {
    log_file.flush();
    log_file.close();
  }
  write_session_manifest();
  mode_controller.finalize_session();
  digitalWrite(kLcdBacklight, HIGH);
}

bool authenticated_request() {
  if (strlen(jarred_drive::kDeviceToken) == 0) return false;
  return sync_server.header("Authorization") ==
         String("Bearer ") + String(jarred_drive::kDeviceToken);
}

void send_device() {
  sync_server.send(
      200, "application/json",
      String("{\"device_id\":\"") + jarred_drive::kDeviceId + "\",\"name\":\"" +
          jarred_drive::kDeviceName + "\",\"hardware_revision\":\"" +
          jarred_drive::kHardwareRevision + "\",\"firmware_version\":\"" +
          jarred_drive::kFirmwareVersion + "\"}");
}

void send_status() {
  const float free_percent = SD_MMC.totalBytes() == 0
                                 ? 0.0F
                                 : 100.0F * (SD_MMC.totalBytes() - SD_MMC.usedBytes()) /
                                       SD_MMC.totalBytes();
  sync_server.send(200, "application/json",
                   String("{\"mode\":\"") + jarred_drive::mode_name(mode_controller.mode()) +
                       "\",\"battery_percent\":0,\"sd_free_percent\":" +
                       String(free_percent, 1) + "}");
}

void send_sessions() {
  File root = SD_MMC.open("/sessions");
  String payload = "[";
  bool first = true;
  if (root) {
    File entry = root.openNextFile();
    while (entry) {
      if (entry.isDirectory()) {
        String name = entry.name();
        const int slash = name.lastIndexOf('/');
        if (slash >= 0) name = name.substring(slash + 1);
        if (!first) payload += ',';
        payload += String("{\"session_id\":\"") + json_escape(name) + "\"}";
        first = false;
      }
      entry.close();
      entry = root.openNextFile();
    }
    root.close();
  }
  payload += ']';
  sync_server.send(200, "application/json", payload);
}

bool safe_component(const String& value) {
  return value.length() > 0 && value.indexOf('/') < 0 && value.indexOf("..") < 0;
}

void stream_session_file(const String& path, const char* content_type) {
  File file = SD_MMC.open(path, FILE_READ);
  if (!file) {
    sync_server.send(404, "application/json", "{\"error\":\"not_found\"}");
    return;
  }
  std::size_t offset = 0;
  const String range = sync_server.header("Range");
  if (range.startsWith("bytes=") && range.endsWith("-")) {
    offset = static_cast<std::size_t>(range.substring(6, range.length() - 1).toInt());
    if (offset > file.size()) offset = 0;
  }
  file.seek(offset);
  sync_server.sendHeader("Accept-Ranges", "bytes");
  if (offset > 0) {
    sync_server.sendHeader(
        "Content-Range",
        String("bytes ") + offset + "-" + (file.size() - 1) + "/" + file.size());
    sync_server.setContentLength(file.size() - offset);
    sync_server.send(206, content_type, "");
  } else {
    sync_server.setContentLength(file.size());
    sync_server.send(200, content_type, "");
  }
  std::uint8_t buffer[1024];
  WiFiClient client = sync_server.client();
  while (file.available() && client.connected()) {
    const std::size_t read = file.read(buffer, sizeof(buffer));
    client.write(buffer, read);
  }
  file.close();
}

void handle_session_request() {
  const String uri = sync_server.uri();
  constexpr const char* prefix = "/api/sessions/";
  const String remainder = uri.substring(strlen(prefix));
  const int slash = remainder.indexOf('/');
  if (slash < 0) {
    sync_server.send(404, "application/json", "{\"error\":\"not_found\"}");
    return;
  }
  const String requested_session = remainder.substring(0, slash);
  const String resource = remainder.substring(slash + 1);
  if (!safe_component(requested_session)) {
    sync_server.send(400, "application/json", "{\"error\":\"invalid_session\"}");
    return;
  }
  if (resource == "manifest") {
    stream_session_file(String("/sessions/") + requested_session + "/manifest.json",
                        "application/json");
    return;
  }
  constexpr const char* files_prefix = "files/";
  if (resource.startsWith(files_prefix)) {
    const String filename = resource.substring(strlen(files_prefix));
    if (!safe_component(filename)) {
      sync_server.send(400, "application/json", "{\"error\":\"invalid_file\"}");
      return;
    }
    stream_session_file(String("/sessions/") + requested_session + "/" + filename,
                        "application/octet-stream");
    return;
  }
  sync_server.send(404, "application/json", "{\"error\":\"not_found\"}");
}

void acknowledge_sync() {
  if (!authenticated_request()) {
    sync_server.send(401, "application/json", "{\"error\":\"unauthorized\"}");
    return;
  }
  // Acknowledgement records transfer state only. It never deletes session files.
  sync_server.send(200, "application/json", "{\"status\":\"acknowledged\",\"deleted\":false}");
}

void start_sync_server() {
  if (!jarred_drive::radio_allowed(mode_controller.mode()) || sync_server_started ||
      strlen(jarred_drive::kWifiSsid) == 0)
    return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(jarred_drive::kWifiSsid, jarred_drive::kWifiPassword);
  const std::uint32_t deadline = millis() + 15000;
  while (WiFi.status() != WL_CONNECTED && millis() < deadline) delay(100);
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.mode(WIFI_OFF);
    return;
  }
  MDNS.begin("jarred-drive");
  MDNS.addService("http", "tcp", 80);
  const char* headers[] = {"Authorization", "Range"};
  sync_server.collectHeaders(headers, 2);
  sync_server.on("/api/device", HTTP_GET, send_device);
  sync_server.on("/api/status", HTTP_GET, send_status);
  sync_server.on("/api/sessions", HTTP_GET, send_sessions);
  sync_server.on("/api/sync/ack", HTTP_POST, acknowledge_sync);
  sync_server.onNotFound(handle_session_request);
  sync_server.begin();
  sync_server_started = true;
}

void handle_serial_mode_command() {
  if (!Serial.available()) return;
  String command = Serial.readStringUntil('\n');
  command.trim();
  if (command == "START" && mode_controller.mode() != jarred_drive::LoggerMode::kRecording) {
    start_session();
  } else if (command == "STOP") {
    stop_and_finalize_session();
  } else if (command == "SYNC" && mode_controller.enter_sync()) {
    start_sync_server();
  } else if (command == "IDLE" && mode_controller.leave_sync()) {
    sync_server.stop();
    MDNS.end();
    WiFi.mode(WIFI_OFF);
    sync_server_started = false;
  }
}

void initialize_storage() {
  SD_MMC.setPins(14, 15, 16, 18, 17, 21);
  if (!SD_MMC.begin("/sdcard", false)) return;
}

}  // namespace

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_OFF);
  pinMode(kMuxS0, OUTPUT);
  pinMode(kMuxS1, OUTPUT);
  pinMode(kMuxS2, OUTPUT);
  pinMode(kWaterExcitation, OUTPUT);
  digitalWrite(kWaterExcitation, LOW);
  analogReadResolution(12);
  pinMode(kLcdBacklight, OUTPUT);
  digitalWrite(kLcdBacklight, HIGH);
  SPI.begin(kLcdSclk, -1, kLcdMosi, kLcdCs);
  display.init(172, 320);
  display.setSPISpeed(40000000);
  display.setRotation(1);
  display.fillScreen(ST77XX_BLACK);
  display.setTextColor(ST77XX_CYAN);
  display.setTextSize(2);
  display.setCursor(8, 20);
  display.println("JARRED DRIVE");
  display.setTextColor(ST77XX_WHITE);
  display.setTextSize(1);
  display.println("READ-ONLY FLIGHT RECORDER");
  vesc_serial.begin(115200, SERIAL_8N1, kVescRx, kVescTx);
  vesc.setSerialPort(&vesc_serial);
  if (jarred_drive::kGnssEnabled) gnss_serial.begin(9600, SERIAL_8N1, kGnssRx, kGnssTx);
  imu_available = initialize_imu();
  initialize_storage();
  // Automatic recording preserves current field behavior until the enclosure
  // button/input is assigned. Serial STOP then SYNC provides the bench workflow.
  start_session();
  delay(500);
}

void loop() {
  const std::uint32_t now = millis();
  handle_serial_mode_command();
  if (jarred_drive::sensors_recording(mode_controller.mode()) &&
      now - last_sample_ms >= kTelemetryPeriodMs) {
    last_sample_ms = now;
    sample.timestamp_ms = now;
    sample.sd_ok = static_cast<bool>(log_file);
    read_vesc(sample);
    read_gnss(sample);
    read_monitoring_board(sample);
    read_imu(sample);
    log_sample(sample);
  }
  if (mode_controller.mode() != jarred_drive::LoggerMode::kRecording &&
      now - last_display_ms >= kDisplayPeriodMs) {
    last_display_ms = now;
    draw_display(sample);
  }
  if (log_file && now - last_flush_ms >= kFlushPeriodMs) {
    last_flush_ms = now;
    log_file.flush();
  }
  if (sync_server_started) sync_server.handleClient();
  delay(1);
}

#endif  // ARDUINO
