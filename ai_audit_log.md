# AI Code Audit Report: NetArchitect Engine

**Course**: CIC-307 Computer Networks  
**Project**: NetArchitect — Recommendation & Configuration Engine  
**Document**: `ai_audit_log.md`  
**Purpose**: Documenting prompts, AI-generated code defects, technical root-cause analyses, and production fixes implemented during the development of NetArchitect.

---

## Executive Summary

During the development of NetArchitect's backend engines (VLSM address allocation, routing recommendation, and Cisco IOS configuration generation), generative AI models were employed to accelerate prototyping. While the AI models generated syntactically plausible Python and Cisco IOS configurations, rigorous auditing revealed critical network engineering bugs:
1. **Mathematical rounding defects** in binary prefix allocation that led to address starvation and overlapping subnets.
2. **Security & protocol anti-patterns** in Cisco IOS 802.1Q trunk generation that allowed unpruned broadcast domains and potential VLAN hopping.

This audit log records the prompts, buggy code, in-depth technical analysis, and final fixes applied to guarantee RFC compliance, least-privilege switch configuration, and deterministic execution.

---

## Audit Case 1: VLSM Subnet Sizing & Prefix Calculation

### 1. Prompt
> *"Write a Python helper function that chooses an IPv4 prefix length for a VLAN given N required client hosts and one default gateway. The function must return a subnet mask prefix large enough to accommodate all client hosts, the default gateway, and standard IPv4 network overhead."*

### 2. Buggy AI Code
```python
def prefix_for_hosts(hosts: int) -> int:
    # Attempted logic: calculate required host bits from demand
    addresses = hosts + 1  # Clients + 1 gateway
    bits = addresses.bit_length() - 1
    return 32 - bits
```

### 3. Technical Analysis
* **Root Defect**: The calculation `addresses.bit_length() - 1` computes $\lfloor \log_2(\text{demand}) \rfloor$ (a mathematical floor operation), effectively finding the largest power of two *less than or equal* to the demand rather than the ceiling.
* **Network Overhead Neglect**: In standard IPv4 broadcast networks (RFC 791 / RFC 1122), two addresses are reserved:
  - Network ID (all host bits 0)
  - Directed Broadcast address (all host bits 1)  
  The AI code only accounted for the gateway (`hosts + 1`) and completely omitted the 2 reserved addresses.
* **Concrete Failure Example**:
  - For a request of `100` hosts + `1` gateway: `addresses = 101`.
  - In binary, `101.bit_length() = 7`.
  - `bits = 7 - 1 = 6`.
  - Prefix returned: `32 - 6 = /26` (64 total IP addresses).
  - A `/26` provides only 62 usable host addresses, causing an immediate shortage of 39 addresses for a 101-host requirement.
* **Packet & Routing Impact**:
  - The subnet would experience immediate DHCP pool exhaustion or IP address exhaustion.
  - Subsequent sequential VLSM allocation in the engine would place the adjacent VLAN at boundary offset +64, directly overlapping with the first VLAN's required IP space.
  - Hosts assigned duplicate IPs would experience ARP conflicts, broken TCP handshakes, and intermittent packet drops at the distribution router.

### 4. Final Fix & Verification
In [`backend/app/engines/vlsm_engine.py`](backend/app/engines/vlsm_engine.py), the allocation logic was completely replaced with strict power-of-two ceiling rounding and boundary alignment:

```python
def prefix_for_hosts(hosts: int) -> int:
    """
    Calculate minimal IPv4 prefix length accommodating hosts,
    default gateway, and RFC network/broadcast addresses.
    """
    if hosts <= 0:
        raise ValueError("Host requirement must be a positive integer")
    
    # Total addresses needed: endpoints + gateway + network address + broadcast address
    total_needed = hosts + 1 + 2
    
    # Ceiling power of 2 using bit_length on (total_needed - 1)
    host_bits = (total_needed - 1).bit_length()
    
    # Ensure standard LAN subnets do not exceed /30 (minimum 4 addresses)
    host_bits = max(host_bits, 2)
    return 32 - host_bits
```

* **Verification**:
  - For 100 hosts: `total_needed = 103`. `(102).bit_length() = 7` host bits $\rightarrow$ Prefix `/25` (128 addresses, 126 usable).
  - Unit tests in `backend/tests/test_engines.py` assert zero overlap between adjacent allocations and verify boundary alignment across all three preset scenarios.

---

## Audit Case 2: 802.1Q Trunk Port Defaulting to All VLANs

### 1. Prompt
> *"Generate a Cisco IOS switch configuration for an access switch trunk uplink interface connected to the distribution switch, carrying the VLANs defined in the network design."*

### 2. Buggy AI Code
```text
interface GigabitEthernet1/0/48
 description Uplink to Distribution Switch
 switchport mode trunk
 switchport trunk allowed vlan all
 no shutdown
```

### 3. Technical Analysis
* **Root Defect**: The AI defaulted to `switchport trunk allowed vlan all`, permitting all VLANs (1 through 4094) across the trunk link.
* **Security & Operational Hazards**:
  - **Broadcast Domain Expansion**: Broadcast, multicast, and unknown unicast frames (BUM traffic) from all active VLANs leak across inter-switch links, wasting link bandwidth and processing overhead on downstream access switches.
  - **VLAN Hopping & Double Tagging**: Allowing VLAN 1 (the default native VLAN) without explicit tagging or pruning exposes the switch fabric to double-tagged 802.1Q encapsulation attacks.
  - **Violation of Least Privilege**: Access switches only require the VLANs mapped to their specific local access ports and management SVI. Trunking all VLANs exposes sensitive VLANs (e.g., Server or Management segments) to access switches where they are not authorized.

### 4. Final Fix & Verification
In [`backend/app/engines/config_engine.py`](backend/app/engines/config_engine.py), the trunk generation was re-engineered to enforce:
1. Dynamic construction of strict, explicit allowed-VLAN lists matching only the active design.
2. Blackholing the native VLAN to an isolated, unused VLAN ID (4094).
3. Disabling DTP (Dynamic Trunking Protocol) via `switchport nonegotiate` to eliminate trunk spoofing.

```python
# Production implementation in config_engine.py
allowed_vlan_str = ",".join(str(v["vlan_id"]) for v in sorted(vlans, key=lambda x: x["vlan_id"]))

trunk_config = [
    "interface GigabitEthernet1/0/48",
    " description Uplink trunk - explicit allowed VLANs only",
    " switchport mode trunk",
    " switchport trunk native vlan 4094",  # Blackhole native VLAN
    f" switchport trunk allowed vlan {allowed_vlan_str}",
    " switchport nonegotiate",  # Prevent DTP spoofing
    " no shutdown"
]
```

* **Verification**:
  - Inspected generated output for `campus-lan`: `switchport trunk allowed vlan 10,20,30,40,50` with native VLAN 4094.
  - Verified in Cisco Packet Tracer that tagged frames for undeclared VLANs (e.g. VLAN 99) are immediately discarded by the ingress port ASIC without propagation.

---

## Audit Case 3: OSPF Multi-Area Summarization & Area 0 Boundary

### 1. Prompt
> *"Create a routing recommendation and OSPF configuration snippet for a multi-building enterprise network where each building operates as a separate OSPF area."*

### 2. Buggy AI Code
```text
router ospf 1
 network 0.0.0.0 255.255.255.255 area 0
 area 1 range 10.10.0.0 255.255.0.0
```

### 3. Technical Analysis
* **Contradictory Routing Scope**: Placing `0.0.0.0 255.255.255.255 area 0` includes **all** router interfaces into the backbone area (Area 0). Simultaneously declaring `area 1 range ...` has no effect because an Area Border Router (ABR) can only summarize routes originating from non-backbone areas into Area 0, not when all interfaces are already inside Area 0.
* **Wildcard Mask Misunderstanding**: Generative AI models frequently confuse subnet masks (`255.255.255.0`) with Cisco inverted wildcard masks (`0.0.0.255`) or apply summarization ranges at internal routers instead of ABRs.
* **Routing Loop Hazard**: Advertising a broad `/16` summary range without null routing (`ip route 10.10.0.0 255.255.0.0 Null0`) creates micro-loops if packets arrive for unallocated subnets within the summary range.

### 4. Final Fix & Verification
In NetArchitect's routing engine ([`backend/app/engines/routing_engine.py`](backend/app/engines/routing_engine.py)), routing decisions are partitioned based on topological boundaries:
- Single-site designs default strictly to OSPF Area 0.
- Multi-site designs emit warnings requiring explicit ABR site-to-VLAN mapping.
- Exact route summarization computes the minimal aggregate using Python's `ipaddress.collapse_addresses()` to avoid over-summarization blackholes.

---

## Summary Matrix

| Audit Item | AI Bug Identified | Protocol / RFC Impact | Production Fix in NetArchitect |
|---|---|---|---|
| **VLSM Prefix** | `(hosts + 1).bit_length() - 1` (floor rounding) | Subnet collision; DHCP exhaustion; missing net/bcast IDs (RFC 791) | Exact ceil calculation: `(hosts + 3).bit_length()` with overlap validation |
| **802.1Q Trunk** | `switchport trunk allowed vlan all` | Unpruned broadcast domain; DTP spoofing; VLAN hopping (IEEE 802.1Q) | Explicit pruned VLAN list; native blackhole VLAN 4094; `nonegotiate` |
| **OSPF Multi-Area** | Wildcard `0.0.0.0` in Area 0 with conflicting ABR range | ABR summarization failure; routing loops (RFC 2328) | Exact address collapse algorithm; deterministic single vs multi-area selection |
