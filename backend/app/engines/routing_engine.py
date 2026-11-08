def recommend_routing(*, sites: int, subnet_count: int, cloud: bool = False, multi_as: bool = False,
                      redundancy: bool = False, requirement: str = "auto") -> dict:
    multi = sites > 1 or cloud or multi_as or subnet_count >= 50
    use_bgp = cloud or multi_as
    if requirement.lower() == "static":
        protocol, reason = "Static routing", "Explicitly requested; appropriate only for small, stable domains with an operational plan for failover."
    elif use_bgp:
        protocol = "Multi-Area OSPF + eBGP" if sites > 1 else "eBGP"
        reason = "BGP is used at the cloud or autonomous-system boundary; OSPF provides internal reachability and limits external route policy to that boundary."
    elif multi:
        protocol, reason = "Multi-Area OSPF", "Multiple sites or a larger subnet domain benefit from hierarchical areas and controlled route summarization."
    else:
        protocol, reason = "Single-Area OSPF (Area 0)", "A single routing domain below 50 subnets is a manageable scope for one OSPF area and SPF-based link-state routing."
    return {"decision": protocol, "input_parameters": {"sites": sites, "subnet_count": subnet_count, "cloud": cloud, "multi_as": multi_as, "redundancy": redundancy},
            "condition": f"multi_site={sites > 1}; cloud_boundary={cloud}; multi_as={multi_as}; subnet_count={subnet_count}",
            "explanation": reason + " OSPF computes shortest paths from link-state information; BGP applies path-vector policy between routing domains.",
            "mathematical_justification": "Area design is based on topology boundaries and operational scale, not endpoint count alone.",
            "standards": ["RFC 2328 (OSPFv2)", "RFC 4271 (BGP-4)"],
            "advantages": ["Separates internal routing from external policy where applicable", "Supports redundant paths" if redundancy else "Keeps the routing domain simple"],
            "limitations": ["Convergence depends on timers, topology, and implementation", "Route policy and summarization require operator validation"],
            "alternatives": ["Static routes for very small stable networks", "OSPF-only where no external AS or cloud routing boundary exists"]}
