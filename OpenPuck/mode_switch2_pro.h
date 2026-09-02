// mode_switch2_pro.h -- Nintendo Switch 2 Pro USB personality.
#pragma once
#include "controllers.h"

class Switch2ProController : public IController {
    public:
	void begin() override;
	void task() override;
	bool dynamicMount() const override
	{
		return true;
	}
	uint8_t maxSlots() const override;
	void usbIdentity() override;
	void beginPool() override;
	void mountSlots(uint8_t k) override;
};

extern Switch2ProController g_switch2Pro;

uint8_t switch2ProMapGet(uint8_t index);
void switch2ProMapSet(uint8_t index, uint8_t value);
