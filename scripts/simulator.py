"""Serve a tests/test_data fixture as a SunSpec device over Modbus TCP that keeps writes."""

import asyncio
import struct
import sys

from sunspec2.file.client import FileClientDevice

PORT = 5020
BASE_ADDR = 40000
READ_HOLDING, READ_INPUT = 3, 4
WRITE_SINGLE, WRITE_MULTIPLE = 6, 16
ILLEGAL_FUNCTION, ILLEGAL_ADDRESS = 1, 2


def load_registers(path):
    device = FileClientDevice(path)
    device.scan()
    return bytearray(b"SunS" + device.get_mb() + b"\xff\xff\x00\x00")


def respond(pdu, registers):
    func = pdu[0]
    if func in (READ_HOLDING, READ_INPUT, WRITE_MULTIPLE):
        addr, count = struct.unpack(">HH", pdu[1:5])
    elif func == WRITE_SINGLE:
        addr, count = struct.unpack(">H", pdu[1:3])[0], 1
    else:
        return bytes([func | 0x80, ILLEGAL_FUNCTION])
    start = (addr - BASE_ADDR) * 2
    end = start + count * 2
    if start < 0 or end > len(registers):
        return bytes([func | 0x80, ILLEGAL_ADDRESS])
    if func == WRITE_SINGLE:
        registers[start:end] = pdu[3:5]
    elif func == WRITE_MULTIPLE:
        registers[start:end] = pdu[6 : 6 + count * 2]
    else:
        return bytes([func, count * 2]) + registers[start:end]
    # A write answers with its function, address and value or count.
    return pdu[:5]


async def handle(reader, writer, registers):
    try:
        while True:
            tid, pid, length, unit = struct.unpack(">HHHB", await reader.readexactly(7))
            pdu = respond(await reader.readexactly(length - 1), registers)
            writer.write(struct.pack(">HHHB", tid, pid, len(pdu) + 1, unit) + pdu)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()


async def main(path):
    registers = load_registers(path)
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, registers), "127.0.0.1", PORT
    )
    print(f"Serving {path} on 127.0.0.1:{PORT}", flush=True)
    await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(
        main(sys.argv[1] if len(sys.argv) > 1 else "tests/test_data/inverter.json")
    )
