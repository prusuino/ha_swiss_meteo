"""The MeteoAlarm files, built from the alert mappings the tests describe.

The integration reads the Atom feed of the alerts in force and then each
alert that covers its point as a CAP document. `warning_routes` turns the
payload of the tests (`{"warnings": [alert(...), ...]}`) into exactly these
files, keyed by URL, ready for a `FakeSession`.
"""
from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from custom_components.swiss_meteo.meteoalarm import WARNINGS_URL

ATOM = "http://www.w3.org/2005/Atom"
CAP = "urn:oasis:names:tc:emergency:cap:1.2"
ALERT_BASE = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-switzerland/"


def cap_url(entry: dict[str, Any]) -> str:
    return ALERT_BASE + str(entry.get("uuid") or entry["alert"].get("identifier"))


def _polygons(info: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for area in info.get("area") or []:
        polygon = area.get("polygon")
        if polygon is None:
            continue
        found += [str(text) for text in (polygon if isinstance(polygon, list) else [polygon])]
    return found


def cap_xml(entry: dict[str, Any]) -> bytes:
    """One alert as the CAP document MeteoAlarm serves."""
    alert = entry["alert"]
    root = ET.Element(f"{{{CAP}}}alert")
    for key in ("identifier", "sender", "sent", "status", "msgType", "references"):
        if alert.get(key) is not None:
            ET.SubElement(root, f"{{{CAP}}}{key}").text = str(alert[key])
    for info in alert.get("info") or []:
        node = ET.SubElement(root, f"{{{CAP}}}info")
        for key in ("language", "event", "headline", "description", "instruction", "senderName", "web", "onset", "effective", "expires"):
            if info.get(key) is not None:
                ET.SubElement(node, f"{{{CAP}}}{key}").text = str(info[key])
        for parameter in info.get("parameter") or []:
            pair = ET.SubElement(node, f"{{{CAP}}}parameter")
            ET.SubElement(pair, f"{{{CAP}}}valueName").text = str(parameter["valueName"])
            ET.SubElement(pair, f"{{{CAP}}}value").text = str(parameter["value"])
        for area in info.get("area") or []:
            place = ET.SubElement(node, f"{{{CAP}}}area")
            if area.get("areaDesc") is not None:
                ET.SubElement(place, f"{{{CAP}}}areaDesc").text = str(area["areaDesc"])
            polygon = area.get("polygon")
            for text in [] if polygon is None else (polygon if isinstance(polygon, list) else [polygon]):
                ET.SubElement(place, f"{{{CAP}}}polygon").text = str(text)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def atom_feed(payload: dict[str, Any], *, links: bool = True) -> bytes:
    """The feed of the alerts in force: one entry per alert, with the area of
    the first language block that has one."""
    root = ET.Element(f"{{{ATOM}}}feed")
    ET.SubElement(root, f"{{{ATOM}}}title").text = "MeteoAlarm - Switzerland"
    for entry in payload.get("warnings") or []:
        alert = entry["alert"]
        infos = alert.get("info") or []
        node = ET.SubElement(root, f"{{{ATOM}}}entry")
        if alert.get("identifier") is not None:
            ET.SubElement(node, f"{{{CAP}}}identifier").text = str(alert["identifier"])
        ET.SubElement(node, f"{{{CAP}}}status").text = str(alert.get("status", "Actual"))
        ET.SubElement(node, f"{{{CAP}}}message_type").text = str(alert.get("msgType", "Alert"))
        expires = next((info["expires"] for info in infos if info.get("expires")), None)
        if expires is not None:
            ET.SubElement(node, f"{{{CAP}}}expires").text = str(expires)
        for text in next((_polygons(info) for info in infos if _polygons(info)), []):
            ET.SubElement(node, f"{{{CAP}}}polygon").text = text
        ET.SubElement(node, f"{{{ATOM}}}link", {"href": "https://meteoalarm.org?region=CH", "rel": "related"})
        if links:
            ET.SubElement(node, f"{{{ATOM}}}link", {"type": "application/cap+xml", "href": cap_url(entry)})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def warning_routes(payload: dict[str, Any]) -> dict[str, bytes]:
    """The feed and every alert of it, by URL."""
    routes = {WARNINGS_URL: atom_feed(payload)}
    for entry in payload.get("warnings") or []:
        routes[cap_url(entry)] = cap_xml(entry)
    return routes
