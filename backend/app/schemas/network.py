from typing import Literal
from ipaddress import IPv4Network
import re
from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator

class VLAN(BaseModel):
    vlan_id: int = Field(ge=1, le=4094)
    name: str = Field(min_length=1, max_length=32)
    hosts: int = Field(gt=0, le=4_000_000_000)

    @field_validator("name")
    @classmethod
    def safe_vlan_name(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,31}", value.strip()):
            raise ValueError("VLAN name must use letters, numbers, spaces, dot, underscore, or hyphen")
        return value.strip()

class Link(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    distance_m: float = Field(ge=0, le=1_000_000)
    requested_medium: str | None = None
    bandwidth_gbps: float = Field(default=10, gt=0, le=10)

class SecurityPolicy(BaseModel):
    name: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    source_vlan_id: int = Field(ge=1, le=4094)
    destination_cidr: IPv4Network
    action: Literal["permit", "deny"]
    protocol: Literal["ip", "tcp", "udp", "icmp"] = "ip"

class NetworkRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    network_name: str = Field(default="Custom Network", min_length=1, max_length=50)
    network_type: Literal["LAN", "MAN", "WAN", "Hybrid"] = "LAN"
    sites: int = Field(default=1, ge=1, le=1000)
    buildings: int = Field(default=1, ge=1, le=1000)
    site_names: list[str] = Field(default_factory=list, max_length=1000)
    building_names: list[str] = Field(default_factory=list, max_length=1000)
    users: int = Field(default=100, ge=1, le=10_000_000)
    endpoints: int = Field(default=100, ge=1, le=10_000_000)
    switches: int = Field(default=4, ge=0, le=100_000)
    routers: int = Field(default=1, ge=0, le=100_000)
    root_cidr: str = "10.0.0.0/16"
    vlans: list[VLAN] = Field(min_length=1, max_length=4094)
    links: list[Link] = Field(default_factory=list)
    cloud: bool = False
    vpn: bool = False
    qos: bool = False
    redundancy: bool = False
    poe: bool = False
    latency_ms: float | None = Field(default=None, gt=0)
    routing_requirement: str = "auto"
    reserved_subnets: list[str] = Field(default_factory=list)
    security_policies: list[SecurityPolicy] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def reject_conflicting_security_rules(self):
        if self.site_names and len(self.site_names) != self.sites:
            raise ValueError("Provide one site name per configured site")
        if self.building_names and len(self.building_names) != self.buildings:
            raise ValueError("Provide one building name per configured building")
        policies = self.security_policies
        names = [p.name.lower() for p in policies]
        if len(names) != len(set(names)):
            raise ValueError("Security policy names must be unique")
        vlan_ids = {v.vlan_id for v in self.vlans}
        if any(p.source_vlan_id not in vlan_ids for p in policies):
            raise ValueError("Every security policy source must reference a configured VLAN")
        for i, left in enumerate(policies):
            for right in policies[i+1:]:
                protocol_overlap = left.protocol == right.protocol or "ip" in (left.protocol, right.protocol)
                if (left.source_vlan_id == right.source_vlan_id and protocol_overlap and
                    left.action != right.action and left.destination_cidr.overlaps(right.destination_cidr)):
                    raise ValueError(f"Conflicting security policies {left.name} and {right.name} overlap with opposite actions")
        return self

    @field_validator("network_name")
    @classmethod
    def trim_network_name(cls, value):
        cleaned = value.strip()
        if not cleaned: raise ValueError("Network name cannot be blank")
        return cleaned

