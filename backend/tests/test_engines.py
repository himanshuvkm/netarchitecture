import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.engines.media_engine import LinkRequest, recommend_media, PhysicalDistanceViolationError
from app.engines.vlsm_engine import allocate_vlsm, AllocationError, subnet_details
from ipaddress import ip_network
from app.engines.config_engine import generate_configs
from app.engines.routing_engine import recommend_routing
from app.profiles.catalog import PROFILES

client=TestClient(app)

@pytest.mark.parametrize("d,medium,optic",[(100,"Cat6a copper","10GBASE-T"),(101,"OM4 multimode fiber","10GBASE-SR"),(400,"OM4 multimode fiber","10GBASE-SR"),(401,"OS2 single-mode fiber","10GBASE-LR")])
def test_media_boundaries(d,medium,optic):
    r=recommend_media(LinkRequest(d)); assert (r["medium"],r["transceiver"])==(medium,optic)

def test_copper_violation():
    with pytest.raises(PhysicalDistanceViolationError,match="100 m"): recommend_media(LinkRequest(101,"copper"))

def test_negative_distance():
    with pytest.raises(ValueError): recommend_media(LinkRequest(-1))
    with pytest.raises(ValueError): recommend_media(LinkRequest(float("nan")))
    with pytest.raises(ValueError,match="10 Gbps"):
        recommend_media(LinkRequest(100, bandwidth_gbps=40))

def test_engineered_long_distance_and_route_summary():
    rec=recommend_media(LinkRequest(50000))
    assert "engineered OS2" in rec["medium"] and "no direct LR/ER" in rec["transceiver"]

def test_vlsm_order_non_overlap_and_masks():
    r=allocate_vlsm("192.168.0.0/16",[{"vlan_id":1,"name":"Small","hosts":50},{"vlan_id":2,"name":"Large","hosts":500}])
    assert r["overlap_valid"] and r["allocations"][0]["vlan_id"]==2
    a=r["allocations"][0]; assert a["wildcard_mask"]=="0.0.1.255" and a["gateway"]==a["first_usable"]

@pytest.mark.parametrize("hosts,prefix",[(1,30),(2,29),(3,29),(100,25)])
def test_prefix_sizes(hosts,prefix):
    a=allocate_vlsm("10.0.0.0/24",[{"vlan_id":1,"name":"T","hosts":hosts}])["allocations"][0]
    assert int(a["network_cidr"].split("/")[1])==prefix
    net=ip_network(a["network_cidr"])
    assert a["broadcast"]==str(net.broadcast_address)
    assert a["first_usable"]==str(a["gateway"])
    assert a["wildcard_mask"]==str(net.hostmask)

@pytest.mark.parametrize("cidr,usable",[("10.0.0.0/30",2),("10.0.0.0/31",2),("10.0.0.1/32",1)])
def test_special_prefix_metadata(cidr,usable):
    row=subnet_details(ip_network(cidr),7,"edge",1)
    assert row["usable_addresses"]==usable and row["total_addresses"]==(1 << (32-int(cidr.split('/')[1])))

def test_zero_root_and_ipv6():
    assert allocate_vlsm("0.0.0.0/0",[{"vlan_id":2,"name":"first","hosts":10}])["allocations"][0]["network_cidr"]=="0.0.0.0/28"
    with pytest.raises(AllocationError): allocate_vlsm("2001:db8::/32",[{"vlan_id":2,"name":"v6","hosts":2}])

@pytest.mark.parametrize("root,vlans",[("bad",[]),("10.0.0.0/24",[{"vlan_id":1,"name":"x","hosts":0}]),("10.0.0.0/24",[{"vlan_id":1,"name":"x","hosts":-1}])])
def test_invalid_vlsm(root,vlans):
    with pytest.raises(AllocationError): allocate_vlsm(root,vlans)

def test_reserved_and_exhaustion():
    r=allocate_vlsm("10.0.0.0/24",[{"vlan_id":1,"name":"x","hosts":10}], ["10.0.0.0/28"])
    assert r["allocations"][0]["network_cidr"]=="10.0.0.16/28"
    with pytest.raises(AllocationError): allocate_vlsm("10.0.0.0/30",[{"vlan_id":1,"name":"x","hosts":10}])

def test_duplicate_vlan():
    with pytest.raises(AllocationError,match="Duplicate"): allocate_vlsm("10.0.0.0/24",[{"vlan_id":1,"name":"x","hosts":2},{"vlan_id":1,"name":"y","hosts":2}])
    with pytest.raises(AllocationError,match="VLAN ID"):
        allocate_vlsm("10.0.0.0/24",[{"vlan_id":4095,"name":"invalid","hosts":2}])

def test_routing_rules():
    assert "Single-Area" in recommend_routing(sites=1,subnet_count=4)["decision"]
    assert "Multi-Area" in recommend_routing(sites=3,subnet_count=4)["decision"]
    assert "eBGP" in recommend_routing(sites=2,subnet_count=4,cloud=True)["decision"]

def test_profile_configs_have_scoped_trunks_and_protocols():
    campus=client.post("/api/analyze",json=PROFILES["campus-lan"]).json()
    c=generate_configs(campus)
    assert "switchport trunk allowed vlan 10,20,30,40,50" in c["access_switch.txt"]
    assert "switchport trunk allowed vlan all" not in c["access_switch.txt"]
    assert "interface Vlan10" in c["access_switch.txt"] and "ip default-gateway" in c["access_switch.txt"]
    assert "transport input ssh" in c["access_switch.txt"]
    assert "router ospf 10" in c["layer3_switch.txt"]
    global_design=client.post("/api/analyze",json=PROFILES["global-wan"]).json()
    wc=generate_configs(global_design)["wan_router.txt"]
    lc=generate_configs(global_design)["layer3_switch.txt"]
    assert "router bgp 65010" in wc and "crypto ikev2" in wc and "NETARCH-VLAN-20-IN" in lc
    assert global_design["route_summarization"]["root_candidate"]=="10.30.0.0/16"

@pytest.mark.parametrize("pid",PROFILES)
def test_profile_e2e(pid):
    response=client.post("/api/analyze",json=PROFILES[pid]); assert response.status_code==200
    data=response.json(); assert data["vlsm"]["overlap_valid"] and data["topology"]["nodes"]

def test_expected_profile_architectures():
    campus=client.post("/api/analyze",json=PROFILES["campus-lan"]).json()
    assert len([n for n in campus["topology"]["nodes"] if n["type"]=="l3-switch" and any(building in n["label"] for building in ("North","South","West"))])==3
    assert [m["medium"] for m in campus["media"]]==["Cat6a copper","OM4 multimode fiber","OM4 multimode fiber"]
    assert "Single-Area" in campus["routing"]["decision"]
    metro=client.post("/api/analyze",json=PROFILES["metro-man"]).json()
    assert all(m["medium"]=="OS2 single-mode fiber" for m in metro["media"])
    assert any("sub-5 ms" in warning for warning in metro["warnings"])
    assert all(edge["redundant"] for edge in metro["topology"]["edges"] if "EVPL" in edge["label"])
    global_design=client.post("/api/analyze",json=PROFILES["global-wan"]).json()
    assert "cloud" in [node["id"] for node in global_design["topology"]["nodes"]]
    assert "eBGP" in global_design["routing"]["decision"]

def test_custom_profile_and_physical_api_validation():
    custom={**PROFILES["campus-lan"],"network_name":"Custom Viva Lab","root_cidr":"172.16.0.0/16","sites":1,"site_names":["Lab"],"buildings":1,"building_names":["Main Lab"],"switches":4,"routers":1}
    response=client.post("/api/analyze",json=custom)
    assert response.status_code==200 and response.json()["vlsm"]["root_network"]=="172.16.0.0/16"
    invalid=client.post("/api/recommendations/media",json={"distance_m":101,"requested_medium":"copper"})
    assert invalid.status_code==422 and "attenuation" in invalid.json()["detail"]["message"]

def test_invalid_api_and_config_export():
    assert client.post("/api/analyze",json={"root_cidr":"bad"}).status_code==422
    payload=PROFILES["campus-lan"]
    assert client.post("/api/configurations/generate",json=payload).status_code==200
    assert client.post("/api/configurations/export",json=payload).headers["content-type"]=="application/zip"

def test_user_security_policy_and_conflict_validation():
    payload={**PROFILES["campus-lan"],"security_policies":[{"name":"BlockAdmin","source_vlan_id":20,"destination_cidr":"192.168.1.0/24","action":"deny","protocol":"tcp"}]}
    response=client.post("/api/configurations/generate",json=payload)
    assert response.status_code==200
    config=response.json()["files"]["layer3_switch.txt"]
    assert "NETARCH-VLAN-20-IN" in config and "deny tcp any 192.168.1.0 0.0.0.255" in config
    payload["security_policies"].append({"name":"AllowOverlap","source_vlan_id":20,"destination_cidr":"192.168.1.128/25","action":"permit","protocol":"ip"})
    assert client.post("/api/analyze",json=payload).status_code==422
