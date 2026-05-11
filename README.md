# NMEA2000 Simulator

A lightweight desktop simulator for broadcasting **NMEA 2000 / ISO 11783** CAN traffic from a USB-CAN adapter that uses `ECanVci.dll` (GCAN-style API).

The application provides a Tkinter GUI to:
- emulate an engine node,
- emulate a second binary-switch node,
- transmit selected PGNs once or periodically,
- and send switch command group-function messages when virtual buttons are pressed.

---

## Purpose

This project is intended for bench/lab integration and testing scenarios where you need a controllable NMEA 2000 message source without a real engine ECU or switch panel.

Typical use cases:
- Validate PGN parsing in a chart plotter, gateway, or data logger.
- Exercise application logic using synthetic engine telemetry.
- Simulate a second node (switch bank) and related control/status traffic.
- Reproduce repeatable CAN traffic patterns during development.

---

## Requirements

### Operating system
- **Windows** (required at runtime to load `ECanVci.dll`).

### Software
- **Python 3.10+** (for type hints such as `int | None`).
- Standard library only (`ctypes`, `tkinter`, `dataclasses`, etc.) — no third-party Python packages are required.

### Hardware / driver
- A compatible USB-CAN adapter exposing the expected `ECanVci.dll` functions:
  - `OpenDevice`
  - `CloseDevice`
  - `InitCAN`
  - `StartCAN`
  - `Transmit`
- `ECanVci.dll` available in the app working directory, or configure its absolute path in the GUI.

### Bus assumptions
- CAN timing in this app is configured for **250 kbps**.
- Frames are sent in **29-bit extended ID** format for NMEA 2000-style identifiers.

---

## Usage

### 1) Start the full engine/switch simulator
From the repository directory:

```bash
python nmea2000_simulator.py
```

### Start the standalone 8-switch simulator
If you only need binary switching simulation without the engine fields, run:

```bash
python nmea2000_binary_switch_simulator.py
```

This smaller program simulates one NMEA 2000 binary switch-bank node with 8 pushbuttons. It defaults to CAN address `55` and bank instance `1`. It sends ISO Address Claim on connect, on simplified source-address conflict, and every 30 seconds; it sends Heartbeat every second. Switch clicks send only PGN 127502 Binary Switch Bank Control with the inverse of the last received status, and received PGN 127501 feedback latches the button labels.

### 2) Configure connection and node identity
In the GUI, set at minimum:
- **DLL path**: path to `ECanVci.dll`.
- **Source address**: primary simulated node address (0..251).
- **Destination**: destination address for PDU1 messages (typically `255` for global).
- **Engine instance** and optional identity/product fields.

You can also configure the virtual second node:
- switch node source address,
- switch node NAME and manufacturer code,
- switch product information.

### 3) Connect to CAN device
- Click **Connect**.
- On success, status changes to connected and one transmit cycle is triggered.

### 4) Select what to transmit
In the full simulator, use the **Enabled messages** checkboxes to include/exclude PGNs such as address claim, product info, heartbeat, engine data, and binary switch status.

In the standalone 8-switch simulator:
- Address Claim (60928) is automatic on connect/conflict and every 30 seconds.
- Heartbeat (126993) is automatic every second.
- Binary Switch Bank Status (127501) can be sent at **Interval ms** when enabled.
- Binary Switch Bank Status (127501) can also be received to latch button labels.
- Button clicks send Binary Switch Bank Control (127502); PGN 126208 is not used.

### 5) Send data
- **Send Once**: transmit one burst of currently enabled messages.
- **Start Periodic**: keep transmitting at **Interval ms**.
- **Stop Periodic**: stop scheduled periodic transmission.
- **Disconnect**: close the CAN device.

### 6) Use virtual switch buttons
In **Binary Switch Bank**:
- In the standalone 8-switch simulator, clicking a button sends **PGN 127502 Binary Switch Bank Control** with the inverse of that switch's last received status.
- The GUI does not latch immediately from the click; it waits up to 200 ms for **PGN 127501 Binary Switch Bank Status** feedback for the selected bank instance.
- Received feedback updates the button label to `ON`, `OFF`, `ERROR`, or `N/A`; if no feedback arrives within 200 ms, the pending label returns to the last received status.
- Periodic status transmission can publish bank state via **PGN 127501**.

---

## Notes about the code (structure and comments)

The Python source is intentionally organized around small, focused functions with descriptive names and inline protocol comments.

### High-level structure
- **Constants**: device defaults, timing values, and PGN IDs are centralized at top-level for easy adjustments.
- **Data models**:
  - `DeviceConfig` for adapter setup.
  - `ProtocolMessage` for PGN payload + metadata before CAN frame expansion.
- **ctypes bindings**:
  - `CAN_OBJ` and `INIT_CONFIG` map the DLL C-structures.
  - `USBCANDevice` wraps DLL function signatures and open/close/transmit operations.
- **Protocol helpers**:
  - CAN ID assembly (`nmea2000_id`).
  - scaling/packing helpers (`clamp_u16`, `le_u16`).
  - payload builders for key PGNs.
  - fast-packet splitter for payloads larger than 8 bytes.
- **GUI controller (`SimulatorApp`)**:
  - builds the UI,
  - parses user inputs safely,
  - composes enabled messages,
  - expands them into CAN frames,
  - and handles periodic scheduling with Tkinter `after` callbacks.

### About comments in the code
The current comments mostly document:
- **protocol scaling rules** (e.g., physical unit per bit for engine PGNs),
- **field bit/byte layout** for packed payloads,
- **simplifications** made versus full standard behavior (for example in command group function payloads and product information handling).

This style is deliberate: comments are focused on non-obvious protocol details rather than repeating what the Python syntax already says.

---

## Limitations / caveats

- Not a full standards-conformance test suite for all NMEA 2000 PGNs.
- Product info and group-function handling are simplified for simulation practicality.
- The full engine simulator is transmit-focused; the standalone 8-switch simulator also receives PGN 127501 to update its button labels.
- Requires Windows because of direct DLL loading via `ctypes.WinDLL`.

---

## Quick troubleshooting

- **"Unsupported OS" error**: run on Windows.
- **Connection error on Connect**:
  - verify DLL path,
  - verify adapter/driver installation,
  - verify device index/CAN channel assumptions for your hardware.
- **No traffic seen on bus**:
  - confirm 250 kbps bus speed,
  - confirm physical CAN wiring/termination,
  - verify message checkboxes are enabled and source address is valid.
