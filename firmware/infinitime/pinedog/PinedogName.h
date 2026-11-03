#pragma once

#include <cstdint>

/*
 * Dog name for display (for example on the System Info screen), so two watches can be
 * told apart. Returns "Pinedog" until a name is set over BLE.
 */
namespace Pinetime {
  namespace Pinedog {
    const char* DogName();
    /* Last value written to the boot-step register (survives a watchdog reset). */
    uint32_t LastBootStep();
  }
}
