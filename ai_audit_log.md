# AI Code Audit Log

## Academic integrity note

No actual AI-generated implementation defect was observed and recorded during this project session. The two cases below are **illustrative exercises**, not evidence of a real hallucination. A student should run the examples, record observed output and test evidence, then replace or supplement this section with the actual AI output and audit evidence required by the instructor. Do not represent these examples as incidents that occurred during development.

## Illustrative case 1: VLSM block size rounds down

### Original prompt (illustrative)

> Write a Python helper that chooses an IPv4 prefix for a VLAN with N required client hosts and one gateway. Return a subnet large enough for every client and the gateway.

### Buggy code (illustrative)

```python
def prefix_for_hosts(hosts):
    # Incorrect: chooses the largest power of two no greater than demand.
    addresses = hosts + 1
    bits = addresses.bit_length() - 1
    return 32 - bits
```

### Defect and possible impact

The floor operation rounds down. For 100 clients plus a gateway, it can choose a 64-address block, which cannot hold the demand even before the network and broadcast reservations. A later allocator may overlap adjacent VLANs or silently omit hosts if it does not check capacity.

### Corrected approach

```python
def prefix_for_hosts(hosts):
    if hosts <= 0:
        raise ValueError("host requirement must be positive")
    addresses = hosts + 1 + 2  # endpoints, gateway, network, broadcast
    bits = (addresses - 1).bit_length()  # ceiling(log2(addresses))
    return 32 - bits
```

### Verification and packet consequence

Check that 100 endpoints plus a gateway require at least 103 total addresses and therefore a 128-address block (`/25`, 126 ordinary usable addresses). Allocate two adjacent VLANs and assert that their network ranges do not overlap. With the buggy size, an endpoint near the end of the assigned range could fail ARP resolution or be placed in another VLAN's address range; a router would then drop or misroute traffic. The project allocator independently checks alignment and overlap.

## Illustrative case 2: trunk permits every VLAN

### Original prompt (illustrative)

> Generate a Cisco IOS trunk uplink configuration for the VLANs present in a network plan.

### Buggy code (illustrative)

```text
interface GigabitEthernet1/0/48
 switchport mode trunk
 switchport trunk allowed vlan all
```

### Defect and possible impact

The command permits VLANs that the design does not require on the link. This expands the broadcast and Layer 2 reachability domain and can expose unintended VLAN traffic if another switch carries those VLANs. It also contradicts least-privilege trunking.

### Corrected approach

```python
allowed = ",".join(str(vlan["vlan_id"]) for vlan in validated_vlans)
commands = [
    "switchport mode trunk",
    "switchport trunk native vlan 999",
    f"switchport trunk allowed vlan {allowed}",
    "switchport nonegotiate",
]
```

### Verification and packet consequence

Generate a trunk from VLAN IDs 10, 20, and 40 and assert that the allowed list is exactly `10,20,40`; inspect that no `all` command is present. A tagged frame for VLAN 30 should not cross this trunk. An unconstrained trunk could carry that frame, allowing traffic to reach a downstream segment that was not intended to receive it. Always confirm the native VLAN is consistently configured at both ends.
