// ps5_native_usb.h -- byte-faithful wired DualSense USB composite POC.
#pragma once
#include <Adafruit_TinyUSB.h>
#include <stdint.h>

void ps5NativeUsbBegin(void);
void ps5NativeUsbMount(void);

const uint8_t *ps5NativeReportDescriptor(void);
uint16_t ps5NativeGetReport(uint8_t reportId, hid_report_type_t reportType,
			    uint8_t *buffer, uint16_t reqLen);
void ps5NativeSetReport(uint8_t reportId, hid_report_type_t reportType,
			uint8_t const *buffer, uint16_t size);
bool ps5NativeBuildInput(uint8_t out[63]);
