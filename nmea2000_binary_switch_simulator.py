import os
import platform
import tkinter as tk
from tkinter import messagebox, ttk

from nmea2000_simulator import (
    DEFAULT_CAN_INDEX,
    DEFAULT_DEVICE_INDEX,
    DEFAULT_DEVICE_TYPE,
    DEFAULT_DLL_NAME,
    DEFAULT_PRIORITY,
    GLOBAL_DESTINATION,
    PGN_ADDRESS_CLAIM,
    PGN_BINARY_SWITCH_BANK_STATUS,
    PGN_GROUP_FUNCTION,
    PGN_HEARTBEAT,
    PGN_PRODUCT_INFO,
    TIMING0_250K,
    TIMING1_250K,
    DeviceConfig,
    ProtocolMessage,
    USBCANDevice,
    build_address_claim,
    build_binary_switch_bank_status,
    build_group_function_binary_switch_command,
    build_heartbeat_payload,
    nmea2000_id,
    set_name_manufacturer_code,
    split_fast_packet,
)

SWITCH_COUNT = 8
DEFAULT_SWITCH_SOURCE_ADDRESS = 55
DEFAULT_SWITCH_BANK_INSTANCE = 1
DEFAULT_SWITCH_DEVICE_NAME = 0x1F2000AA12345678
DEFAULT_MANUFACTURER_CODE = 176
DEFAULT_PRODUCT_NAME = "Azimut Switch"
DEFAULT_APPLICATION_VERSION = "0.1"
DEFAULT_DATABASE_VERSION = 2000
DEFAULT_MODEL_VERSION = "SW1"
DEFAULT_PRODUCT_CODE = "AZM_SW_SF"
DEFAULT_PRODUCT_ID = "AZ_SW"


def _ascii_field(value: str, length: int = 32) -> bytes:
    return value[:length].ljust(length, "\x00").encode("ascii", errors="ignore")


def build_switch_product_info_payload(
    product_name: str,
    application_version: str,
    database_version: int,
    model_version: str,
    product_code: str,
    product_id: str,
) -> bytes:
    # Simplified product information payload for the switch-only simulator.
    # The first two bytes keep the existing NMEA database/version position;
    # the following ASCII fields carry Azimut's requested product identity.
    database = int(max(0, min(0xFFFF, database_version))).to_bytes(2, byteorder="little", signed=False)
    return (
        database
        + _ascii_field(product_code)
        + _ascii_field(product_name)
        + _ascii_field(application_version)
        + _ascii_field(model_version)
        + _ascii_field(product_id)
        + bytes((1, 1))
    )


class BinarySwitchSimulatorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("NMEA2000 Binary Switch Simulator (8 switches)")
        self.device: USBCANDevice | None = None
        self.send_job: str | None = None
        self.is_connected = False
        self.fast_packet_sequence = 0
        self.heartbeat_sequence = 0
        self.switch_states = [False] * SWITCH_COUNT
        self.switch_buttons: list[ttk.Button] = []
        self._build_ui()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=10)
        main.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.columnconfigure(3, weight=1)

        self.status_text = tk.StringVar(value="Status: Disconnected")
        ttk.Label(main, textvariable=self.status_text).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        ttk.Label(main, text="DLL path").grid(row=1, column=0, sticky="w")
        self.dll_path = tk.StringVar(value=DEFAULT_DLL_NAME)
        ttk.Entry(main, textvariable=self.dll_path).grid(row=1, column=1, columnspan=3, sticky="ew")

        ttk.Label(main, text="Source address").grid(row=2, column=0, sticky="w")
        self.source_address = tk.StringVar(value=str(DEFAULT_SWITCH_SOURCE_ADDRESS))
        ttk.Entry(main, textvariable=self.source_address, width=10).grid(row=2, column=1, sticky="w")

        ttk.Label(main, text="Destination").grid(row=2, column=2, sticky="w")
        self.destination_address = tk.StringVar(value=str(GLOBAL_DESTINATION))
        ttk.Entry(main, textvariable=self.destination_address, width=10).grid(row=2, column=3, sticky="w")

        ttk.Label(main, text="Device NAME (hex)").grid(row=3, column=0, sticky="w")
        self.device_name = tk.StringVar(value=f"0x{DEFAULT_SWITCH_DEVICE_NAME:016X}")
        ttk.Entry(main, textvariable=self.device_name).grid(row=3, column=1, sticky="ew")

        ttk.Label(main, text="Manufacturer code").grid(row=3, column=2, sticky="w")
        self.manufacturer_code = tk.StringVar(value=str(DEFAULT_MANUFACTURER_CODE))
        ttk.Entry(main, textvariable=self.manufacturer_code, width=10).grid(row=3, column=3, sticky="w")

        ttk.Label(main, text="Bank instance").grid(row=4, column=0, sticky="w")
        self.bank_instance = tk.StringVar(value=str(DEFAULT_SWITCH_BANK_INSTANCE))
        ttk.Entry(main, textvariable=self.bank_instance, width=10).grid(row=4, column=1, sticky="w")

        ttk.Label(main, text="Interval ms").grid(row=4, column=2, sticky="w")
        self.interval_ms = tk.IntVar(value=100)
        ttk.Entry(main, textvariable=self.interval_ms, width=10).grid(row=4, column=3, sticky="w")

        product = ttk.LabelFrame(main, text="Product information", padding=8)
        product.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 6))
        product.columnconfigure(1, weight=1)
        product.columnconfigure(3, weight=1)
        self.product_name = self._add_field(product, 0, "Device/Product name", DEFAULT_PRODUCT_NAME, col=0)
        self.application_version = self._add_field(product, 0, "Application version", DEFAULT_APPLICATION_VERSION, col=2)
        self.database_version = self._add_field(product, 1, "Database version", str(DEFAULT_DATABASE_VERSION), col=0)
        self.model_version = self._add_field(product, 1, "Model version", DEFAULT_MODEL_VERSION, col=2)
        self.product_code = self._add_field(product, 2, "Product code", DEFAULT_PRODUCT_CODE, col=0)
        self.product_id = self._add_field(product, 2, "Product ID", DEFAULT_PRODUCT_ID, col=2)

        enabled = ttk.LabelFrame(main, text="Enabled messages", padding=8)
        enabled.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(4, 6))
        self.address_claim_enabled = tk.BooleanVar(value=True)
        self.product_info_enabled = tk.BooleanVar(value=True)
        self.heartbeat_enabled = tk.BooleanVar(value=True)
        self.binary_switch_status_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(enabled, text="ISO Address Claim (60928)", variable=self.address_claim_enabled).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(enabled, text="Product Info (126996)", variable=self.product_info_enabled).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(enabled, text="Heartbeat (126993)", variable=self.heartbeat_enabled).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(enabled, text="Binary Switch Bank Status (127501)", variable=self.binary_switch_status_enabled).grid(
            row=1, column=1, sticky="w"
        )

        switch_frame = ttk.LabelFrame(main, text="Binary Switch Bank (8 pushbuttons)", padding=8)
        switch_frame.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(4, 6))
        ttk.Label(switch_frame, text="Press/release sends PGN 126208 command and updates PGN 127501 status.").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 4)
        )
        for index in range(SWITCH_COUNT):
            button = ttk.Button(switch_frame, text=f"SW {index + 1}: RELEASED", width=16)
            button.bind("<ButtonPress-1>", lambda _event, switch_no=index + 1: self.on_switch_press(switch_no))
            button.bind("<ButtonRelease-1>", lambda _event, switch_no=index + 1: self.on_switch_release(switch_no))
            button.grid(row=1 + (index // 4), column=index % 4, padx=3, pady=3, sticky="ew")
            self.switch_buttons.append(button)

        buttons = ttk.Frame(main)
        buttons.grid(row=8, column=0, columnspan=4, pady=8, sticky="ew")
        self.connect_button = ttk.Button(buttons, text="Connect", command=self.connect)
        self.connect_button.grid(row=0, column=0, padx=4)
        self.disconnect_button = ttk.Button(buttons, text="Disconnect", command=self.disconnect)
        self.disconnect_button.grid(row=0, column=1, padx=4)
        self.send_once_button = ttk.Button(buttons, text="Send Once", command=self.send_once)
        self.send_once_button.grid(row=0, column=2, padx=4)
        self.start_button = ttk.Button(buttons, text="Start Periodic", command=self.start_periodic)
        self.start_button.grid(row=0, column=3, padx=4)
        self.stop_button = ttk.Button(buttons, text="Stop Periodic", command=self.stop_periodic)
        self.stop_button.grid(row=0, column=4, padx=4)

        self._update_button_states()
        self._refresh_switch_button_labels()

    def _add_field(self, parent: ttk.Frame, row: int, label: str, default: str, col: int = 0) -> tk.StringVar:
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w")
        value = tk.StringVar(value=default)
        ttk.Entry(parent, textvariable=value).grid(row=row, column=col + 1, sticky="ew")
        return value

    def _as_int(self, value: str, default: int = 0) -> int:
        try:
            text = value.strip()
            if text.lower().startswith("0x"):
                return int(text, 16)
            return int(float(text))
        except ValueError:
            return default

    def _source_address(self) -> int:
        return max(0, min(251, self._as_int(self.source_address.get(), DEFAULT_SWITCH_SOURCE_ADDRESS)))

    def _destination(self) -> int:
        return max(0, min(255, self._as_int(self.destination_address.get(), GLOBAL_DESTINATION)))

    def _device_name(self) -> int:
        value = self.device_name.get().strip()
        try:
            name = int(value, 16) if value.lower().startswith("0x") else int(value)
        except ValueError:
            name = DEFAULT_SWITCH_DEVICE_NAME
        manufacturer = self._as_int(self.manufacturer_code.get(), DEFAULT_MANUFACTURER_CODE)
        return set_name_manufacturer_code(name, manufacturer)

    def _bank_instance(self) -> int:
        return max(0, min(255, self._as_int(self.bank_instance.get(), DEFAULT_SWITCH_BANK_INSTANCE)))

    def _refresh_switch_button_labels(self) -> None:
        for index, button in enumerate(self.switch_buttons, start=1):
            state_text = "PRESSED" if self.switch_states[index - 1] else "RELEASED"
            button.configure(text=f"SW {index}: {state_text}")

    def _send_switch_command(self, switch_number: int, state_on: bool) -> None:
        if not self.device:
            return
        payload = build_group_function_binary_switch_command(self._bank_instance(), switch_number, state_on)
        frame_id = nmea2000_id(DEFAULT_PRIORITY, PGN_GROUP_FUNCTION, self._source_address(), self._destination())
        self.device.send(frame_id, payload)

    def on_switch_press(self, switch_number: int) -> None:
        switch_index = max(1, min(SWITCH_COUNT, switch_number)) - 1
        if self.switch_states[switch_index]:
            return
        self.switch_states[switch_index] = True
        self._refresh_switch_button_labels()
        self._send_switch_command(switch_number, True)

    def on_switch_release(self, switch_number: int) -> None:
        switch_index = max(1, min(SWITCH_COUNT, switch_number)) - 1
        if not self.switch_states[switch_index]:
            return
        self.switch_states[switch_index] = False
        self._refresh_switch_button_labels()
        self._send_switch_command(switch_number, False)

    def resolve_dll_path(self) -> str:
        path = self.dll_path.get().strip() or DEFAULT_DLL_NAME
        return os.path.abspath(path)

    def connect(self) -> None:
        if platform.system() != "Windows":
            messagebox.showerror("Unsupported OS", "This simulator requires Windows because it loads ECanVci.dll.")
            return
        try:
            config = DeviceConfig(
                dll_path=self.resolve_dll_path(),
                device_type=DEFAULT_DEVICE_TYPE,
                device_index=DEFAULT_DEVICE_INDEX,
                can_index=DEFAULT_CAN_INDEX,
                timing0=TIMING0_250K,
                timing1=TIMING1_250K,
            )
            self.device = USBCANDevice(config)
            self.device.open()
            self.is_connected = True
            self.status_text.set(f"Status: Connected ({config.dll_path})")
            self.send_once()
        except Exception as exc:
            self.device = None
            self.is_connected = False
            messagebox.showerror("Connection error", str(exc))
        self._update_button_states()

    def disconnect(self) -> None:
        self.stop_periodic()
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
        self.device = None
        self.is_connected = False
        self.status_text.set("Status: Disconnected")
        self._update_button_states()

    def _send_protocol_messages(self) -> None:
        if not self.device:
            return
        for frame_id, data in self.current_frames():
            self.device.send(frame_id, data)

    def send_once(self) -> None:
        self._send_protocol_messages()

    def start_periodic(self) -> None:
        if not self.device or self.send_job is not None:
            return
        self._schedule_send()
        self._update_button_states()

    def stop_periodic(self) -> None:
        if self.send_job is not None:
            self.root.after_cancel(self.send_job)
            self.send_job = None
        self._update_button_states()

    def _schedule_send(self) -> None:
        try:
            interval = max(10, int(self.interval_ms.get()))
        except tk.TclError:
            interval = 100
        self.send_job = self.root.after(interval, self._send_and_reschedule)

    def _send_and_reschedule(self) -> None:
        self._send_protocol_messages()
        self._schedule_send()

    def _expand_protocol_message(self, message: ProtocolMessage) -> list[tuple[int, bytes]]:
        if len(message.data) <= 8:
            frame_id = nmea2000_id(message.priority, message.pgn, self._source_address(), message.destination)
            return [(frame_id, message.data)]

        frames = split_fast_packet(message.data, self.fast_packet_sequence)
        self.fast_packet_sequence = (self.fast_packet_sequence + 1) & 0x07
        frame_id = nmea2000_id(message.priority, message.pgn, self._source_address(), message.destination)
        return [(frame_id, frame.ljust(8, b"\xFF")) for frame in frames]

    def current_messages(self) -> list[ProtocolMessage]:
        messages: list[ProtocolMessage] = []
        if self.address_claim_enabled.get():
            messages.append(ProtocolMessage(PGN_ADDRESS_CLAIM, build_address_claim(self._device_name()), 6, GLOBAL_DESTINATION))
        if self.product_info_enabled.get():
            payload = build_switch_product_info_payload(
                self.product_name.get(),
                self.application_version.get(),
                self._as_int(self.database_version.get(), DEFAULT_DATABASE_VERSION),
                self.model_version.get(),
                self.product_code.get(),
                self.product_id.get(),
            )
            messages.append(ProtocolMessage(PGN_PRODUCT_INFO, payload, 6, GLOBAL_DESTINATION))
        if self.heartbeat_enabled.get():
            heartbeat_interval = max(0, self._as_int(str(self.interval_ms.get()), 100))
            payload = build_heartbeat_payload(heartbeat_interval, self.heartbeat_sequence)
            self.heartbeat_sequence = (self.heartbeat_sequence + 1) & 0xFF
            messages.append(ProtocolMessage(PGN_HEARTBEAT, payload, 7, GLOBAL_DESTINATION))
        if self.binary_switch_status_enabled.get():
            messages.append(
                ProtocolMessage(
                    PGN_BINARY_SWITCH_BANK_STATUS,
                    build_binary_switch_bank_status(self._bank_instance(), self.switch_states),
                    3,
                    GLOBAL_DESTINATION,
                )
            )
        return messages

    def current_frames(self) -> list[tuple[int, bytes]]:
        frames: list[tuple[int, bytes]] = []
        for message in self.current_messages():
            frames.extend(self._expand_protocol_message(message))
        return frames

    def _update_button_states(self) -> None:
        if self.is_connected:
            self.connect_button.state(["disabled"])
            self.disconnect_button.state(["!disabled"])
            self.send_once_button.state(["!disabled"])
            if self.send_job is None:
                self.start_button.state(["!disabled"])
                self.stop_button.state(["disabled"])
            else:
                self.start_button.state(["disabled"])
                self.stop_button.state(["!disabled"])
        else:
            self.connect_button.state(["!disabled"])
            self.disconnect_button.state(["disabled"])
            self.send_once_button.state(["disabled"])
            self.start_button.state(["disabled"])
            self.stop_button.state(["disabled"])


def main() -> None:
    root = tk.Tk()
    BinarySwitchSimulatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
