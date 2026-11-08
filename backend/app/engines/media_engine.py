"""Deterministic physical media decisions. Distances are normalized to metres."""
from dataclasses import dataclass
import math


class PhysicalDistanceViolationError(ValueError):
    def __init__(self, distance_m: float, maximum_m: float = 100):
        self.distance_m = distance_m
        self.maximum_m = maximum_m
        self.recommended_alternative = "OM4 multimode fiber through 400 m or OS2 single-mode fiber beyond 400 m"
        super().__init__(f"Copper link distance {distance_m:g} m exceeds the {maximum_m:g} m channel limit; attenuation and crosstalk may make the link unreliable. Recommended alternative: {self.recommended_alternative}.")


@dataclass
class LinkRequest:
    distance_m: float
    requested_medium: str | None = None
    bandwidth_gbps: float = 10
    name: str = "Link"


def recommend_media(request: LinkRequest) -> dict:
    d = request.distance_m
    if not math.isfinite(d) or d < 0:
        raise ValueError("Distance must be a finite non-negative number")
    if not math.isfinite(request.bandwidth_gbps) or request.bandwidth_gbps <= 0:
        raise ValueError("Bandwidth must be a finite positive number")
    if request.bandwidth_gbps > 10:
        raise ValueError("This planning rule set validates 10 Gbps Ethernet PHYs only; use a rate-specific optical reach design for higher bandwidth")
    medium = (request.requested_medium or "auto").lower()
    if medium in {"copper", "cat6a", "cat6"} and d > 100:
        raise PhysicalDistanceViolationError(d)
    if d <= 100:
        kind, optic, wavelength = "Cat6a copper", "10GBASE-T", "N/A"
        limitation = "Use a standards-compliant channel no longer than 100 m; installation quality and alien crosstalk affect performance."
        standard = "IEEE 802.3an (10GBASE-T)"
    elif d <= 400:
        kind, optic, wavelength = "OM4 multimode fiber", "10GBASE-SR", "850 nm"
        limitation = "OM4 reach is transceiver and data-rate dependent; modal bandwidth and connector losses limit reach. Verify the exact optic and installed channel."
        standard = "IEEE 802.3ae (10GBASE-SR)"
    elif d <= 40000:
        kind, optic, wavelength = "OS2 single-mode fiber", ("10GBASE-ER" if d > 10000 else "10GBASE-LR"), ("1550 nm" if d > 10000 else "1310 nm")
        limitation = "Nominal LR/ER reach does not prove this link is viable. Check both-end module compatibility, fiber attenuation, connector/splice losses, dispersion, and receive power against the vendor optical budget."
        standard = "IEEE 802.3ae (10GBASE-LR/ER)"
    else:
        kind, optic, wavelength = "Carrier Ethernet over engineered OS2 transport", "Provider-specified handoff optic (no direct LR/ER recommendation)", "Carrier engineered"
        limitation = "This path exceeds the nominal 40 km 10GBASE-ER reach class. Use a carrier optical transport system or engineered regeneration/amplification plan; agree the handoff optic with the carrier and validate the complete optical budget."
        standard = "Carrier service handoff and optical transport design required"
    if medium in {"om4", "multimode", "fiber multimode"} and d > 400:
        raise ValueError("OM4 requested above this engine's 400 m planning threshold; use OS2 and validate optic reach")
    if medium in {"os2", "single-mode", "fiber single-mode"} and d <= 400:
        kind = "OS2 single-mode fiber"
        optic, wavelength = ("10GBASE-LR", "1310 nm")
        limitation = "Short-reach single-mode is feasible when supported at both ends; confirm optic compatibility and received optical power."
    rationale = ("Cat6a carries 10GBASE-T over a compliant copper Ethernet channel up to 100 m and can support PoE endpoints; validate cable category, installation, and crosstalk." if kind == "Cat6a copper" else
                 "OM4 multimode fiber is suited to short building backbones with 10GBASE-SR at 850 nm; modal dispersion and channel losses constrain its rate-specific reach." if kind == "OM4 multimode fiber" else
                 "This path exceeds the nominal direct 10GBASE-ER reach class; use a provider optical transport handoff or an engineered regeneration plan rather than a generic LR/ER optic." if d > 40000 else
                 "OS2 single-mode fiber supports longer optical paths with lower modal dispersion than multimode fiber; the optic and complete optical budget determine usable reach.")
    return {"name": request.name, "distance_m": d, "medium": kind, "transceiver": optic, "wavelength": wavelength,
            "input_parameters": {"distance_m":d,"requested_medium":request.requested_medium or "auto","bandwidth_gbps":request.bandwidth_gbps},
            "decision": f"{kind} with {optic}", "condition": f"distance={d:g} m; planning thresholds: copper <=100 m, OM4 <=400 m, OS2 above 400 m",
            "explanation": rationale + " " + limitation, "mathematical_justification": f"{d:g} m maps to the selected distance class. A direct 10GBASE-LR span is limited to its nominal 10 km class and ER to 40 km; this selection still needs a vendor optical-budget check.", "standard": standard,
            "advantages": ["Meets the distance class used by this planner", "Uses a common Ethernet PHY for the selected medium"],
            "limitations": [limitation], "alternatives": (["OM4 multimode where optical isolation or pathway conditions justify fiber", "OS2 single-mode for links above 400 m"] if d <= 100 else
                ["Cat6a when the channel is at most 100 m", "OS2 for links above the validated OM4 reach"] if d <= 400 else
                ["OM4 only where the exact optic and channel meet its reach limit", "Carrier optical transport for spans beyond direct LR/ER reach"])}
