#include "operating_mode.hpp"

namespace jarred_drive {

bool ModeController::start_recording() {
  if (mode_ != LoggerMode::kPreRide && mode_ != LoggerMode::kChargingIdle) return false;
  mode_ = LoggerMode::kRecording;
  return true;
}

bool ModeController::stop_recording() {
  if (mode_ != LoggerMode::kRecording) return false;
  mode_ = LoggerMode::kPostRide;
  return true;
}

bool ModeController::finalize_session() {
  if (mode_ != LoggerMode::kPostRide) return false;
  mode_ = LoggerMode::kChargingIdle;
  return true;
}

bool ModeController::enter_sync() {
  if (mode_ == LoggerMode::kRecording || mode_ == LoggerMode::kPostRide) return false;
  mode_ = LoggerMode::kSync;
  return true;
}

bool ModeController::leave_sync() {
  if (mode_ != LoggerMode::kSync) return false;
  mode_ = LoggerMode::kChargingIdle;
  return true;
}

}  // namespace jarred_drive
