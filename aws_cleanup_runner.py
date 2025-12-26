# === AWS VPC Cleanup Runner (intermediate) ===
import boto3, logging
from botocore.exceptions import ClientError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    filename="cleanup.log"  # writes logs to file for audit
)

def ask_region_list():
    s = input("Enter AWS regions (comma separated, e.g., us-east-1, ap-south-1): ").strip()
    regions = [r.strip() for r in s.split(",") if r.strip()]
    if not regions: raise ValueError("At least one region is required.")
    return regions

def ask_terminate_instances() -> bool:
    return input("Terminate EC2 instances in each non-default VPC? (yes/no): ").strip().lower() in ("y","yes")

def ask_dry_run() -> bool:
    return input("Dry-run (preview only)? (yes/no): ").strip().lower() in ("y","yes")

def confirm_delete() -> bool:
    print("\nSAFETY CHECK: Type DELETE to proceed with destructive actions, or press Enter to cancel.")
    return input("Confirm: ").strip() == "DELETE"

def build_ec2(region): return boto3.client("ec2", region_name=region)

def skip_vpc_by_tags(v):
    # Tag-based safety: skip VPC tagged env=prod or keep=true
    tags = {t["Key"]: t.get("Value","") for t in v.get("Tags", [])}
    if tags.get("env","").lower()=="prod" or tags.get("keep","").lower()=="true":
        return True
    return False

def terminate_instances(ec2, vpc_id, DRY_RUN):
    inst_ids = []
    res = ec2.describe_instances(Filters=[{"Name":"vpc-id","Values":[vpc_id]}])
    for r in res.get("Reservations", []):
        for i in r.get("Instances", []):
            state = i.get("State", {}).get("Name")
            if state not in ("terminated","shutting-down"):
                inst_ids.append(i["InstanceId"])
    if inst_ids:
        logging.info(f"Terminate -> {inst_ids} in {vpc_id}")
        if not DRY_RUN:
            ec2.terminate_instances(InstanceIds=inst_ids)
            ec2.get_waiter('instance_terminated').wait(InstanceIds=inst_ids)
            logging.info("Instances terminated.")
    else:
        logging.info(f"No active instances in {vpc_id}")

def delete_vpc_endpoints(ec2, vpc_id, DRY_RUN):
    eps = ec2.describe_vpc_endpoints(Filters=[{"Name":"vpc-id","Values":[vpc_id]}]).get("VpcEndpoints",[])
    for ep in eps:
        ep_id = ep["VpcEndpointId"]
        logging.info(f"VPCE -> delete {ep_id}")
        if not DRY_RUN: ec2.delete_vpc_endpoints(VpcEndpointIds=[ep_id])

def delete_nat_gateways_and_eips(ec2, vpc_id, DRY_RUN):
    try:
        ngws = ec2.describe_nat_gateways(Filters=[{"Name":"vpc-id","Values":[vpc_id]}]).get("NatGateways",[])
    except ClientError as e:
        logging.warning(f"NAT describe failed: {e}"); ngws=[]
    for ngw in ngws:
        ngw_id = ngw["NatGatewayId"]
        logging.info(f"NAT -> delete {ngw_id}")
        if not DRY_RUN: ec2.delete_nat_gateway(NatGatewayId=ngw_id)
    # release unassociated EIPs
    try:
        addrs = ec2.describe_addresses().get("Addresses",[])
        for a in addrs:
            if "AssociationId" not in a and "AllocationId" in a:
                alloc = a["AllocationId"]
                logging.info(f"EIP -> release {alloc}")
                if not DRY_RUN: ec2.release_address(AllocationId=alloc)
    except ClientError as e:
        logging.warning(f"EIP describe failed: {e}")

def detach_delete_igws(ec2, vpc_id, DRY_RUN):
    igws = ec2.describe_internet_gateways(Filters=[{"Name":"attachment.vpc-id","Values":[vpc_id]}]).get("InternetGateways",[])
    for igw in igws:
        igw_id = igw["InternetGatewayId"]
        logging.info(f"IGW -> detach & delete {igw_id}")
        if not DRY_RUN:
            try: ec2.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
            except ClientError as e: logging.warning(f"Detach IGW failed: {e}")
            try: ec2.delete_internet_gateway(InternetGatewayId=igw_id)
            except ClientError as e: logging.warning(f"Delete IGW failed: {e}")

def disassociate_non_main_rts(ec2, vpc_id, DRY_RUN):
    rts = ec2.describe_route_tables(Filters=[{"Name":"vpc-id","Values":[vpc_id]}]).get("RouteTables",[])
    for rt in rts:
        assocs = rt.get("Associations",[])
        is_main = any(a.get("Main") for a in assocs)
        if is_main: 
            logging.info(f"Main RT kept: {rt['RouteTableId']}")
            continue
        rt_id = rt["RouteTableId"]
        for a in assocs:
            aid = a.get("RouteTableAssociationId")
            if aid:
                logging.info(f"RT disassociate -> {aid} (from {rt_id})")
                if not DRY_RUN:
                    try: ec2.disassociate_route_table(AssociationId=aid)
                    except ClientError as e: logging.warning(f"Disassociate failed: {e}")

def delete_subnets(ec2, vpc_id, DRY_RUN):
    subs = ec2.describe_subnets(Filters=[{"Name":"vpc-id","Values":[vpc_id]}]).get("Subnets",[])
    for sn in subs:
        sid = sn["SubnetId"]
        logging.info(f"Subnet -> delete {sid}")
        if not DRY_RUN:
            try: ec2.delete_subnet(SubnetId=sid)
            except ClientError as e: logging.warning(f"Delete subnet failed: {e}")

def delete_non_default_sgs(ec2, vpc_id, DRY_RUN):
    sgs = ec2.describe_security_groups(Filters=[{"Name":"vpc-id","Values":[vpc_id]}]).get("SecurityGroups",[])
    for sg in sgs:
        if sg.get("GroupName")=="default": continue
        gid = sg["GroupId"]
        logging.info(f"SG -> delete {gid}")
        if not DRY_RUN:
            try: ec2.delete_security_group(GroupId=gid)
            except ClientError as e: logging.warning(f"Delete SG failed: {e}")

def delete_remaining_rts(ec2, vpc_id, DRY_RUN):
    rts = ec2.describe_route_tables(Filters=[{"Name":"vpc-id","Values":[vpc_id]}]).get("RouteTables",[])
    for rt in rts:
        if any(a.get("Main") for a in rt.get("Associations",[])): continue
        rt_id = rt["RouteTableId"]
        logging.info(f"RT -> delete {rt_id}")
        if not DRY_RUN:
            try: ec2.delete_route_table(RouteTableId=rt_id)
            except ClientError as e: logging.warning(f"Delete RT failed: {e}")

def cleanup_vpc(ec2, v, terminate_first, DRY_RUN):
    vpc_id = v["VpcId"]
    logging.info(f"=== Cleaning VPC: {vpc_id} ===")
    if terminate_first: terminate_instances(ec2, vpc_id, DRY_RUN)
    delete_vpc_endpoints(ec2, vpc_id, DRY_RUN)
    delete_nat_gateways_and_eips(ec2, vpc_id, DRY_RUN)
    detach_delete_igws(ec2, vpc_id, DRY_RUN)
    disassociate_non_main_rts(ec2, vpc_id, DRY_RUN)
    delete_subnets(ec2, vpc_id, DRY_RUN)
    delete_non_default_sgs(ec2, vpc_id, DRY_RUN)
    delete_remaining_rts(ec2, vpc_id, DRY_RUN)
    logging.info(f"VPC -> delete {vpc_id}")
    if not DRY_RUN:
        try: ec2.delete_vpc(VpcId=vpc_id)
        except ClientError as e: logging.error(f"Delete VPC failed: {e}")

def main():
    regions = ask_region_list()
    terminate_first = ask_terminate_instances()
    DRY_RUN = ask_dry_run()

    if not DRY_RUN:
        if not confirm_delete():
            print("Cancelled."); return

    for region in regions:
        ec2 = build_ec2(region)
        vpcs = ec2.describe_vpcs().get("Vpcs",[])
        if not vpcs:
            logging.info(f"No VPCs in {region}."); continue
        for v in vpcs:
            if v.get("IsDefault", False): 
                logging.info(f"Skip default VPC {v['VpcId']}"); continue
            if skip_vpc_by_tags(v):
                logging.info(f"Skip tagged VPC {v['VpcId']}"); continue
            cleanup_vpc(ec2, v, terminate_first, DRY_RUN)

if __name__ == "__main__":
    main()
