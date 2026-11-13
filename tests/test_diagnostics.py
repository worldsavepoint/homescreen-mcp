import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from homescreen.diagnostics import inspect_layout, probe_lockdown, usb_diagnostics


class Service:
    def __init__(self):
        self.commands = []
        self.closed = False

    async def send_recv_plist(self, command):
        self.commands.append(command)
        return [[], [{"bundleIdentifier": "com.example.private", "displayName": "Private"}]]

    async def close(self):
        self.closed = True


class Lockdown:
    paired = True
    all_values = {"ProductVersion": "1.0", "ProductType": "SampleDevice1,1",
                  "BuildVersion": "SAMPLE_BUILD", "UniqueDeviceID": "secret-udid"}

    def __init__(self):
        self.services = []
        self.service = Service()

    async def start_lockdown_service(self, name):
        self.services.append(name)
        return self.service


def test_probe_only_sends_get_icon_state_and_redacts_identifiers():
    phone = Lockdown()
    report = asyncio.run(probe_lockdown(phone, expected_version="1.0"))
    assert phone.services == ["com.apple.springboardservices"]
    assert phone.service.commands == [{"command": "getIconState", "formatVersion": "2"}]
    assert phone.service.closed
    assert report["apps_on_home_screen"] == 1
    assert report["write_tested"] is False
    assert "secret-udid" not in str(report)
    assert "com.example.private" not in str(report)


@pytest.mark.parametrize("paired,version", [(False, "1.0"), (True, "2.0")])
def test_no_service_started_without_pairing_or_expected_version(paired, version):
    phone = Lockdown()
    phone.paired = paired
    phone.all_values = dict(phone.all_values, ProductVersion=version)
    with pytest.raises(ValueError):
        asyncio.run(probe_lockdown(phone, expected_version="1.0"))
    assert phone.services == []


def test_invalid_shape_rejected():
    with pytest.raises(ValueError):
        inspect_layout({"unknown": []})


def test_folder_widget_counts():
    state = [[], [{"displayName": "Folder", "iconLists": [[{"bundleIdentifier": "a"}]]},
                  {"iconType": "custom", "gridSize": "small", "displayName": "Widget"}]]
    report = inspect_layout(state)
    assert report["folders"] == 1 and report["widgets"] == 1
    assert report["apps_on_home_screen"] == 1


def test_usb_uses_existing_pairing_and_explicit_single_usb_device(monkeypatch):
    import pymobiledevice3.usbmux as mux
    import pymobiledevice3.lockdown as lockdown
    phone = Lockdown()
    phone.close = AsyncMock()
    create = AsyncMock(return_value=phone)
    monkeypatch.setattr(mux, "list_devices", AsyncMock(return_value=[
        SimpleNamespace(serial="fixture-id", connection_type="USB"),
        SimpleNamespace(serial="other", connection_type="Network")]))
    monkeypatch.setattr(lockdown, "create_using_usbmux", create)
    asyncio.run(usb_diagnostics(expected_version="1.0"))
    create.assert_awaited_once_with(serial="fixture-id", autopair=False, connection_type="USB")
    phone.close.assert_awaited_once()


@pytest.mark.parametrize("count", [0, 2])
def test_ambiguous_usb_selection_does_not_connect(monkeypatch, count):
    import pymobiledevice3.usbmux as mux
    import pymobiledevice3.lockdown as lockdown
    create = AsyncMock()
    monkeypatch.setattr(mux, "list_devices", AsyncMock(return_value=[
        SimpleNamespace(serial=str(i), connection_type="USB") for i in range(count)]))
    monkeypatch.setattr(lockdown, "create_using_usbmux", create)
    with pytest.raises(ValueError):
        asyncio.run(usb_diagnostics())
    create.assert_not_awaited()


def test_read_failure_closes_service():
    phone = Lockdown()
    phone.service.send_recv_plist = AsyncMock(side_effect=TimeoutError)
    with pytest.raises(TimeoutError):
        asyncio.run(probe_lockdown(phone))
    assert phone.service.closed
