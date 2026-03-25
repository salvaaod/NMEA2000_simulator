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

### 1) Start the program
From the repository directory:

```bash
python nmea2000_simulator.py
```

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
Use the **Enabled messages** checkboxes to include/exclude PGNs, including:
- ISO Address Claim (60928)
- ISO Request (59904)
- Product Info (126996)
- Heartbeat (126993)
- Engine Rapid (127488)
- Engine Dynamic (127489)
- Binary Switch Bank Status (127501)
- plus second-node variants for address claim/product/heartbeat

### 5) Send data
- **Send Once**: transmit one burst of currently enabled messages.
- **Start Periodic**: keep transmitting at **Interval ms**.
- **Stop Periodic**: stop scheduled periodic transmission.
- **Disconnect**: close the CAN device.

### 6) Use virtual switch buttons
In **Binary Switch Bank (1-12 pushbuttons)**:
- Pressing/releasing a switch button updates internal switch state.
- Each press/release sends a simplified **PGN 126208 Command Group Function** control frame.
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
- No receive/decode path in this tool: it is transmit-focused.
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
