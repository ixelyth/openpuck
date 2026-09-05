// mode_joycon2.h -- clean Nintendo Joy-Con 2 USB personality.
#pragma once
#include "controllers.h"

class JoyCon2Controller : public IController {
    public:
	void begin() override;
	void onReport45(int slot, const uint8_t *rep, bool fresh,
			uint8_t bodyTlen) override;
	void task() override;
};

extern JoyCon2Controller g_joyCon2;

// Custom TinyUSB class driver for the exact two-interface Joy-Con 2 USB shape.
const usbd_class_driver_t *joyCon2ClassDriver(void);

// Nintendo device-level vendor control requests used before/alongside bulk commands.
bool joyCon2VendorControlXfer(uint8_t rhport, uint8_t stage,
			      const tusb_control_request_t *request);
