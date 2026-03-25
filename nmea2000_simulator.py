import ctypes
import os
import platform
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

USBCAN_II = 4
DEFAULT_DEVICE_TYPE = USBCAN_II
DEFAULT_DEVICE_INDEX = 0
DEFAULT_CAN_INDEX = 0
DEFAULT_DLL_NAME = "ECanVci.dll"
TIMING0_250K = 0x01
TIMING1_250K = 0x1C

# Core NMEA2000 / ISO11783 PGNs used by this simulator.
PGN_ISO_REQUEST = 59904
PGN_ADDRESS_CLAIM = 60928
PGN_PRODUCT_INFO = 126996
PGN_HEARTBEAT = 126993
PGN_ENGINE_RAPID = 127488
PGN_ENGINE_DYNAMIC = 127489

GLOBAL_DESTINATION = 0xFF
DEFAULT_PRIORITY = 6


@dataclass
class DeviceConfig:
    dll_path: str
    device_type: int
    device_index: int
    can_index: int
    timing0: int
    timing1: int


@dataclass
class ProtocolMessage:
    pgn: int
    data: bytes
    priority: int = DEFAULT_PRIORITY
    destination: int = GLOBAL_DESTINATION


class CAN_OBJ(ctypes.Structure):
    _fields_ = [
        ("ID", ctypes.c_uint),
        ("TimeStamp", ctypes.c_uint),
        ("TimeFlag", ctypes.c_ubyte),
        ("SendType", ctypes.c_ubyte),
        ("RemoteFlag", ctypes.c_ubyte),
        ("ExternFlag", ctypes.c_ubyte),
        ("DataLen", ctypes.c_ubyte),
        ("Data", ctypes.c_ubyte * 8),
        ("Reserved", ctypes.c_ubyte * 3),
    ]


class INIT_CONFIG(ctypes.Structure):
    _fields_ = [
        ("AccCode", ctypes.c_uint),
        ("AccMask", ctypes.c_uint),
        ("Reserved", ctypes.c_uint),
        ("Filter", ctypes.c_ubyte),
        ("Timing0", ctypes.c_ubyte),
        ("Timing1", ctypes.c_ubyte),
        ("Mode", ctypes.c_ubyte),
    ]


class USBCANDevice:
    def __init__(self, config: DeviceConfig) -> None:
        self.config = config
        self.dll = ctypes.WinDLL(config.dll_path)
        self._bind_functions()

    def _bind_functions(self) -> None:
        self.dll.OpenDevice.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        self.dll.OpenDevice.restype = ctypes.c_uint
        self.dll.CloseDevice.argtypes = [ctypes.c_uint, ctypes.c_uint]
        self.dll.CloseDevice.restype = ctypes.c_uint
        self.dll.InitCAN.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(INIT_CONFIG)]
        self.dll.InitCAN.restype = ctypes.c_uint
        self.dll.StartCAN.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        self.dll.StartCAN.restype = ctypes.c_uint
        self.dll.Transmit.argtypes = [
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(CAN_OBJ),
            ctypes.c_ulong,
        ]
        self.dll.Transmit.restype = ctypes.c_ulong

    def open(self) -> None:
        result = self.dll.OpenDevice(self.config.device_type, self.config.device_index, 0)
        if result == 0:
            raise RuntimeError("OpenDevice failed.")
        init_config = INIT_CONFIG(
            AccCode=0,
            AccMask=0xFFFFFFFF,
            Reserved=0,
            Filter=0,
            Timing0=self.config.timing0,
            Timing1=self.config.timing1,
            Mode=0,
        )
        if self.dll.InitCAN(
            self.config.device_type,
            self.config.device_index,
            self.config.can_index,
            ctypes.byref(init_config),
        ) == 0:
            raise RuntimeError("InitCAN failed.")
        if self.dll.StartCAN(self.config.device_type, self.config.device_index, self.config.can_index) == 0:
            raise RuntimeError("StartCAN failed.")

    def close(self) -> None:
        self.dll.CloseDevice(self.config.device_type, self.config.device_index)

    def send(self, frame_id: int, data: bytes) -> int:
        can_obj = CAN_OBJ()
        can_obj.ID = frame_id
        can_obj.TimeStamp = 0
        can_obj.TimeFlag = 0
        can_obj.SendType = 0
        can_obj.RemoteFlag = 0
        can_obj.ExternFlag = 1
        can_obj.DataLen = len(data)
        for index, value in enumerate(data):
            can_obj.Data[index] = value
        return int(
            self.dll.Transmit(
                self.config.device_type,
                self.config.device_index,
                self.config.can_index,
                ctypes.byref(can_obj),
                1,
            )
        )


def nmea2000_id(priority: int, pgn: int, source_address: int, destination: int = GLOBAL_DESTINATION) -> int:
    pf = (pgn >> 8) & 0xFF
    if pf < 240:
        pgn_field = pgn & 0x3FF00
        ps = destination & 0xFF
    else:
        pgn_field = pgn & 0x3FFFF
        ps = pgn & 0xFF
    return (
        ((priority & 0x7) << 26)
        | ((pgn_field & 0x3FF00) << 8)
        | ((pf & 0xFF) << 16)
        | ((ps & 0xFF) << 8)
        | (source_address & 0xFF)
    )


def clamp_u16(value: float, scale: float, minimum: float = 0.0, maximum: float = 65535.0) -> int:
    scaled = int(round(value / scale))
    return max(int(minimum), min(int(maximum), scaled))


def le_u16(value: int) -> bytes:
    return bytes((value & 0xFF, (value >> 8) & 0xFF))


def build_address_claim(name: int) -> bytes:
    return name.to_bytes(8, byteorder="little", signed=False)


def build_iso_request(requested_pgn: int) -> bytes:
    return bytes((requested_pgn & 0xFF, (requested_pgn >> 8) & 0xFF, (requested_pgn >> 16) & 0xFF)) + bytes((0xFF,) * 5)


def build_engine_rapid(engine_instance: int, engine_speed_rpm: float, engine_boost_kpa: float, trim_percent: float) -> bytes:
    speed_raw = clamp_u16(engine_speed_rpm, 0.25)
    boost_raw = max(0, min(250, int(round(engine_boost_kpa))))
    trim_raw = max(0, min(250, int(round(trim_percent / 0.4))))
    return bytes(
        (
            engine_instance & 0xFF,
            boost_raw,
            0xFF,
            speed_raw & 0xFF,
            (speed_raw >> 8) & 0xFF,
            trim_raw,
            0xFF,
            0xFF,
        )
    )


def build_engine_dynamic(
    engine_instance: int,
    oil_pressure_kpa: float,
    oil_temp_c: float,
    coolant_temp_c: float,
    alternator_voltage_v: float,
    fuel_rate_lph: float,
    total_engine_hours_h: float,
    coolant_pressure_kpa: float,
    fuel_pressure_kpa: float,
    engine_load_percent: float,
    engine_torque_percent: float,
) -> bytes:
    oil_p_raw = clamp_u16(oil_pressure_kpa, 1.0)
    oil_t_raw = clamp_u16(oil_temp_c + 273.15, 0.1)
    coolant_t_raw = clamp_u16(coolant_temp_c + 273.15, 0.1)
    alt_v_raw = clamp_u16(alternator_voltage_v, 0.01)
    fuel_rate_raw = clamp_u16(fuel_rate_lph, 0.1)
    hours_raw = max(0, min(0xFFFFFFFF, int(round(total_engine_hours_h))))
    coolant_p_raw = clamp_u16(coolant_pressure_kpa, 1.0)
    fuel_p_raw = clamp_u16(fuel_pressure_kpa, 1.0)
    load_raw = max(0, min(250, int(round(engine_load_percent / 0.4))))
    torque_raw = max(0, min(250, int(round(engine_torque_percent / 0.4))))

    data = bytearray()
    data.extend((engine_instance & 0xFF,))
    data.extend(le_u16(oil_p_raw))
    data.extend(le_u16(oil_t_raw))
    data.extend(le_u16(coolant_t_raw))
    data.extend(le_u16(alt_v_raw))
    data.extend(le_u16(fuel_rate_raw))
    data.extend(hours_raw.to_bytes(4, byteorder="little", signed=False))
    data.extend(le_u16(coolant_p_raw))
    data.extend(le_u16(fuel_p_raw))
    data.extend((load_raw, torque_raw, 0xFF, 0xFF))
    return bytes(data)


def build_product_info_payload(model_id: str, software_version: str, serial_code: str) -> bytes:
    # Simplified NMEA2000 Product Information payload (fast packet).
    model = model_id[:32].ljust(32, "\x00").encode("ascii", errors="ignore")
    software = software_version[:32].ljust(32, "\x00").encode("ascii", errors="ignore")
    serial = serial_code[:32].ljust(32, "\x00").encode("ascii", errors="ignore")
    n2k_version = (2100).to_bytes(2, byteorder="little")
    product_code = (1001).to_bytes(2, byteorder="little")
    cert_level = bytes((1,))
    load_equivalency = bytes((1,))
    return n2k_version + product_code + model + software + serial + cert_level + load_equivalency


def split_fast_packet(payload: bytes, sequence_id: int) -> list[bytes]:
    if len(payload) <= 8:
        return [payload]
    sid = sequence_id & 0x07
    frame_index = 0
    cursor = 0
    frames: list[bytes] = []

    first_room = 6
    first_chunk = payload[cursor : cursor + first_room]
    cursor += len(first_chunk)
    first_frame = bytes(((sid << 5) | frame_index, len(payload))) + first_chunk
    frames.append(first_frame)
    frame_index += 1

    while cursor < len(payload):
        chunk = payload[cursor : cursor + 7]
        cursor += len(chunk)
        frame = bytes((((sid << 5) | frame_index),)) + chunk
        frames.append(frame)
        frame_index += 1
    return frames


class SimulatorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("NMEA2000 Engine Simulator (USB GCAN)")
        self.device: USBCANDevice | None = None
        self.send_job: str | None = None
        self.is_connected = False
        self.fast_packet_sequence = 0
        self._build_ui()

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=10)
        main.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)

        self.status_text = tk.StringVar(value="Status: Disconnected")
        ttk.Label(main, textvariable=self.status_text).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        ttk.Label(main, text="DLL path").grid(row=1, column=0, sticky="w")
        self.dll_path = tk.StringVar(value=DEFAULT_DLL_NAME)
        ttk.Entry(main, textvariable=self.dll_path).grid(row=1, column=1, columnspan=3, sticky="ew")

        ttk.Label(main, text="Source address").grid(row=2, column=0, sticky="w")
        self.source_address = tk.StringVar(value="0")
        ttk.Entry(main, textvariable=self.source_address).grid(row=2, column=1, sticky="ew")

        ttk.Label(main, text="Destination").grid(row=2, column=2, sticky="w")
        self.destination_address = tk.StringVar(value="255")
        ttk.Entry(main, textvariable=self.destination_address).grid(row=2, column=3, sticky="ew")

        ttk.Label(main, text="Engine instance").grid(row=3, column=0, sticky="w")
        self.engine_instance = tk.StringVar(value="0")
        ttk.Entry(main, textvariable=self.engine_instance).grid(row=3, column=1, sticky="ew")

        ttk.Label(main, text="Device NAME (hex)").grid(row=3, column=2, sticky="w")
        self.device_name = tk.StringVar(value="0x1F2000123456789A")
        ttk.Entry(main, textvariable=self.device_name).grid(row=3, column=3, sticky="ew")

        row = 4
        self.engine_speed_rpm = self._add_field(main, row, "Engine speed rpm", "750")
        self.engine_boost_kpa = self._add_field(main, row, "Boost pressure kPa", "100", col=2)
        row += 1
        self.trim_percent = self._add_field(main, row, "Engine trim %", "0")
        self.oil_pressure_kpa = self._add_field(main, row, "Oil pressure kPa", "350", col=2)
        row += 1
        self.oil_temp_c = self._add_field(main, row, "Oil temp °C", "85")
        self.coolant_temp_c = self._add_field(main, row, "Coolant temp °C", "78", col=2)
        row += 1
        self.alternator_v = self._add_field(main, row, "Alternator V", "13.8")
        self.fuel_rate_lph = self._add_field(main, row, "Fuel rate L/h", "12", col=2)
        row += 1
        self.engine_hours_h = self._add_field(main, row, "Engine hours", "500")
        self.coolant_pressure_kpa = self._add_field(main, row, "Coolant pressure kPa", "120", col=2)
        row += 1
        self.fuel_pressure_kpa = self._add_field(main, row, "Fuel pressure kPa", "300")
        self.engine_load_percent = self._add_field(main, row, "Engine load %", "35", col=2)
        row += 1
        self.engine_torque_percent = self._add_field(main, row, "Engine torque %", "42")
        self.iso_request_pgn = self._add_field(main, row, "ISO request PGN", str(PGN_ADDRESS_CLAIM), col=2)
        row += 1

        ttk.Label(main, text="Product model").grid(row=row, column=0, sticky="w")
        self.product_model = tk.StringVar(value="GCAN Engine Sim")
        ttk.Entry(main, textvariable=self.product_model).grid(row=row, column=1, sticky="ew")
        ttk.Label(main, text="Software version").grid(row=row, column=2, sticky="w")
        self.software_version = tk.StringVar(value="1.0.0")
        ttk.Entry(main, textvariable=self.software_version).grid(row=row, column=3, sticky="ew")
        row += 1

        ttk.Label(main, text="Serial code").grid(row=row, column=0, sticky="w")
        self.serial_code = tk.StringVar(value="SIM-0001")
        ttk.Entry(main, textvariable=self.serial_code).grid(row=row, column=1, sticky="ew")

        ttk.Label(main, text="Interval ms").grid(row=row, column=2, sticky="w")
        self.interval_ms = tk.IntVar(value=100)
        ttk.Entry(main, textvariable=self.interval_ms).grid(row=row, column=3, sticky="ew")
        row += 1

        enabled = ttk.LabelFrame(main, text="Enabled messages", padding=8)
        enabled.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(8, 6))
        self.address_claim_enabled = tk.BooleanVar(value=True)
        self.iso_request_enabled = tk.BooleanVar(value=True)
        self.product_info_enabled = tk.BooleanVar(value=True)
        self.heartbeat_enabled = tk.BooleanVar(value=True)
        self.engine_rapid_enabled = tk.BooleanVar(value=True)
        self.engine_dynamic_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(enabled, text="ISO Address Claim", variable=self.address_claim_enabled).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(enabled, text="ISO Request", variable=self.iso_request_enabled).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(enabled, text="Product Info", variable=self.product_info_enabled).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(enabled, text="Heartbeat", variable=self.heartbeat_enabled).grid(row=1, column=1, sticky="w")
        ttk.Checkbutton(enabled, text="Engine Rapid PGN 127488", variable=self.engine_rapid_enabled).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(enabled, text="Engine Dynamic PGN 127489", variable=self.engine_dynamic_enabled).grid(row=2, column=1, sticky="w")
        row += 1

        ttk.Label(main, text="Preview (next frames)").grid(row=row, column=0, sticky="w")
        self.preview_text = tk.StringVar(value="")
        ttk.Label(main, textvariable=self.preview_text, justify="left").grid(row=row, column=1, columnspan=3, sticky="w")
        row += 1

        buttons = ttk.Frame(main)
        buttons.grid(row=row, column=0, columnspan=4, pady=8, sticky="ew")
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
        self.refresh_preview()

    def _add_field(self, parent: ttk.Frame, row: int, label: str, default: str, col: int = 0) -> tk.StringVar:
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w")
        value = tk.StringVar(value=default)
        ttk.Entry(parent, textvariable=value).grid(row=row, column=col + 1, sticky="ew")
        return value

    def _as_int(self, value: str, default: int = 0) -> int:
        try:
            if value.strip().lower().startswith("0x"):
                return int(value.strip(), 16)
            return int(float(value.strip()))
        except ValueError:
            return default

    def _as_float(self, value: str, default: float = 0.0) -> float:
        try:
            return float(value.strip())
        except ValueError:
            return default

    def _source_address(self) -> int:
        return max(0, min(253, self._as_int(self.source_address.get(), 0)))

    def _destination(self) -> int:
        return max(0, min(255, self._as_int(self.destination_address.get(), 255)))

    def _device_name(self) -> int:
        value = self.device_name.get().strip()
        try:
            return int(value, 16) if value.lower().startswith("0x") else int(value)
        except ValueError:
            return 0x1F2000123456789A

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
        source = self._source_address()
        if len(message.data) <= 8:
            frame_id = nmea2000_id(message.priority, message.pgn, source, message.destination)
            return [(frame_id, message.data)]

        frames = split_fast_packet(message.data, self.fast_packet_sequence)
        self.fast_packet_sequence = (self.fast_packet_sequence + 1) & 0x07
        frame_id = nmea2000_id(message.priority, message.pgn, source, message.destination)
        return [(frame_id, frame.ljust(8, b"\xFF")) for frame in frames]

    def current_messages(self) -> list[ProtocolMessage]:
        destination = self._destination()
        engine_instance = max(0, min(255, self._as_int(self.engine_instance.get(), 0)))

        messages: list[ProtocolMessage] = []
        if self.address_claim_enabled.get():
            messages.append(ProtocolMessage(PGN_ADDRESS_CLAIM, build_address_claim(self._device_name()), 6, GLOBAL_DESTINATION))
        if self.iso_request_enabled.get():
            request_pgn = max(0, min(0x3FFFF, self._as_int(self.iso_request_pgn.get(), PGN_ADDRESS_CLAIM)))
            messages.append(ProtocolMessage(PGN_ISO_REQUEST, build_iso_request(request_pgn), 6, destination))
        if self.product_info_enabled.get():
            payload = build_product_info_payload(self.product_model.get(), self.software_version.get(), self.serial_code.get())
            messages.append(ProtocolMessage(PGN_PRODUCT_INFO, payload, 6, GLOBAL_DESTINATION))
        if self.heartbeat_enabled.get():
            messages.append(ProtocolMessage(PGN_HEARTBEAT, bytes((engine_instance, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF)), 7, GLOBAL_DESTINATION))
        if self.engine_rapid_enabled.get():
            messages.append(
                ProtocolMessage(
                    PGN_ENGINE_RAPID,
                    build_engine_rapid(
                        engine_instance,
                        self._as_float(self.engine_speed_rpm.get(), 0.0),
                        self._as_float(self.engine_boost_kpa.get(), 100.0),
                        self._as_float(self.trim_percent.get(), 0.0),
                    ),
                    2,
                    GLOBAL_DESTINATION,
                )
            )
        if self.engine_dynamic_enabled.get():
            messages.append(
                ProtocolMessage(
                    PGN_ENGINE_DYNAMIC,
                    build_engine_dynamic(
                        engine_instance,
                        self._as_float(self.oil_pressure_kpa.get(), 0.0),
                        self._as_float(self.oil_temp_c.get(), 0.0),
                        self._as_float(self.coolant_temp_c.get(), 0.0),
                        self._as_float(self.alternator_v.get(), 0.0),
                        self._as_float(self.fuel_rate_lph.get(), 0.0),
                        self._as_float(self.engine_hours_h.get(), 0.0),
                        self._as_float(self.coolant_pressure_kpa.get(), 0.0),
                        self._as_float(self.fuel_pressure_kpa.get(), 0.0),
                        self._as_float(self.engine_load_percent.get(), 0.0),
                        self._as_float(self.engine_torque_percent.get(), 0.0),
                    ),
                    2,
                    GLOBAL_DESTINATION,
                )
            )
        return messages

    def current_frames(self) -> list[tuple[int, bytes]]:
        frames: list[tuple[int, bytes]] = []
        for message in self.current_messages():
            frames.extend(self._expand_protocol_message(message))
        return frames

    def refresh_preview(self) -> None:
        lines = []
        for idx, (frame_id, data) in enumerate(self.current_frames()[:8], start=1):
            lines.append(f"{idx}. 0x{frame_id:08X} / {' '.join(f'{b:02X}' for b in data)}")
        if not lines:
            lines.append("No messages enabled")
        self.preview_text.set("\n".join(lines))
        self.root.after(250, self.refresh_preview)

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
    SimulatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
