#!/usr/bin/env python3
"""
Boat data simulator that mimics a Tohatsu outboard connected to the
wellenvogel esp32-nmea2000 WiFi gateway
(https://github.com/wellenvogel/esp32-nmea2000).

The Tohatsu speaks NMEA 2000 natively.  The gateway can re-emit those PGNs
as `$PCDIN` sentences (N2K-over-0183: the raw NMEA 2000 binary payload
hex-encoded inside an NMEA 0183 frame).  Signal K's NMEA 0183 pipeline
auto-detects `$PCDIN`/`$MXPGN` and routes them through canboatjs for full
PGN decoding (see signalk-server's `@signalk/streams/nmea0183-signalk.js`,
function `isN2KOver0183`).

PGNs simulated
  127488  Engine Parameters, Rapid Update  (RPM, trim)
  127489  Engine Parameters, Dynamic       (coolant, oil, voltage, fuel rate, hours)
  127505  Fluid Level                      (fuel tank)
  127508  Battery Status                   (house/start battery voltage)
  128267  Water Depth
  129025  Position, Rapid Update
  129026  COG & SOG, Rapid Update

Configure Signal K -> Server -> Connections:
  Type:    NMEA 0183
  Source:  TCP
  Host:    127.0.0.1
  Port:    10111  (or --port value you chose)

Signal K connects out to this process, so secure mode / token auth is not
in the path of the gateway data.
"""
import asyncio
import math
import struct
import argparse

TCP_HOST = "0.0.0.0"
TCP_PORT = 10111
N2K_SRC = 23  # arbitrary source-address byte to identify our virtual gateway


# ─── N2K binary PGN encoders ────────────────────────────────────────────────
# All multi-byte fields are little-endian. Resolutions and N/A sentinels match
# the canboat PGN definitions consumed by signalk-server -> canboatjs.

def pgn_127488(rpm: float, trim_pct: float, instance: int = 0) -> bytes:
    """Engine Parameters, Rapid Update — 8 bytes."""
    return struct.pack(
        "<BHHbBB",
        instance,
        int(round(rpm * 4)) & 0xFFFF,                       # 0.25 RPM
        0xFFFF,                                             # boost pressure: N/A
        max(-128, min(127, int(round(trim_pct)))),          # int8 %
        0xFF, 0xFF,                                         # reserved
    )


def pgn_127489(coolant_k: float, voltage: float, fuel_lph: float,
               hours_s: float, oil_pa: float, oil_k: float,
               instance: int = 0) -> bytes:
    """Engine Parameters, Dynamic — 26 bytes (multi-frame, sent coalesced)."""
    return struct.pack(
        "<BHHHhhIHHBHHbb",
        instance,
        int(round(oil_pa / 100)) & 0xFFFF,                  # uint16 hPa
        int(round(oil_k * 10)) & 0xFFFF,                    # uint16 0.1 K
        int(round(coolant_k * 100)) & 0xFFFF,               # uint16 0.01 K
        max(-32768, min(32767, int(round(voltage * 100)))), # int16 0.01 V
        max(-32768, min(32767, int(round(fuel_lph * 10)))), # int16 0.1 L/h
        int(round(hours_s)) & 0xFFFFFFFF,                   # uint32 s
        0xFFFF, 0xFFFF,                                     # coolant/fuel pressure N/A
        0xFF,                                               # reserved
        0x0000, 0x0000,                                     # discrete status 1/2
        0x7F, 0x7F,                                         # load/torque N/A
    )


def pgn_127505(level_pct: float, capacity_l: float,
               instance: int = 0, fluid_type: int = 0) -> bytes:
    """Fluid Level — 8 bytes. fluid_type 0=Fuel."""
    type_inst = ((fluid_type & 0x0F) << 4) | (instance & 0x0F)
    return struct.pack(
        "<BhIB",
        type_inst,
        max(-32768, min(32767, int(round(level_pct * 250)))),  # int16 0.004 %
        int(round(capacity_l * 10)) & 0xFFFFFFFF,              # uint32 0.1 L
        0xFF,                                                  # reserved
    )


def pgn_127508(voltage: float, instance: int = 0) -> bytes:
    """Battery Status — 8 bytes."""
    return struct.pack(
        "<BhhHB",
        instance,
        max(-32768, min(32767, int(round(voltage * 100)))),  # int16 0.01 V
        0x7FFF,                                              # current N/A
        0xFFFF,                                              # temp N/A
        0xFF,                                                # SID
    )


def pgn_128267(depth_m: float) -> bytes:
    """Water Depth — 8 bytes."""
    return struct.pack(
        "<BIhB",
        0xFF,                                            # SID
        int(round(depth_m * 100)) & 0xFFFFFFFF,          # uint32 0.01 m
        0,                                               # offset 0.001 m
        0xFF,                                            # range N/A
    )


def pgn_129025(lat_deg: float, lon_deg: float) -> bytes:
    """Position, Rapid Update — 8 bytes."""
    return struct.pack(
        "<ii",
        int(round(lat_deg * 1e7)),
        int(round(lon_deg * 1e7)),
    )


def pgn_129026(cog_rad: float, sog_ms: float) -> bytes:
    """COG & SOG, Rapid Update — 8 bytes."""
    # byte 1: bits 0-1 = COG reference (0=True), bits 2-7 = reserved (1s).
    cog_ref = 0xFC
    return struct.pack(
        "<BBHHH",
        0xFF,                                              # SID
        cog_ref,
        int(round(cog_rad * 10000)) & 0xFFFF,              # uint16 0.0001 rad
        max(0, min(0xFFFF, int(round(sog_ms * 100)))),     # uint16 0.01 m/s
        0xFFFF,                                            # reserved
    )


# ─── PCDIN sentence framing ─────────────────────────────────────────────────

def encode_pcdin(pgn: int, data: bytes, src: int = N2K_SRC) -> str:
    """Wrap a raw N2K PGN payload as a `$PCDIN,<pgn>,<time>,<src>,<hex>*CC` line.

    The time field is parsed by canboatjs as base-32 → seconds-since-2010, so
    the literal `00000000` decodes to t=0 (canboatjs replaces it with the
    receive timestamp anyway).
    """
    body = f"PCDIN,{pgn:06X},00000000,{src:02X},{data.hex().upper()}"
    cs = 0
    for c in body:
        cs ^= ord(c)
    return f"${body}*{cs:02X}\r\n"


# ─── Simulator ──────────────────────────────────────────────────────────────

class BoatSim:
    def __init__(self, scenario="cruise"):
        self.scenario = scenario
        self.t = 0
        self.fuel_remaining_l = 25.0
        self.tank_capacity_l = 25.0
        self.engine_hours = 137.5
        self.lat = 60.1234
        self.lon = 24.4321
        self.heading_deg = 90.0
        self.hz = 1
        self.clients: set[asyncio.StreamWriter] = set()

    def step(self) -> dict:
        if self.scenario == "idle":
            rpm = 850 + 30 * math.sin(self.t / 5)
        elif self.scenario == "cruise":
            phase = (self.t % 300) / 300
            if phase < 0.1:
                rpm = 900 + 100 * phase * 10
            elif phase < 0.3:
                rpm = 1000 + (phase - 0.1) * 25000
            else:
                rpm = 5500 + 200 * math.sin(self.t / 30)
        elif self.scenario == "wot":
            rpm = 6100 + 50 * math.sin(self.t / 10)
        else:
            rpm = 1000

        fuel_rate_lph = 0.04 + 0.000000035 * (rpm ** 2.7)
        coolant_c = min(75.0, 18.0 + self.t * 0.18)
        trim_pct = 35 + 10 * math.sin(self.t / 60)
        voltage = 14.2 if rpm > 800 else 12.6

        self.fuel_remaining_l = max(0, self.fuel_remaining_l - fuel_rate_lph / 3600.0)

        sog_knots = max(0, (rpm - 1200) / 250)
        sog_ms = sog_knots * 0.5144

        self.lat += (sog_ms * math.cos(math.radians(self.heading_deg))) / 111000
        self.lon += (sog_ms * math.sin(math.radians(self.heading_deg))) / (
            111000 * math.cos(math.radians(self.lat))
        )
        self.heading_deg = (self.heading_deg + 0.3 * math.sin(self.t / 120)) % 360

        if rpm > 800:
            self.engine_hours += 1.0 / 3600.0

        depth_m = 8.0 + 5.0 * math.sin(self.t / 45)

        return {
            "rpm": rpm,
            "fuel_rate_lph": fuel_rate_lph,
            "coolant_c": coolant_c,
            "trim_pct": trim_pct,
            "voltage": voltage,
            "sog_knots": sog_knots,
            "sog_ms": sog_ms,
            "depth_m": depth_m,
        }

    def make_sentences(self, s: dict) -> list[str]:
        return [
            encode_pcdin(127488, pgn_127488(s["rpm"], s["trim_pct"])),
            encode_pcdin(127489, pgn_127489(
                coolant_k=s["coolant_c"] + 273.15,
                voltage=s["voltage"],
                fuel_lph=s["fuel_rate_lph"],
                hours_s=self.engine_hours * 3600,
                oil_pa=300_000,           # ~3 bar typical idle
                oil_k=80 + 273.15,
            )),
            encode_pcdin(127505, pgn_127505(
                level_pct=self.fuel_remaining_l / self.tank_capacity_l * 100,
                capacity_l=self.tank_capacity_l,
            )),
            encode_pcdin(127508, pgn_127508(s["voltage"])),
            encode_pcdin(128267, pgn_128267(s["depth_m"])),
            encode_pcdin(129025, pgn_129025(self.lat, self.lon)),
            encode_pcdin(129026, pgn_129026(math.radians(self.heading_deg), s["sog_ms"])),
        ]

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info("peername")
        self.clients.add(writer)
        print(f"[gateway] client connected from {addr}")
        try:
            while not reader.at_eof():
                await reader.read(64)
        except (ConnectionError, OSError):
            pass
        finally:
            self.clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            print(f"[gateway] client disconnected {addr}")

    async def broadcast(self, payload: bytes):
        dead = []
        for w in list(self.clients):
            try:
                w.write(payload)
                await w.drain()
            except (ConnectionError, OSError):
                dead.append(w)
        for w in dead:
            self.clients.discard(w)

    async def run(self):
        print(f"Tohatsu/esp32-nmea2000 N2K gateway sim [{self.scenario}]")
        server = await asyncio.start_server(self.handle_client, TCP_HOST, TCP_PORT)
        addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
        print(f"[gateway] PCDIN (N2K-over-0183) TCP server on {addrs}")

        async with server:
            try:
                while True:
                    s = self.step()
                    payload = "".join(self.make_sentences(s)).encode("ascii")
                    await self.broadcast(payload)
                    if self.t % 10 == 0:
                        print(
                            f"  t={self.t}s  clients={len(self.clients)}"
                            f"  rpm={s['rpm']:.0f}  sog={s['sog_knots']:.1f}kn"
                            f"  fuel={self.fuel_remaining_l:.1f}L"
                            f"  hours={self.engine_hours:.2f}"
                        )
                    self.t += 1
                    await asyncio.sleep(1 / self.hz)
            except (KeyboardInterrupt, asyncio.CancelledError):
                print(f"\n[gateway] stopped at t={self.t}s.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="cruise", choices=["idle", "cruise", "wot"])
    parser.add_argument("--host", default=TCP_HOST)
    parser.add_argument("--port", type=int, default=TCP_PORT)
    args = parser.parse_args()
    TCP_HOST, TCP_PORT = args.host, args.port
    try:
        asyncio.run(BoatSim(args.scenario).run())
    except KeyboardInterrupt:
        pass
