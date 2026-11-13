"""USB compatibility probe with no layout write operation or automatic pairing.

Only an existing trusted USB connection and getIconState are used. A successful
probe demonstrates reading, never setIconState or lossless restore compatibility.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .model import Layout


def inspect_layout(state: Any) -> dict[str, Any]:
    if not isinstance(state, list) or not state or not all(isinstance(p, list) for p in state):
        raise ValueError("Unsupported getIconState response shape")
    layout = Layout(state)
    kinds = [node.kind for node in layout.nodes.values()]
    return {
        "pages": len(state) - 1,
        "apps_on_home_screen": kinds.count("app"),
        "folders": kinds.count("folder"),
        "widgets": kinds.count("widget"),
        "layout_validation_problems": len(layout.validate()),
        "app_library_exposed": False,
    }


async def probe_lockdown(lockdown, *, expected_version: str | None = None) -> dict[str, Any]:
    if not lockdown.paired:
        raise ValueError("An existing trusted pairing is required; automatic pairing is disabled")
    values = lockdown.all_values
    version = values.get("ProductVersion")
    if expected_version and version != expected_version:
        raise ValueError("Connected iOS version does not match --expected-version")
    service = await lockdown.start_lockdown_service("com.apple.springboardservices")
    try:
        # Intentionally no SpringBoard write-capable wrapper or Session object.
        state = await asyncio.wait_for(service.send_recv_plist(
            {"command": "getIconState", "formatVersion": "2"}), timeout=20)
        result = inspect_layout(state)
    finally:
        await service.close()
    return {
        "product_type": values.get("ProductType"),
        "ios_version": version,
        "build": values.get("BuildVersion"),
        "read_tested": True,
        "write_tested": False,
        "automatic_pairing": False,
        "springboard_commands": ["getIconState"],
        **result,
    }


async def usb_diagnostics(*, expected_version: str | None = None) -> dict[str, Any]:
    from pymobiledevice3.usbmux import list_devices
    from pymobiledevice3.lockdown import create_using_usbmux

    devices = [d for d in await list_devices() if d.connection_type == "USB"]
    if len(devices) != 1:
        raise ValueError(f"Connect exactly one USB iPhone/iPad (found {len(devices)}); no device selected")
    lockdown = await create_using_usbmux(serial=devices[0].serial, autopair=False, connection_type="USB")
    try:
        return await probe_lockdown(lockdown, expected_version=expected_version)
    finally:
        await lockdown.close()


async def diagnostics(*, expected_version: str | None = None) -> dict[str, Any]:
    return await asyncio.wait_for(usb_diagnostics(expected_version=expected_version), timeout=45)
