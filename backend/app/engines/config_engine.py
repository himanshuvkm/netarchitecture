from ipaddress import ip_network
import re
import io, zipfile


def generate_configs(analysis: dict) -> dict[str, str]:
    name = re.sub(r"[^A-Za-z0-9-]", "-", analysis.get("network_name", "NetArchitect").strip())[:30].strip("-") or "NetArchitect"
    vlans = analysis.get("vlans", [])
    rows = analysis.get("vlsm", {}).get("allocations", [])
    used_vlans = {v["vlan_id"] for v in vlans}
    native_candidates = [v for v in range(4094, 1, -1) if v not in used_vlans]
    if not native_candidates:
        raise ValueError("No unused VLAN ID remains for the native trunk VLAN")
    native_vlan = native_candidates[0]
    lines = [f"! Device: {name}-DIST-01", "! Purpose: Layer 3 distribution; generated from validated design inputs.",
             "! Assumptions: Cisco IOS-like syntax; verify platform support and interface mapping before deployment.", "! Warnings: Replace credentials, confirm VLAN membership and ACL policy, and review change impact.",
             "hostname " + name + "-DIST-01", "no ip domain-lookup", "ip routing", "spanning-tree mode rapid-pvst", "spanning-tree portfast default", "spanning-tree bpduguard default"]
    lines += [f"vlan {native_vlan}", " name NATIVE-BLACKHOLE"]
    for v in vlans:
        vid, vname = v["vlan_id"], v["name"]
        lines += [f"vlan {vid}", f" name {vname[:32]}"]
    for row in rows:
        lines += [f"interface vlan {row['vlan_id']}", f" description {row['vlan_name']} gateway", f" ip address {row['gateway']} {row['subnet_mask']}", " no shutdown"]
    if rows:
        lines += ["interface GigabitEthernet1/0/48", " description Uplink trunk - restrict allowed VLANs", " switchport mode trunk", f" switchport trunk native vlan {native_vlan}", " switchport trunk allowed vlan " + ",".join(str(r["vlan_id"]) for r in rows), " switchport nonegotiate", " no shutdown"]
    lines += ["ip domain-name netarchitect.local", "username netadmin privilege 15 secret <SET_SECRET_SECURELY>", "crypto key generate rsa modulus 2048", "ip ssh version 2", "line vty 0 4", " transport input ssh", " login local", "! Replace the secret placeholder before applying this configuration."]
    route = analysis.get("routing", {}).get("decision", "")
    if "Single-Area OSPF" in route:
        root = analysis.get("root_cidr", "10.0.0.0/8")
        try:
            wildcard = str(ip_network(root, strict=True).hostmask)
            addr = str(ip_network(root, strict=True).network_address)
            lines += ["router ospf 10", " router-id 10.255.255.1", f" network {addr} {wildcard} area 0", " passive-interface default"]
        except ValueError: pass
    if "eBGP" in route:
        lines += ["! eBGP template: substitute peer IP and AS from the provider / cloud handoff.", "! Apply inbound and outbound route policies before enabling the neighbor.", "router bgp 65010", " bgp log-neighbor-changes", " neighbor <PEER_IP> remote-as <PEER_AS>", " address-family ipv4", "  neighbor <PEER_IP> activate", "  neighbor <PEER_IP> prefix-list NETARCH-IN in"]
        lines += [f"  aggregate-address {summary} summary-only" for summary in analysis.get("route_summarization", {}).get("exact_aggregates", [])]
        lines += [" exit-address-family", "! Aggregates require every component route in the BGP table; define route filters before production."]
    if analysis.get("vpn"):
        lines += ["! IPsec site-to-site template. Replace peer, transform, and key through a secure deployment process.", "crypto ikev2 proposal NETARCH-IKEV2", " encryption aes-cbc-256", " integrity sha256", " group 14", "crypto ikev2 policy 10", " proposal NETARCH-IKEV2", "crypto ikev2 keyring NETARCH-KEYRING", " peer REMOTE-SITE", "  address <REMOTE_PEER_IP>", "  pre-shared-key <INJECT_SECRET_SECURELY>", "! Bind an IKEv2 profile and IPsec transform to the platform-specific tunnel interface."]
    if analysis.get("qos"):
        lines += ["! QoS starter policy: classify and mark at the trusted edge; validate provider class mapping.", "class-map match-any NETARCH-REALTIME", " match dscp ef", "policy-map NETARCH-WAN-OUT", " class NETARCH-REALTIME", "  priority percent 20", " class class-default", "  fair-queue", "! Apply service-policy output to the correct WAN interface after bandwidth review."]
    policies = analysis.get("security_policies", [])
    for row in rows:
        vlan_policies = [p for p in policies if p["source_vlan_id"] == row["vlan_id"]]
        is_iot = "iot" in row["vlan_name"].lower()
        if not vlan_policies and not is_iot: continue
        acl = f"NETARCH-VLAN-{row['vlan_id']}-IN"
        lines += [f"! Inbound policy for VLAN {row['vlan_id']}; IOS applies implicit deny after the listed entries.", f"ip access-list extended {acl}"]
        for policy in vlan_policies:
            destination = ip_network(policy["destination_cidr"], strict=True)
            lines += [f" {policy['action']} {policy['protocol']} any {destination.network_address} {destination.hostmask}"]
        if not vlan_policies and is_iot:
            root = ip_network(analysis["root_cidr"], strict=True)
            lines += [f" deny ip any {root.network_address} {root.hostmask}", " permit ip any any", "! IoT can reach non-root destinations; narrow this egress rule to approved services."]
        lines += [f"interface Vlan{row['vlan_id']}", f" ip access-group {acl} in"]
    default_vlan = vlans[0]["vlan_id"] if vlans else 10
    switch = ["! Device: access switch", "! Purpose: secured access and uplink trunk template", "! Assumptions: Set access ports after confirming endpoint inventory.", "hostname " + name + "-ACCESS-01", "spanning-tree mode rapid-pvst", "spanning-tree bpduguard default", f"vlan {native_vlan}", " name NATIVE-BLACKHOLE", "interface range GigabitEthernet1/0/1-47", " switchport mode access", f" switchport access vlan {default_vlan}", " spanning-tree portfast", " spanning-tree bpduguard enable", " shutdown", "! Enable only assigned ports after setting the correct VLAN.", "interface GigabitEthernet1/0/48", " switchport mode trunk", f" switchport trunk native vlan {native_vlan}", " switchport trunk allowed vlan " + (",".join(str(v["vlan_id"]) for v in vlans) or "10"), " switchport nonegotiate", " no shutdown", "ip domain-name netarchitect.local", "username netadmin privilege 15 secret <SET_SECRET_SECURELY>", "crypto key generate rsa modulus 2048", "ip ssh version 2", "line vty 0 4", " transport input ssh", " login local", "! Replace the secret placeholder and confirm the switch interface map before deployment."]
    management = next((row for row in rows if "management" in row["vlan_name"].lower()), None)
    if management:
        management_ip = str(int(ip_network(management["network_cidr"]).network_address) + 2)
        switch += [f"interface Vlan{management['vlan_id']}", " description Switch management", f" ip address {management_ip} {management['subnet_mask']}", " no shutdown", f"ip default-gateway {management['gateway']}", "! Reserve this SVI address from endpoint assignment and use a unique address on each cloned switch."]
    else:
        switch += ["! Configure a management SVI and default gateway after identifying the management VLAN."]
    if analysis.get("poe"):
        switch.insert(switch.index("interface range GigabitEthernet1/0/1-47"), "! PoE is requested; assign AP ports only after validating switch model and total power budget.")
    router = ["! Device: WAN edge router", "! Purpose: routing and carrier / cloud handoff template", "! Assumptions: Addressing and interface identifiers are deployment inputs.", "! Warnings: Verify carrier QoS, optical budget, route policy, and platform syntax before deployment.", "hostname " + name + "-EDGE-01", "no ip domain-lookup"]
    if "OSPF" in route:
        router += ["router ospf 10", " router-id 10.255.255.254", " passive-interface default"]
        if "Multi-Area" in route:
            router += ["! Multi-area template: map site-facing interfaces to areas and configure area range summaries at ABRs.", "! Site-to-VLAN mapping was not provided, so area assignments are intentionally left for design completion."]
        else:
            router += ["! Add explicitly addressed transit interfaces with the correct area."]
    if "eBGP" in route:
        router += ["router bgp 65010", " bgp log-neighbor-changes", " neighbor <PEER_IP> remote-as <PEER_AS>", " address-family ipv4", "  neighbor <PEER_IP> activate", "  neighbor <PEER_IP> prefix-list NETARCH-IN in"]
        router += [f"  aggregate-address {summary} summary-only" for summary in analysis.get("route_summarization", {}).get("exact_aggregates", [])]
        router += [" exit-address-family", "! Aggregates require all component routes in BGP; configure explicit route filters and maximum-prefix before peer activation."]
    if analysis.get("vpn"):
        router += ["! IPsec/IKEv2 site-to-site template; inject secrets securely.", "crypto ikev2 proposal NETARCH-IKEV2", " encryption aes-cbc-256", " integrity sha256", " group 14", "crypto ikev2 keyring NETARCH-KEYRING", " peer REMOTE-SITE", "  address <REMOTE_PEER_IP>", "  pre-shared-key <INJECT_SECRET_SECURELY>"]
    if analysis.get("qos"):
        router += ["class-map match-any NETARCH-REALTIME", " match dscp ef", "policy-map NETARCH-WAN-OUT", " class NETARCH-REALTIME", "  priority percent 20", " class class-default", "  fair-queue", "! Apply to the provider-facing interface after validating CIR and traffic policy."]
    return {"layer3_switch.txt": "\n".join(lines) + "\n", "access_switch.txt": "\n".join(switch) + "\n", "wan_router.txt":"\n".join(router)+"\n"}


def export_zip(configs: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in configs.items(): archive.writestr(filename, content)
    return output.getvalue()
