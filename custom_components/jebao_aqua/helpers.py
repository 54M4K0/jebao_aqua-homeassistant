"""Helper functions for Jebao Aqua integration."""

from __future__ import annotations

from typing import Any

from .const import DOMAIN, LOGGER

# Attributes hidden by default (managed by smart dosing or raw binary data)
HIDDEN_ATTRS: set[str] = {
    # Manual pump channels — dangerous, replaced by safe service
    "channe1",
    "channe2",
    "channe3",
    "channe4",
    "channe5",
    "channe6",
    "channe7",
    "channe8",
    # Timer on/off — managed by smart dosing
    "Timer1ON",
    "Timer2ON",
    "Timer3ON",
    "Timer4ON",
    "Timer5ON",
    "Timer6ON",
    "Timer7ON",
    "Timer8ON",
    # Interval — managed by smart dosing
    "IntervalT1",
    "IntervalT2",
    "IntervalT3",
    "IntervalT4",
    "IntervalT5",
    "IntervalT6",
    "IntervalT7",
    "IntervalT8",
    # Schedule blobs — binary, not user-readable
    "CH1SWTime",
    "CH2SWTime",
    "CH3SWTime",
    "CH4SWTime",
    "CH5SWTime",
    "CH6SWTime",
    "CH7SWTime",
    "CH8SWTime",
    # Calibration — diagnostic only
    "CALSW",
    "CALSet",
    "Calib1",
    # Raw binary date/time — replaced by Device Clock sensor
    "YMDData",
    "HMSData",
}


def is_hidden_attr(attr_name: str) -> bool:
    """Check if an attribute should be hidden by default."""
    return attr_name in HIDDEN_ATTRS


def get_device_info(device: dict) -> dict:
    """Return standardized device information dictionary."""
    device_name = device.get("dev_alias") or f"Jebao {device['did'][-6:]}"
    lan_ip = device.get("lan_ip")

    info = {
        "identifiers": {(DOMAIN, device["did"])},
        "name": device_name,
        "manufacturer": "Jebao",
    }

    if lan_ip:
        info["connections"] = {("ip", lan_ip)}

    return info


def get_model_attrs(model: dict) -> list[dict]:
    """Get attrs list from model, supporting both old and new format."""
    attrs = model.get("attrs", [])
    if not attrs:
        entities = model.get("entities", [])
        if entities:
            attrs = entities[0].get("attrs", [])
    return attrs


# --- Attribute display name translations (Chinese -> English) ---
# Used to provide user-friendly entity names in Home Assistant.
ATTR_DISPLAY_NAMES: dict[str, str] = {
    # Multi-head doser (MD-4.5 etc.)
    "开关": "Power",
    "通道1": "Channel 1",
    "通道2": "Channel 2",
    "通道3": "Channel 3",
    "通道4": "Channel 4",
    "通道5": "Channel 5",
    "通道6": "Channel 6",
    "通道7": "Channel 7",
    "通道8": "Channel 8",
    "定时开关1": "Timer 1",
    "定时开关2": "Timer 2",
    "定时开关3": "Timer 3",
    "定时开关4": "Timer 4",
    "定时开关5": "Timer 5",
    "定时开关6": "Timer 6",
    "定时开关7": "Timer 7",
    "定时开关8": "Timer 8",
    "校准开关": "Calibration",
    "校准通道": "Calibration Channel",
    "校准量": "Calibration Volume",
    "校准时间": "Calibration Time",
    "校准1": "Calibration 1",
    "头数量": "Active Channels",
    "间隙时间1": "Interval 1",
    "间隙时间2": "Interval 2",
    "间隙时间3": "Interval 3",
    "间隙时间4": "Interval 4",
    "间隙时间5": "Interval 5",
    "间隙时间6": "Interval 6",
    "间隙时间7": "Interval 7",
    "间隙时间8": "Interval 8",
    "开路": "Open Circuit",
    "串口连接故障": "UART Fault",
    "日期数据": "Date Data",
    "时间数据": "Time Data",
    # Pump / wave maker
    "控制模式": "Control Mode",
    "固定速度": "Fixed Speed",
    "自定义脉冲": "Custom Pulse",
    "潮汐模式": "Tide Mode",
    "波浪模式": "Wave Mode",
    "联动": "Linkage",
    "夜间模式": "Night Mode",
    "夜间速度": "Night Speed",
    "喂食模式": "Feed Mode",
    "喂食时间": "Feed Duration",
    "白天速度": "Day Speed",
    "夜间开始": "Night Start",
    "夜间结束": "Night End",
    "速度": "Speed",
    "方向": "Direction",
    "频率": "Frequency",
    "最大速度": "Max Speed",
    "最小速度": "Min Speed",    
    "开机/关机": "Power Switch",
    "喂食开关": "Feed Switch",
    "喂食时长": "Feed Duration",
    "定时开关": "Program Switch",
    "当前定时喂食时间": "Manual Feed Time",
    "模式": "Mode",
    "当前定时模式": "Current Program Mode",
    "当前定时档位": "Current Program Setting",
    "当前定时流量": "Current Program Flow",
    "当前定时脉冲潮汐": "Current Program Pulse Tide",
    "当前定时频率": "Set Program Frequency",
    "脉冲潮汐": "Pulse Wave",
    "温度过高": "Over Temperature",
    "电机堵转": "Motor Stall",
    "电机欠压": "Under Voltage",
    "电机过压": "Over Voltage",
    "电机过流": "Over Current",
    "空载": "No Load",
    "设定电机转速": "Set Flow Speed",
    # Light
    "亮度": "Brightness",
    "色温": "Color Temperature",
    "白光": "White",
    "蓝光": "Blue",
    "红光": "Red",
    "绿光": "Green",
    "紫光": "Purple",
    "UV": "UV",
    "日出时间": "Sunrise Time",
    "日落时间": "Sunset Time",
    "自动模式": "Auto Mode",
    "定时模式": "Timer Mode",
    "手动模式": "Manual Mode",
    # Feeder
    "喂食量": "Feed Amount",
    "剩余食量": "Remaining Food",
    "电池电量": "Battery Level",
    # Filter
    "过滤模式": "Filter Mode",
    "流量": "Flow Rate",
    # General
    "温度": "Temperature",
    "湿度": "Humidity",
    "信号强度": "Signal Strength",
    "固件版本": "Firmware Version",
}


# --- Entity naming helpers (aliases for backward compatibility) ---


def make_entity_name(attr_display_name: str) -> str:
    """Create entity name from attribute display name, with translation."""
    return ATTR_DISPLAY_NAMES.get(attr_display_name, attr_display_name)


# --- Enum value translations ---
ENUM_TRANSLATIONS: dict[str, str] = {
    "校准1": "Calibrate CH1",
    "校准2": "Calibrate CH2",
    "校准3": "Calibrate CH3",
    "校准4": "Calibrate CH4",
    "校准5": "Calibrate CH5",
    "校准6": "Calibrate CH6",
    "校准7": "Calibrate CH7",
    "校准8": "Calibrate CH8",
    # Wave pump modes
    "固定模式": "Fixed Mode",
    "脉冲模式": "Pulse Mode",
    "随机模式": "Random Mode",
    "潮汐模式": "Tide Mode",
    "自定义模式": "Custom Mode",
    "夜间模式": "Night Mode",
    "喂食模式": "Feed Mode",
    "经典造浪": "Classic Wave",
    "正弦造浪,": "Sine Wave",
    "随机造浪": "Random Wave",
    "恒流造浪": "Constant Speed",
    # Light modes
    "手动模式": "Manual Mode",
    "自动模式": "Auto Mode",
    "定时模式": "Timer Mode",
    # General
    "开": "On",
    "关": "Off",
    "正转": "Forward",
    "反转": "Reverse",
    # MDP/DCP pump modes
    "停机": "Stopped",
    "自动": "Auto",
    "喂食": "Feed",
    #Linked Modes
    "独立": "Independent",
    "主机": "Master",
    "从机": "Slave",
}


def translate_enum_value(value: str) -> str:
    """Translate a Chinese enum value to English."""
    return ENUM_TRANSLATIONS.get(value, value)


def make_entity_id(platform: str, device_id: str, attr_name: str) -> str:
    """Create standardized entity ID."""
    safe_id = device_id.replace(" ", "_").lower()
    safe_attr = attr_name.replace(" ", "_").lower()
    return f"{platform}.{safe_id}_{safe_attr}"


def make_unique_id(device_id: str, attr_name: str) -> str:
    """Create standardized unique ID."""
    return f"{device_id}_{attr_name.replace(' ', '_').lower()}"


# Backward-compatible aliases
create_entity_name = lambda device_name, attr_name: make_entity_name(attr_name)
create_entity_id = lambda platform, device_name, attr_name: make_entity_id(
    platform, device_name, attr_name
)
create_unique_id = make_unique_id


def is_device_data_valid(device_data: dict | None) -> bool:
    """Check if device data is valid."""
    if not device_data or not isinstance(device_data, dict):
        return False
    attr = device_data.get("attr")
    return bool(attr and isinstance(attr, dict))


def safe_get_attr_value(
    coordinator_data: dict | None, device_id: str, attribute: str
) -> Any | None:
    """Safely get attribute value from coordinator data."""
    if not coordinator_data:
        return None
    device_data = coordinator_data.get(device_id)
    if not is_device_data_valid(device_data):
        return None
    return device_data.get("attr", {}).get(attribute)


# Legacy alias
def get_attribute_value(device_data: dict, attribute: str) -> Any | None:
    """Safely get attribute value from device data (legacy)."""
    if not is_device_data_valid(device_data):
        return None
    return device_data.get("attr", {}).get(attribute)
