"""IPv4 VLSM allocation using integer arithmetic and ipaddress validation."""
from ipaddress import IPv4Network, IPv4Address, ip_network


class AllocationError(ValueError):
    pass


def prefix_for_hosts(hosts: int) -> int:
    if isinstance(hosts, bool) or hosts <= 0:
        raise AllocationError("Host requirement must be a positive integer")
    # Reserve a usable gateway plus the requested endpoint addresses, and network/broadcast.
    needed = hosts + 1 + 2
    bits = (needed - 1).bit_length()
    if bits > 32:
        raise AllocationError("Host requirement exceeds IPv4 address capacity")
    return 32 - bits


def subnet_details(network: IPv4Network, vlan_id: int, name: str, hosts: int) -> dict:
    total = network.num_addresses
    if network.prefixlen == 32:
        first = last = gateway = network.network_address
        usable = 1
    elif network.prefixlen == 31:
        first, last = network.network_address, network.broadcast_address
        gateway, usable = first, 2
    else:
        first, last = network.network_address + 1, network.broadcast_address - 1
        gateway, usable = first, max(0, total - 2)
    calculation = f"{hosts} endpoint hosts + 1 gateway require {hosts+1} usable addresses; ordinary IPv4 LANs also reserve network and broadcast addresses. Allocated block: {total} addresses ({network})."
    standards = ["RFC 4632 (CIDR)" ]
    if network.prefixlen == 31: standards.append("RFC 3021 (/31 point-to-point links)")
    return {"vlan_id": vlan_id, "vlan_name": name, "required_hosts": hosts, "network_cidr": str(network),
            "subnet_mask": str(network.netmask), "wildcard_mask": str(network.hostmask), "gateway": str(gateway),
            "first_usable": str(first), "last_usable": str(last), "broadcast": str(network.broadcast_address),
            "total_addresses": total, "usable_addresses": usable,
            "utilization_percent": round((hosts / usable * 100), 2) if usable else 0,
            "required_addresses_including_gateway": hosts + 1,
            "prefix_calculation": calculation,
            "decision": f"Allocate {network} to VLAN {name}",
            "input_parameters": {"vlan_id":vlan_id,"vlan_name":name,"required_endpoint_hosts":hosts,"gateway_policy":"first usable address"},
            "condition": f"Choose the smallest power-of-two block with at least {hosts+1} usable addresses including one gateway; align the network boundary and avoid all allocated/reserved ranges.",
            "explanation": "VLAN requests are allocated from largest to smallest so small blocks cannot fragment space needed by larger requirements.",
            "mathematical_justification": calculation,
            "standards": standards,
            "advantages": ["Address block is aligned and does not overlap another allocation", "Gateway is reserved inside the usable host range"],
            "limitations": ["A power-of-two block can leave usable addresses unassigned", "The gateway address must be configured consistently on the Layer 3 device"],
            "alternatives": ["Choose a different root CIDR or host budget if address space is exhausted"]}


def allocate_vlsm(root_cidr: str, vlans: list[dict], reserved: list[str] | None = None) -> dict:
    try:
        root = ip_network(root_cidr, strict=True)
    except ValueError as exc:
        raise AllocationError(f"Invalid root CIDR: {exc}") from exc
    if not isinstance(root, IPv4Network):
        raise AllocationError("Only IPv4 CIDRs are supported")
    ids = [v.get("vlan_id") for v in vlans]
    for vlan in vlans:
        vid = vlan.get("vlan_id")
        if isinstance(vid, bool) or not isinstance(vid, int) or not 1 <= vid <= 4094:
            raise AllocationError(f"Invalid VLAN ID {vid!r}; expected an integer from 1 through 4094")
        if not isinstance(vlan.get("name"), str) or not vlan["name"].strip():
            raise AllocationError("Every VLAN requires a non-empty name")
    if len(ids) != len(set(ids)):
        raise AllocationError("Duplicate VLAN IDs are not allowed")
    requests = []
    for v in vlans:
        hosts = v.get("hosts", 0)
        if isinstance(hosts, bool) or not isinstance(hosts, int) or hosts <= 0:
            raise AllocationError(f"VLAN {v.get('name', '?')}: host count must be a positive integer")
        prefix = prefix_for_hosts(hosts)
        if prefix < root.prefixlen:
            raise AllocationError(f"VLAN {v.get('name', '?')} requires more addresses than root {root} can provide")
        requests.append((v, prefix))
    blocked: list[IPv4Network] = []
    for cidr in reserved or []:
        try:
            n = ip_network(cidr, strict=True)
        except ValueError as exc:
            raise AllocationError(f"Invalid reserved CIDR {cidr}: {exc}") from exc
        if not isinstance(n, IPv4Network) or not n.subnet_of(root):
            raise AllocationError(f"Reserved subnet {cidr} must be within {root}")
        blocked.append(n)
    allocated: list[IPv4Network] = []
    cursor = int(root.network_address)
    root_end = int(root.broadcast_address)
    for v, prefix in sorted(requests, key=lambda pair: (pair[1], pair[0].get("vlan_id", 0))):
        size = 1 << (32 - prefix)
        candidate = (cursor + size - 1) & ~(size - 1)
        while True:
            if candidate + size - 1 > root_end:
                raise AllocationError(f"Address space exhausted while allocating VLAN {v.get('name', '?')} ({v['hosts']} hosts) in {root}")
            network = IPv4Network((candidate, prefix))
            collision = next((n for n in blocked + allocated if network.overlaps(n)), None)
            if collision is None:
                break
            candidate = int(collision.broadcast_address) + 1
            candidate = (candidate + size - 1) & ~(size - 1)
        allocated.append(network)
        cursor = int(network.broadcast_address) + 1
    rows = [subnet_details(n, v["vlan_id"], v["name"], v["hosts"]) for (v, _), n in zip(sorted(requests, key=lambda pair: (pair[1], pair[0].get("vlan_id", 0))), allocated)]
    return {"root_network": str(root), "allocations": rows, "overlap_valid": all(not a.overlaps(b) for i, a in enumerate(allocated) for b in allocated[i+1:]),
            "allocated_addresses": sum(n.num_addresses for n in allocated), "root_addresses": root.num_addresses}
