from ipaddress import collapse_addresses, ip_network
from .vlsm_engine import allocate_vlsm
from .media_engine import LinkRequest, recommend_media
from .routing_engine import recommend_routing

def analyze(data: dict) -> dict:
    vlans = [v if isinstance(v, dict) else v.model_dump() for v in data.get("vlans", [])]
    links = [l if isinstance(l, dict) else l.model_dump() for l in data.get("links", [])]
    allocation = allocate_vlsm(data["root_cidr"], vlans, data.get("reserved_subnets"))
    exact_summaries = [str(n) for n in collapse_addresses([ip_network(row["network_cidr"]) for row in allocation["allocations"]])]
    media = [recommend_media(LinkRequest(l["distance_m"], l.get("requested_medium"), l.get("bandwidth_gbps", 10), l["name"])) for l in links]
    routing = recommend_routing(sites=data.get("sites", 1), subnet_count=len(vlans), cloud=data.get("cloud", False),
        multi_as=data.get("routing_requirement", "auto").lower() == "bgp", redundancy=data.get("redundancy", False), requirement=data.get("routing_requirement", "auto"))
    site_count = data.get("buildings", 1) if data.get("network_type") == "LAN" else data.get("sites", 1)
    router_count = data.get("routers", 1)
    switch_count = max(1 + 2 * site_count, data.get("switches", 1 + 2 * site_count))
    topology_nodes = [{"id":f"edge-{i+1}","label":f"WAN Edge Router {i+1}","type":"router"} for i in range(router_count)] + [{"id":"core","label":"Core L3 Switch","type":"l3-switch"}]
    topology_edges = [{"source":f"edge-{i+1}","target":"core","label":"Routed core uplink","media":"Ethernet handoff","redundant":data.get("redundancy",False)} for i in range(router_count)]
    access_total = max(site_count, switch_count - site_count - 1)
    access_per_site = [access_total // site_count + (1 if i < access_total % site_count else 0) for i in range(site_count)]
    for i in range(site_count):
        sid = f"site-{i+1}"
        site_label = ((data.get("building_names") or [])[i] if i < len(data.get("building_names", [])) else f"Building {i+1}") if data.get("network_type") == "LAN" else ((data.get("site_names") or [])[i] if i < len(data.get("site_names", [])) else f"Site {i+1}")
        topology_nodes += [{"id":sid,"label":f"{site_label} Distribution","type":"l3-switch"},
                           {"id":f"endpoints-{i+1}","label":f"{site_label} Endpoints","type":"endpoint-group"}]
        for switch_i in range(access_per_site[i]):
            topology_nodes.append({"id":f"access-{i+1}-{switch_i+1}","label":f"{site_label} Access {switch_i+1}","type":"l2-switch"})
        li = min(i, len(links)-1) if links else None
        link = links[li] if li is not None else {}
        physical = media[li] if li is not None else {}
        carrier = "EVPL / " if data.get("network_type") == "MAN" else ""
        topology_edges += [{"source":"core","target":sid,"label":carrier+(link.get("name",f"Site {i+1} uplink")),
                            "media":physical.get("medium","planned uplink"),"distance_m":link.get("distance_m"),
                            "bandwidth_gbps":link.get("bandwidth_gbps"),"redundant":data.get("redundancy",False)},
                           ]
        for switch_i in range(access_per_site[i]):
            access_id=f"access-{i+1}-{switch_i+1}"
            topology_edges += [{"source":sid,"target":access_id,"label":"802.1Q campus trunk","media":"Ethernet","vlans":[v["vlan_id"] for v in vlans]},
                               {"source":access_id,"target":f"endpoints-{i+1}","label":"Access ports","media":"Cat6a (<=100 m planning class)","vlans":[v["vlan_id"] for v in vlans]}]
    if any("server" in v["name"].lower() for v in vlans):
        topology_nodes.append({"id":"servers","label":"Server Segment","type":"server"})
        topology_edges.append({"source":"core","target":"servers","label":"Server VLAN SVI","media":"Ethernet","vlans":[v["vlan_id"] for v in vlans if "server" in v["name"].lower()]})
    if data.get("cloud"):
        topology_nodes.append({"id":"cloud","label":"Cloud VPC","type":"cloud"})
        topology_edges.append({"source":"edge-1" if router_count else "core","target":"cloud","label":"IPsec VPN / cloud interconnect","media":"Encrypted overlay","redundant":data.get("redundancy",False)})
    architecture = ("Hierarchical campus core, distribution, and access" if data.get("network_type") == "LAN" else
                    "Metro EVPL WAN with redundant site paths" if data.get("network_type") == "MAN" and data.get("redundancy") else
                    "Global routed WAN with cloud VPN boundary" if data.get("cloud") else
                    "Multi-site routed WAN" if site_count > 1 else "Single-site routed network")
    topology = {"decision":architecture,"input_parameters":{"network_type":data.get("network_type"),"sites":data.get("sites",1),"buildings":data.get("buildings",1),"switches":data.get("switches",0),"routers":router_count,"redundancy":data.get("redundancy",False),"cloud":data.get("cloud",False),"vpn":data.get("vpn",False)},
                "condition":"The diagram uses site/building counts, switch and router counts, link distances/media, VLAN IDs, and cloud/redundancy flags from the request.",
                "explanation":"A hierarchical layout separates core routing, site distribution, access switching, and endpoint groups. Site uplinks and optional cloud edges reflect supplied link and resilience inputs.",
                "mathematical_justification":f"The model represents {router_count} edge routers, {switch_count} switches (including one core and at least one distribution/access pair per site), and {data.get('endpoints',0)} endpoints.",
                "standards":["IEEE 802.1Q (VLAN tagging)"],"advantages":["Separates access and routing roles","Shows the requested site and link relationships"],
                "limitations":["Device placement is an initial logical topology; exact rack, port, and carrier handoff mappings are not supplied"],
                "alternatives":["Collapsed core for a smaller campus","Full mesh or provider-managed WAN where carrier and routing constraints support it"],
                "nodes":topology_nodes,"edges":topology_edges}
    warning = []
    if data.get("switches", switch_count) < 1 + 2 * site_count:
        warning.append(f"The topology requires at least {1 + 2 * site_count} switches for one core, one distribution, and one access switch per site; the requested count is {data.get('switches', 0)}.")
    if data.get("latency_ms") and data.get("latency_ms") <= 5:
        warning.append("Latency is a design target only. A sub-5 ms result requires a carrier SLA and deployment measurement; this planner cannot guarantee it.")
    if data.get("vpn"): warning.append("IPsec values are generated as templates; populate peer addresses and keys using approved secret handling.")
    if data.get("poe"): warning.append("PoE requested: verify endpoint IEEE class, switch per-port support, total power budget, and redundant power supplies; AP ports are not inferred from this VLAN plan.")
    if "Multi-Area OSPF" in routing["decision"]: warning.append("Site-to-VLAN mapping is not supplied; assign OSPF areas and summaries at the site ABRs during detailed design.")
    policies = [{**p, "destination_cidr":str(p["destination_cidr"])} for p in data.get("security_policies", [])]
    if any("iot" in v["name"].lower() and not any(p["source_vlan_id"] == v["vlan_id"] for p in policies) for v in vlans):
        warning.append("The generated IoT ACL blocks traffic to the root network and permits other destinations; review and narrow egress policy for deployment.")
    return {"network_name":data.get("network_name","NetArchitect"),"network_type":data.get("network_type"),"sites":data.get("sites",1),"buildings":data.get("buildings",1),
        "endpoints":data.get("endpoints",0),"root_cidr":data["root_cidr"],"vlans":vlans,"vlsm":allocation,"media":media,
        "routing":routing,"topology":topology,"route_summarization":{"component_routes":[r["network_cidr"] for r in allocation["allocations"]],"exact_aggregates":exact_summaries,"reduces_route_count":len(exact_summaries)<len(allocation["allocations"]),"root_candidate":str(ip_network(data["root_cidr"],strict=True)),"explanation":"These exact aggregates cover only fully allocated adjacent blocks. The root CIDR is a broader summary candidate only when one site owns the range and safely handles unused destinations; site-level summarization requires a site-to-VLAN mapping."},"warnings":warning,"resiliency":"Redundant paths requested" if data.get("redundancy") else "Single path assumptions",
        "cloud":data.get("cloud",False),"vpn":data.get("vpn",False),"qos":data.get("qos",False),"poe":data.get("poe",False),"redundancy":data.get("redundancy",False),"switches":data.get("switches",0),"routers":data.get("routers",0),"network_type":data.get("network_type"),"security_policies":policies}
