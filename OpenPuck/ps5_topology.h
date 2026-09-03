// ps5_topology.h -- wired DualSense USB topology for PS5 Game/Clean mode.
#pragma once
extern "C" {
#include "device/usbd_pvt.h"
}
void ps5TopologyAddInterface(void);
const usbd_class_driver_t *ps5TopologyClassDriver(void);
