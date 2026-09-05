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
