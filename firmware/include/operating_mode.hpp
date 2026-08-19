#pragma once

namespace jarred_drive {

enum class LoggerMode { kPreRide, kRecording, kPostRide, kSync, kChargingIdle };

constexpr bool radio_allowed(LoggerMode mode) { return mode == LoggerMode::kSync; }

constexpr bool sensors_recording(LoggerMode mode) { return mode == LoggerMode::kRecording; }

inline const char* mode_name(LoggerMode mode) {
  switch (mode) {
    case LoggerMode::kPreRide:
      return "PRE_RIDE";
    case LoggerMode::kRecording:
      return "RECORDING";
    case LoggerMode::kPostRide:
      return "POST_RIDE";
    case LoggerMode::kSync:
      return "SYNC";
    case LoggerMode::kChargingIdle:
      return "CHARGING_IDLE";
  }
  return "UNKNOWN";
}

class ModeController {
 public:
  LoggerMode mode() const { return mode_; }
  bool start_recording();
  bool stop_recording();
  bool finalize_session();
  bool enter_sync();
  bool leave_sync();

 private:
  LoggerMode mode_{LoggerMode::kPreRide};
};

}  // namespace jarred_drive
