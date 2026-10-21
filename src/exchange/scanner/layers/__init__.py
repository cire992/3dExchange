"""Organizational-layer handlers, referenced by name from environment definitions."""

from exchange.scanner.layers import daz, folder, mo2, unreal
from exchange.scanner.layers.base import Handler

HANDLERS: dict[str, Handler] = {
    "daz": daz.identify,
    "folder": folder.identify,
    "mo2": mo2.identify,
    "unreal": unreal.identify,
}
