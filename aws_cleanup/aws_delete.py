#!/usr/bin/env python3
import datetime
import time
import boto3
from botocore.exceptions import ClientError


EMPTY_LEFTOVERS = {
    "load_balancer": [],
    "ec2_instance": [],
    "nat_gateway": [],
    "internet_gateway": [],
    "target_group": [],
    "network_interface": [],
    "route_table": [],
    "security_group": [],
    "subnet": [],
    "vpc_endpoint": [],
    "vpc": [],
    "eip": [],
}
HOURS_TO_EXPIRE = 6
CI_TAG = "ci-op-"
DELETED_RESOURCES = {
    "iam_user": 0,
    "iam_profile": 0,
    "iam_role": 0,
    "load_balancer": 0,
    "ec2_instance": 0,
    "nat_gateway": 0,
    "internet_gateway": 0,
    "target_group": 0,
    "network_interface": 0,
    "route_table": 0,
    "security_group": 0,
    "subnet": 0,
    "vpc_endpoint": 0,
    "vpc": 0,
    "volume": 0,
    "s3": 0,
    "eip": 0,
    "dhcp_opts": 0,
}
TOTAL_SAVED = {"total": 0}


class AWSResourceDeletion:

    def __init__(self, ec2_client, elb_client, elbv2_client, s3_client, iam_client, pricing_client, tag, dry_run=False):
        self.tag = tag
        self.ec2_client = ec2_client
        self.elb_client = elb_client
        self.elbv2_client = elbv2_client
        self.s3_client = s3_client
        self.iam_client = iam_client
        self.pricing_client = pricing_client
        self.dry_run = dry_run
        self.delete = Delete(ec2_client, elb_client, elbv2_client, s3_client, iam_client, pricing_client, dry_run)
        self.tags_set = []

    def cycle(self, exp_vpc, past_leftovers=None):
        past_leftovers = past_leftovers or {}
        leftovers = {
            "load_balancer": [],
            "ec2_instance": [],
            "nat_gateway": [],
            "internet_gateway": [],
            "target_group": [],
            "network_interface": [],
            "route_table": [],
            "security_group": [],
            "subnet": [],
            "vpc_endpoint": [],
            "vpc": [],
            "eip": [],
        }
        lbs_list = past_leftovers.get("load_balancer", self.get_lbs_from_vpc(exp_vpc))
        for lb in lbs_list:
            result = self.delete.load_balancer(lb)
            if not result:
                leftovers["load_balancer"].append(lb)
        instances_list = past_leftovers.get("ec2_instance", self.get_ec2_instances_from_vpc(exp_vpc))
        for instance in instances_list:
            result = self.delete.ec2_instance(instance)
            if not result:
                leftovers["ec2_instance"].append(instance)
        nat_list = past_leftovers.get("nat_gateway", self.get_nat_gateways_from_vpc(exp_vpc))
        for nat in nat_list:
            result = self.delete.nat_gateway(nat)
            if not result:
                leftovers["nat_gateway"].append(nat)
        eip_list = past_leftovers.get("eip", self.get_eips_from_tag(exp_vpc))
        eip_list += self.get_unattached_eips()
        for eip in eip_list:
            result = self.delete.eip(eip)
            if not result:
                leftovers["eip"].append(eip)
        igw_list = past_leftovers.get("internet_gateway", self.get_internet_gateways_from_vpc(exp_vpc))
        for igw in igw_list:
            result = self.delete.internet_gateway(igw, exp_vpc["VpcId"])
            if not result:
                leftovers["internet_gateway"].append(igw)
        # tg_list = past_leftovers.get('target_group', self.get_target_groups_from_vpc(exp_vpc))
        # for tg in tg_list:
        #     result = self.delete.target_group(tg)
        #     if not result:
        #         leftovers['target_group'].append(tg)
        ni_list = past_leftovers.get("network_interface", self.get_network_interfaces_from_vpc(exp_vpc))
        for ni in ni_list:
            result = self.delete.network_interface(ni)
            if not result:
                leftovers["network_interface"].append(ni)
        rt_list = past_leftovers.get("route_table", self.get_route_tables_from_vpc(exp_vpc))
        for rt in rt_list:
            result = self.delete.route_table(rt)
            if not result:
                leftovers["route_table"].append(rt)
        sg_list = past_leftovers.get("security_group", self.get_security_groups_from_vpc(exp_vpc))
        for sg in sg_list:
            result = self.delete.security_group(sg)
            if not result:
                leftovers["security_group"].append(sg)
        subnets_list = past_leftovers.get("subnet", self.get_subnets_from_vpc(exp_vpc))
        for subnet in subnets_list:
            result = self.delete.subnet(subnet)
            if not result:
                leftovers["subnet"].append(subnet)
        vpce_list = past_leftovers.get("vpc_endpoint", self.get_vpc_endpoint_from_vpc(exp_vpc))
        for vpce in vpce_list:
            result = self.delete.vpc_endpoint(vpce)
            if not result:
                leftovers["vpc_endpoint"].append(vpce)
        vpc_result = self.delete.vpc(exp_vpc["VpcId"])
        if not vpc_result:
            leftovers["vpc"].append(exp_vpc["VpcId"])
        else:
            return EMPTY_LEFTOVERS
        return leftovers

    def run(self):

        vpcs = self.get_vpc_id_by_tag()
        expired_vpc = self.get_expired_vpcs(vpcs)
        expired_instances = self.get_expired_instances()

        for instance in expired_instances:
            print(f"Instance {instance['InstanceId']} ({instance['InstanceType']}) expired {instance['delta']} ago")
            result = self.delete.ec2_instance(instance["InstanceId"])

        for vpc in expired_vpc:
            vpc_tag = self._get_tag_from_vpc(vpc)
            print(f"VPC {vpc['VpcId']} with tag {vpc_tag} expired {vpc['delta']} ago")
            leftovers = self.cycle(vpc)
            print(f"Leftovers from first cycle {leftovers}")
            # run the cycle until there are no more leftovers or max 10 times
            count = 1
            while leftovers != EMPTY_LEFTOVERS:
                time.sleep(60)
                count += 1
                leftovers = self.cycle(vpc, leftovers)
                print(f"Leftovers from cycle {count}: {leftovers}")
                if count > 9:
                    print(f"Max number of cycles reached with VPC {vpc['Name']} leftovers: {leftovers}")
                    break
            if vpc_tag == "":
                print("Skipping deletion of S3 bucket and volumes, since tag is empty")
            else:
                if vpc_tag == self.tag:
                    volumes = self.get_volumes_expired(self.tag)
                    buckets = self.get_s3_buckets_expired(self.tag)
                else:
                    volumes = self.get_volumes_from_tag(vpc_tag)
                    buckets = self.get_s3_buckets_from_tag(vpc_tag)
                for vol in volumes:
                    result = self.delete.volume(vol)
                    if not result:
                        leftovers["volume"].append(vol)
                for bucket in buckets:
                    result = self.delete.s3_bucket(bucket)
                    if not result:
                        leftovers["s3"].append(bucket)
        expired_resources = AWSExpiredResources(
            self.ec2_client, self.elb_client, self.elbv2_client, self.s3_client, self.iam_client, self.dry_run
        )
        expired_resources.eliminate()
        print(f"All resources deleted for region {self.ec2_client.meta.region_name}")

    def _get_tag_from_vpc(self, vpc):
        for tag in vpc.get("Tags", []):
            if tag["Key"] == "Name":
                if tag["Value"]:
                    vpc_tag = tag["Value"]
                    vpc_tag = "-".join(vpc_tag.split("-")[:5])
                    return vpc_tag
        for tag in vpc.get("Tags", []):
            if tag["Key"].startswith("kubernetes.io/cluster/ci-op-"):
                vpc_tag = tag["Key"].split("/")[2]
                vpc_tag = "-".join(vpc_tag.split("-")[:5])
                return vpc_tag
        return ""

    # Get VPC which starts from the tag
    def get_vpc_id_by_tag(self):
        result = []
        vpcs = self.ec2_client.describe_vpcs()
        for vpc in vpcs["Vpcs"]:
            for tag in vpc.get("Tags", []):
                if tag["Key"] == "Name" and tag["Value"].startswith(self.tag):
                    result.append(vpc["VpcId"])
        return result

    def get_expired_vpcs(self, vpcs):
        expired_vpcs = []
        for vpc in self.ec2_client.describe_vpcs(VpcIds=vpcs)["Vpcs"]:
            if has_expired(vpc):
                expired_vpcs.append(vpc)
        return expired_vpcs

    def get_expired_instances(self):

        result = []
        reservations = self.ec2_client.describe_instances()["Reservations"]
        for reservation in reservations:
            for instance in reservation["Instances"]:
                if has_expired(instance):
                    result.append(instance)
        return result

    def get_lbs_from_vpc(self, vpc):
        result = []
        for lb in self.elb_client.describe_load_balancers()["LoadBalancerDescriptions"]:
            if lb["VPCId"] == vpc["VpcId"]:
                result.append(lb["LoadBalancerName"])
        for lb2 in self.elbv2_client.describe_load_balancers()["LoadBalancers"]:
            if lb2["VpcId"] == vpc["VpcId"]:
                result.append(lb2["LoadBalancerArn"])
        return result

    def get_ec2_instances_from_vpc(self, vpc):
        result = []
        for reservation in self.ec2_client.describe_instances()["Reservations"]:
            for instance in reservation["Instances"]:
                if "VpcId" in instance and instance["VpcId"] == vpc["VpcId"]:
                    result.append(instance["InstanceId"])
        return result

    def get_nat_gateways_from_vpc(self, vpc):
        result = []
        for nat in self.ec2_client.describe_nat_gateways()["NatGateways"]:
            if nat["VpcId"] == vpc["VpcId"]:
                result.append(nat["NatGatewayId"])
        return result

    def get_internet_gateways_from_vpc(self, vpc):
        result = []
        for igw in self.ec2_client.describe_internet_gateways()["InternetGateways"]:
            for attachment in igw["Attachments"]:
                if attachment["VpcId"] == vpc["VpcId"]:
                    result.append(igw["InternetGatewayId"])
        return result

    def get_vpc_endpoint_from_vpc(self, vpc):
        result = []
        for vpce in self.ec2_client.describe_vpc_endpoints()["VpcEndpoints"]:
            if vpce["VpcId"] == vpc["VpcId"]:
                result.append(vpce["VpcEndpointId"])
        return result

    def get_target_groups_from_vpc(self, vpc):
        result = []
        for tg in self.elbv2_client.describe_target_groups()["TargetGroups"]:
            if tg["VpcId"] == vpc["VpcId"]:
                result.append(tg["TargetGroupArn"])
        return result

    def get_network_interfaces_from_vpc(self, vpc):
        result = []
        for ni in self.ec2_client.describe_network_interfaces()["NetworkInterfaces"]:
            if ni["VpcId"] == vpc["VpcId"]:
                result.append(ni["NetworkInterfaceId"])
        return result

    def get_eips_from_tag(self, vpc):
        result = []
        vpc_tag = self._get_tag_from_vpc(vpc)
        if not vpc_tag:
            return result
        for eip in self.ec2_client.describe_addresses()["Addresses"]:
            if eip["Domain"] == "vpc":
                if "tags" in eip and eip["Tags"]:
                    for t in eip["Tags"]:
                        if t["Key"] == "Name" and t["Value"].startswith(vpc_tag):
                            result.append(eip["AllocationId"])
        return result

    def get_unattached_eips(self):
        result = []
        for eip in self.ec2_client.describe_addresses()["Addresses"]:
            if "InstanceId" not in eip and "NetworkInterfaceId" not in eip:
                result.append(eip["AllocationId"])
        return result

    def get_route_tables_from_vpc(self, vpc):
        return [
            i["RouteTableId"]
            for i in self.ec2_client.describe_route_tables()["RouteTables"]
            if "VpcId" in i and i["VpcId"] == vpc["VpcId"]
        ]

    def get_security_groups_from_vpc(self, vpc):
        result = []
        for sg in self.ec2_client.describe_security_groups()["SecurityGroups"]:
            if sg["VpcId"] == vpc["VpcId"]:
                result.append(sg["GroupId"])
        return result

    def get_subnets_from_vpc(self, vpc):
        result = []
        for subnet in self.ec2_client.describe_subnets()["Subnets"]:
            if subnet["VpcId"] == vpc["VpcId"]:
                result.append(subnet["SubnetId"])
        return result

    def get_volumes_from_tag(self, tag):
        result = []
        for volume in self.ec2_client.describe_volumes()["Volumes"]:
            for t in volume["Tags"]:
                if t["Key"] == "Name" and t["Value"].startswith(tag):
                    result.append(volume["VolumeId"])
        print("Getting EBS volumes", len(result))
        return result

    def get_volumes_expired(self, tag):
        result = []
        for volume in self.ec2_client.describe_volumes()["Volumes"]:
            if (volume["Tags"][0]["Key"] == "Name" and volume["Tags"][0]["Value"].startswith(tag) and
                datetime.datetime.now(datetime.timezone.utc) >
                    volume["CreateTime"] + datetime.timedelta(hours=HOURS_TO_EXPIRE)):
                result.append(volume["VolumeId"])
        print("Getting EBS volumes", len(result))
        return result

    def get_s3_buckets_from_tag(self, tag):
        result = []
        for bucket in self.s3_client.list_buckets()["Buckets"]:
            if bucket["Name"].startswith(tag):
                result.append(bucket["Name"])
        print("Getting S3 buckets", len(result))
        return result

    def get_s3_buckets_expired(self, tag):
        result = []
        for bucket in self.s3_client.list_buckets()["Buckets"]:
            if (bucket["Name"].startswith(tag) and
                datetime.datetime.now(datetime.timezone.utc) >
                    bucket.creation_date + datetime.timedelta(hours=HOURS_TO_EXPIRE)):
                result.append(bucket["Name"])
        print("Getting S3 buckets", len(result))
        return result


class AWSExpiredResources:

    def __init__(self, ec2_client, elb_client, elbv2_client, s3_client, iam_client, dry_run=False):
        self.ec2_client = ec2_client
        self.elb_client = elb_client
        self.elbv2_client = elbv2_client
        self.s3_client = s3_client
        self.iam_client = iam_client
        self.dry_run = dry_run
        self.delete = Delete(ec2_client, elb_client, elbv2_client, s3_client, iam_client, dry_run)

    def eliminate(self):
        for reservation in self.ec2_client.describe_instances()["Reservations"]:
            for instance in reservation["Instances"]:
                if has_expired(instance):
                    print(f"Instance {instance['InstanceId']} expired")
                    self.delete.ec2_instance(instance["InstanceId"])
        for lb in self.elb_client.describe_load_balancers()["LoadBalancerDescriptions"]:
            if has_expired(lb):
                print(f"Load Balancer {lb['LoadBalancerName']} expired")
                self.delete.load_balancer(lb["LoadBalancerName"])
        for lb2 in self.elbv2_client.describe_load_balancers()["LoadBalancers"]:
            if has_expired(lb2):
                print(f"Load Balancer v2 {lb2['LoadBalancerArn']} expired")
                self.delete.load_balancer(lb2["LoadBalancerArn"])
        for nat in self.ec2_client.describe_nat_gateways()["NatGateways"]:
            if has_expired(nat):
                print(f"NAT Gateway {nat['NatGatewayId']} expired")
                self.delete.nat_gateway(nat["NatGatewayId"])
        for igw in self.ec2_client.describe_internet_gateways()["InternetGateways"]:
            for attachment in igw["Attachments"]:
                if has_expired(igw):
                    print(f"Internet Gateway {igw['InternetGatewayId']} expired")
                    self.delete.internet_gateway(igw["InternetGatewayId"], attachment["VpcId"])
        for vpce in self.ec2_client.describe_vpc_endpoints()["VpcEndpoints"]:
            if has_expired(vpce):
                print(f"VPC Endpoint {vpce['VpcEndpointId']} expired")
                self.delete.vpc_endpoint(vpce["VpcEndpointId"])
        for tg in self.elbv2_client.describe_target_groups()["TargetGroups"]:
            if has_expired(tg):
                print(f"Target Group {tg['TargetGroupArn']} expired")
                self.delete.target_group(tg["TargetGroupArn"])
        for ni in self.ec2_client.describe_network_interfaces()["NetworkInterfaces"]:
            if has_expired(ni):
                print(f"Network Interface {ni['NetworkInterfaceId']} expired")
                self.delete.network_interface(ni["NetworkInterfaceId"])
        for rt in self.ec2_client.describe_route_tables()["RouteTables"]:
            if has_expired(rt):
                print(f"Route Table {rt['RouteTableId']} expired")
                self.delete.route_table(rt["RouteTableId"])
        for sg in self.ec2_client.describe_security_groups()["SecurityGroups"]:
            if has_expired(sg):
                print(f"Security Group {sg['GroupId']} expired")
                self.delete.security_group(sg["GroupId"])
        for subnet in self.ec2_client.describe_subnets()["Subnets"]:
            if has_expired(subnet):
                print(f"Subnet {subnet['SubnetId']} expired")
                self.delete.subnet(subnet["SubnetId"])
        for dhcp_opts in self.ec2_client.describe_dhcp_options()["DhcpOptions"]:
            if has_expired(dhcp_opts):
                print(f"DHCP Options {dhcp_opts['DhcpOptionsId']} expired")
                self.delete.dhcp_opts(dhcp_opts["DhcpOptionsId"])
        for vpc in self.ec2_client.describe_vpcs()["Vpcs"]:
            if has_expired(vpc):
                print(f"VPC {vpc['VpcId']} expired")
                self.delete.vpc(vpc["VpcId"])
        for eip in self.ec2_client.describe_addresses()["Addresses"]:
            if has_expired(eip) or unattached(eip):
                print(f"EIP {eip['AllocationId']} expired or unattached")
                self.delete.eip(eip["AllocationId"])
        for volume in self.ec2_client.describe_volumes()["Volumes"]:
            if has_expired(volume) or old_dated(volume):
                print(f"Volume {volume['VolumeId']} expired")
                self.delete.volume(volume["VolumeId"])
        for bucket in self.s3_client.list_buckets()["Buckets"]:
            if has_expired(bucket) or old_dated(bucket):
                print(f"S3 bucket {bucket['Name']} expired")
                self.delete.s3_bucket(bucket["Name"])
        for user in self.iam_client.list_users()["Users"]:
            if has_expired(user) or old_dated(user):
                print(f"IAM user {user['UserName']} expired")
                self.delete.iam_user(user["UserName"])
        for profile in self.iam_client.list_instance_profiles()["InstanceProfiles"]:
            if has_expired(profile) or old_dated(profile):
                print(f"IAM role {profile['InstanceProfileName']} expired")
                self.delete.iam_instance_profile(profile)
        for role in self.iam_client.list_roles()["Roles"]:
            if has_expired(role) or old_dated(role):
                print(f"IAM role {role['RoleName']} expired")
                self.delete.iam_role(role["RoleName"])


class Price:

    def __init__(self, ec2_client, elb_client, elbv2_client, s3_client, iam_client, pricing_client, dry_run=False):
        self.ec2_client = ec2_client
        self.elb_client = elb_client
        self.elbv2_client = elbv2_client
        self.s3_client = s3_client
        self.iam_client = iam_client
        self.pricing_client = pricing_client
        self.dry_run = dry_run
        self.price_cache = {}

    def estimate(self, resource_type, resource_id):
        if resource_type == "ec2_instance":
            return self.ec2_instance(resource_id)
        elif resource_type == "elb":
            return self.elb(resource_id)
        elif resource_type == "elbv2":
            return self.elbv2(resource_id)
        elif resource_type == "natgw":
            return self.natgw(resource_id)
        elif resource_type == "vpc_endpoint":
            return self.vpc_endpoint(resource_id)
        elif resource_type == "eip":
            return self.eip(resource_id)
        elif resource_type == "volume":
            return self.volume(resource_id)
        elif resource_type == "s3_bucket":
            return self.s3_bucket(resource_id)
        else:
            return 0

    def ec2_instance(self, instance_id):
        instance = self.ec2_client.describe_instances(InstanceIds=[instance_id])["Reservations"][0]["Instances"][0]
        instance_type = instance["InstanceType"]
        if instance_type in self.price_cache:
            return self.price_cache[instance_type]
        # Fetch on-demand pricing for the given instance type
        try:
            response = self.pricing_client.get_products(
                ServiceCode="AmazonEC2",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
                    {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
                    {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
                    {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
                    {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
                ],
            )

            # Parse the price from the response
            for price_item in response["PriceList"]:
                price_data = eval(price_item)  # Convert string to dict (not ideal but works)
                on_demand_terms = price_data["terms"]["OnDemand"]
                for term_key in on_demand_terms:
                    price_dimensions = on_demand_terms[term_key]["priceDimensions"]
                    for dimension_key in price_dimensions:
                        price_value = price_dimensions[dimension_key]["pricePerUnit"]["USD"]
                        print(f"Price value for instance type {instance_type}: {price_value}")
                        self.price_cache[instance_type] = float(price_value)
                        return float(price_value)
        except Exception as e:
            print(f"Error getting EC2 pricing: {e}")
        # if no price found, return constant values
        return {"m6a.xlarge": 0.1728, "m6a.2xlarge": 0.3456}.get(instance_type) or 0.17

    def elb(self, lb_name):
        if self.price_cache.get("elb"):
            return self.price_cache["elb"]
        # Calculate price for Classic Load Balancer (CLB)
        price_value = 0
        try:
            response = self.pricing_client.get_products(
                ServiceCode="AmazonEC2",  # ELB pricing is actually under EC2
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Load Balancer"},
                    {"Type": "TERM_MATCH", "Field": "usagetype", "Value": "LoadBalancerUsage"},
                ],
            )
            # Parse the price from the response
            for price_item in response["PriceList"]:
                price_data = eval(price_item)
                on_demand_terms = price_data["terms"]["OnDemand"]
                for term_key in on_demand_terms:
                    price_dimensions = on_demand_terms[term_key]["priceDimensions"]
                    for dimension_key in price_dimensions:
                        price_value = float(price_dimensions[dimension_key]["pricePerUnit"]["USD"])
                        print(f"ELB Price value: {price_value}")
                        break
                if price_value:
                    break

        except Exception as e:
            print(f"Error getting ELB pricing: {e}")

        if not price_value:
            price_value = 0.025
        self.price_cache["elb"] = price_value
        return price_value

    def elbv2(self, lb_arn):
        if self.price_cache.get("elbv2"):
            return self.price_cache["elbv2"]
        price_value = 0
        try:
            response = self.pricing_client.get_products(
                ServiceCode="AmazonEC2",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Load Balancer-Network"},
                    {"Type": "TERM_MATCH", "Field": "usagetype", "Value": "LoadBalancerUsage"},
                ],
            )
            # Parse the price from the response
            for price_item in response["PriceList"]:
                price_data = eval(price_item)
                on_demand_terms = price_data["terms"]["OnDemand"]
                for term_key in on_demand_terms:
                    price_dimensions = on_demand_terms[term_key]["priceDimensions"]
                    for dimension_key in price_dimensions:
                        price_value = float(price_dimensions[dimension_key]["pricePerUnit"]["USD"])
                        print(f"NLB Price value: {price_value}")
                        break
                if price_value:
                    break

        except Exception as e:
            print(f"Error getting NLB pricing: {e}")
        if not price_value:
            price_value = 0.0225
        self.price_cache["elbv2"] = price_value
        return price_value

    def natgw(self, nat_id):
        if self.price_cache.get("natgw"):
            return self.price_cache["natgw"]
        price_value = 0
        try:
            response = self.pricing_client.get_products(
                ServiceCode="AmazonEC2",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "NAT Gateway"},
                    {"Type": "TERM_MATCH", "Field": "usagetype", "Value": "USW2-NatGateway-Hours"},
                ],
            )
            for price_item in response["PriceList"]:
                price_data = eval(price_item)
                on_demand_terms = price_data["terms"]["OnDemand"]
                for term_key in on_demand_terms:
                    price_dimensions = on_demand_terms[term_key]["priceDimensions"]
                    for dimension_key in price_dimensions:
                        price_value = float(price_dimensions[dimension_key]["pricePerUnit"]["USD"])
                        print(f"NATGW Price value: {price_value}")
                        break
                if price_value:
                    break

        except Exception as e:
            print(f"Error getting NATGW pricing: {e}")
        if not price_value:
            price_value = 0.045
        self.price_cache["natgw"] = price_value
        return price_value

    def vpc_endpoint(self, vpce_id):
        # charged per GBs
        return 0

    def eip(self, allocation_id):
        # charged only if not attached
        return 0.005

    def volume(self, volume_id):
        price_value = 0
        volume_size = 0
        try:
            volume = self.ec2_client.describe_volumes(VolumeIds=[volume_id])["Volumes"][0]
            volume_type = volume["VolumeType"]
            volume_size = volume["Size"]
            if self.price_cache.get("volume"):
                return (self.price_cache["volume"] * volume_size) / 720
            response = self.pricing_client.get_products(
                ServiceCode="AmazonEC2",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Storage"},
                    {"Type": "TERM_MATCH", "Field": "volumeApiName", "Value": volume_type},
                ],
            )
            for price_item in response["PriceList"]:
                price_data = eval(price_item)
                on_demand_terms = price_data["terms"]["OnDemand"]
                for term_key in on_demand_terms:
                    price_dimensions = on_demand_terms[term_key]["priceDimensions"]
                    for dimension_key in price_dimensions:
                        price_value = float(price_dimensions[dimension_key]["pricePerUnit"]["USD"])
                        print(f"Volume Price value: {price_value} per GB per month")
                        break
                if price_value:
                    break
        except Exception as e:
            print(f"Error getting Volume pricing: {e}")
            if price_value:
                self.price_cache["volume"] = price_value
            if not volume_size:
                return 0
        if not price_value:
            price_value = 0.0156
        self.price_cache["volume"] = price_value
        price_per_hour = (price_value * volume_size) / 720
        return price_per_hour

    def s3_bucket(self, bucket_name):
        price_value = 0
        # charged per GBs
        s3_total_size = 0
        s3_bucket_paginator = self.s3_client.get_paginator("list_objects_v2")
        for page in s3_bucket_paginator.paginate(Bucket=bucket_name):
            if "Contents" in page:
                for obj in page["Contents"]:
                    s3_total_size += obj["Size"]
        # convert to GBs
        s3_total_size = s3_total_size / 1073741824
        if self.price_cache.get("s3_bucket"):
            return (self.price_cache["s3_bucket"] * s3_total_size) / 720
        try:
            response = self.pricing_client.get_products(
                ServiceCode="AmazonS3", Filters=[{"Type": "TERM_MATCH", "Field": "productFamily", "Value": "Storage"}]
            )
            for price_item in response["PriceList"]:
                price_data = eval(price_item)
                on_demand_terms = price_data["terms"]["OnDemand"]
                for term_key in on_demand_terms:
                    price_dimensions = on_demand_terms[term_key]["priceDimensions"]
                    for dimension_key in price_dimensions:
                        price_value = float(price_dimensions[dimension_key]["pricePerUnit"]["USD"])
                        print(f"S3 Price value: {price_value} per GB per month")
                        break
                if price_value:
                    break
        except Exception as e:
            print(f"Error getting S3 pricing: {e}")
            if price_value:
                self.price_cache["s3_bucket"] = price_value
            if not s3_total_size:
                return 0
        if not price_value:
            price_value = 0.00405
        self.price_cache["s3_bucket"] = price_value
        price_per_hour = (price_value * s3_total_size) / 720
        return price_per_hour


class Delete:

    def __init__(self, ec2_client, elb_client, elbv2_client, s3_client, iam_client, pricing_client, dry_run=False):
        self.ec2_client = ec2_client
        self.elb_client = elb_client
        self.elbv2_client = elbv2_client
        self.s3_client = s3_client
        self.iam_client = iam_client
        self.dry_run = dry_run
        self.price = Price(ec2_client, elb_client, elbv2_client, s3_client, iam_client, pricing_client, dry_run)

    # Function to delete an EC2 instance
    def ec2_instance(self, instance_id):
        try:
            if not self.dry_run:
                self.ec2_client.terminate_instances(InstanceIds=[instance_id])
            print(f"Terminated EC2 instance: {instance_id}")
            DELETED_RESOURCES["ec2_instance"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("ec2_instance", instance_id)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"Instance {instance_id} does not exist")
                return True
            print(f"Error terminating EC2 instance {instance_id}: {e}")

    # Function to delete a Load Balancer
    def load_balancer(self, data):
        if "arn:aws:elasticloadbalancing" in data:
            print(f"Deleting Load Balancer v2: {data}")
            return self.load_balancerv2(data)
        else:
            print(f"Deleting Load Balancer v1: {data}")
            return self.load_balancerv1(data)

    # Function to delete a Load Balancer v1
    def load_balancerv1(self, name):
        try:
            if not self.dry_run:
                self.elb_client.delete_load_balancer(LoadBalancerName=name)
            print(f"Deleted Load Balancer: {name}")
            DELETED_RESOURCES["load_balancer"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("elb", name)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"Load Balancer {name} does not exist")
                return True
            print(f"Error deleting Load Balancer {name}: {e}")

    # Function to delete a load balancer v2
    def load_balancerv2(self, arn):
        try:
            if not self.dry_run:
                self.elbv2_client.delete_load_balancer(LoadBalancerArn=arn)
            print(f"Deleted Load Balancer v2: {arn}")
            DELETED_RESOURCES["load_balancer"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("elbv2", arn)
            return True
        except ClientError as e:
            if "does not exist" in str(e) or "is not a valid load balancer" in str(e):
                print(f"Load Balancer v2 {arn} does not exist")
                return True
            print(f"Error deleting Load Balancer v2 {arn}: {e}")

    # Function to delete a Target Group
    def target_group(self, arn):
        # Should be removed with load balancer
        try:
            if not self.dry_run:
                self.elbv2_client.delete_target_group(TargetGroupArn=arn)
            print(f"Deleted Target Group: {arn}")
            DELETED_RESOURCES["target_group"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("elbv2_target_group", arn)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"Target Group {arn} does not exist")
                return True
            print(f"Error deleting Target Group {arn}: {e}")

    # Function to delete a Network Interface
    def network_interface(self, eni_id):
        try:
            interface = self.ec2_client.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
            status = interface["NetworkInterfaces"][0]["Status"]
            if status == "in-use":
                print(f"Network Interface {eni_id} is in use and cannot be deleted")
                return
            if not self.dry_run:
                self.ec2_client.delete_network_interface(NetworkInterfaceId=eni_id)
            print(f"Deleted Network Interface: {eni_id}")
            DELETED_RESOURCES["network_interface"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("network_interface", eni_id)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"Network Interface {eni_id} does not exist")
                return True
            print(f"Error deleting Network Interface {eni_id}: {e}")

    # Function to delete a NAT Gateway
    def nat_gateway(self, nat_id):
        try:
            if not self.dry_run:
                self.ec2_client.delete_nat_gateway(NatGatewayId=nat_id)
            print(f"Deleted NAT Gateway: {nat_id}")
            DELETED_RESOURCES["nat_gateway"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("natgw", nat_id)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"NAT Gateway {nat_id} does not exist")
                return True
            print(f"Error deleting NAT Gateway {nat_id}: {e}")

    # Function to release an Elastic IP
    def eip(self, allocation_id):
        try:
            if not self.dry_run:
                self.ec2_client.release_address(AllocationId=allocation_id)
            print(f"Released EIP: {allocation_id}")
            DELETED_RESOURCES["eip"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("eip", allocation_id)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"EIP {allocation_id} does not exist")
                return True
            print(f"Error releasing EIP {allocation_id}: {e}")

    # Function to delete a VPC Endpoint
    def vpc_endpoint(self, vpce_id):
        try:
            if not self.dry_run:
                self.ec2_client.delete_vpc_endpoints(VpcEndpointIds=[vpce_id])
            print(f"Deleted VPC Endpoint: {vpce_id}")
            DELETED_RESOURCES["vpc_endpoint"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("vpce", vpce_id)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"VPC Endpoint {vpce_id} does not exist")
                return True
            print(f"Error deleting VPC Endpoint {vpce_id}: {e}")

    # Function to delete a Security Group
    def security_group(self, sg_id):
        def revoke_all_rules(sg_id):
            try:
                security_group = self.ec2_client.describe_security_groups(GroupIds=[sg_id])["SecurityGroups"][0]
                ingress_rules = security_group["IpPermissions"]
                egress_rules = security_group["IpPermissionsEgress"]
                if ingress_rules:
                    print(f"Revoking ingress rules for Security Group {sg_id}")
                    if not self.dry_run:
                        self.ec2_client.revoke_security_group_ingress(GroupId=sg_id, IpPermissions=ingress_rules)
                if egress_rules:
                    print(f"Revoking egress rules for Security Group {sg_id}")
                    if not self.dry_run:
                        self.ec2_client.revoke_security_group_egress(GroupId=sg_id, IpPermissions=egress_rules)
                return True
            except ClientError as e:
                print(f"Error revoking rules for Security Group {sg_id}: {e}")
                return False

        try:
            if not self.dry_run:
                self.ec2_client.delete_security_group(GroupId=sg_id)
            print(f"Deleted Security Group: {sg_id}")
            DELETED_RESOURCES["security_group"] += 1
            return True
        except ClientError as e:
            if "is still in use and cannot be deleted" in str(e) or "has a dependent object" in str(e):
                print(f"Security Group {sg_id} is still in use and cannot be deleted")
                # let's revoke all rules and try again next time
                revoke_all_rules(sg_id)
                return
            if "does not exist" in str(e):
                print(f"Security Group {sg_id} does not exist")
                return True
            if '"default" cannot be deleted by a user' in str(e):
                print(f"Security Group {sg_id} is a default group and cannot be deleted")
                return True
            print(f"Error deleting Security Group {sg_id}: {e}")

    # Function to delete a Subnet
    def subnet(self, subnet_id):
        try:
            if not self.dry_run:
                self.ec2_client.delete_subnet(SubnetId=subnet_id)
            print(f"Deleted Subnet: {subnet_id}")
            DELETED_RESOURCES["subnet"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("subnet", subnet_id)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"Subnet {subnet_id} does not exist")
                return True
            print(f"Error deleting Subnet {subnet_id}: {e}")

    # Function to delete a Route Table
    def route_table(self, rt_id):
        try:
            if not self.dry_run:
                self.ec2_client.delete_route_table(RouteTableId=rt_id)
            print(f"Deleted Route Table: {rt_id}")
            DELETED_RESOURCES["route_table"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("route_table", rt_id)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"Route Table {rt_id} does not exist")
                return True
            print(f"Error deleting Route Table {rt_id}: {e}")

    # Function to delete an Internet Gateway
    def internet_gateway(self, igw_id, vpc_id):
        try:
            # detach firstly from VPC
            print("Detaching Internet Gateway from VPC")
            if not self.dry_run:
                self.ec2_client.detach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
                self.ec2_client.delete_internet_gateway(InternetGatewayId=igw_id)
            print(f"Deleted Internet Gateway: {igw_id}")
            DELETED_RESOURCES["internet_gateway"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("internet_gateway", igw_id)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"Internet Gateway {igw_id} does not exist")
                return True
            print(f"Error deleting Internet Gateway {igw_id}: {e}")

    # Function to delete DHCP opts
    def dhcp_opts(self, dhcp_opts_id):
        try:
            if not self.dry_run:
                self.ec2_client.delete_dhcp_options(DhcpOptionsId=dhcp_opts_id)
            print(f"Deleted DHCP Options: {dhcp_opts_id}")
            DELETED_RESOURCES["dhcp_opts"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("dhcp_opts", dhcp_opts_id)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"DHCP Options {dhcp_opts_id} does not exist")
                return True
            print(f"Error deleting DHCP Options {dhcp_opts_id}: {e}")

    # Function to delete a VPC
    def vpc(self, vpc_id):
        try:
            if not self.dry_run:
                self.ec2_client.delete_vpc(VpcId=vpc_id)
            print(f"Deleted VPC: {vpc_id}")
            DELETED_RESOURCES["vpc"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("vpc", vpc_id)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"VPC {vpc_id} does not exist")
                return True
            print(f"Error deleting VPC {vpc_id}: {e}")

    # Function to delete an EBS Volume
    def volume(self, vol_id):
        try:
            if not self.dry_run:
                self.ec2_client.delete_volume(VolumeId=vol_id)
            print(f"Deleted Volume: {vol_id}")
            DELETED_RESOURCES["volume"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("volume", vol_id)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"Volume {vol_id} does not exist")
                return True
            print(f"Error deleting Volume {vol_id}: {e}")

    # Function to delete an S3 Bucket
    # Note: The bucket must be empty before it can be deleted
    def s3_bucket(self, bucket_name):
        def delete_objects(bucket_name):
            paginator = self.s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket_name):
                if "Contents" in page:
                    print("Some contents is here")
                    # Create a list of object keys to delete
                    objects_to_delete = [{"Key": obj["Key"]} for obj in page["Contents"]]
                    print("Going to delete objects:", len(objects_to_delete), "objects")
                    # Delete the objects
                    if not self.dry_run:
                        self.s3_client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects_to_delete})

        try:
            delete_objects(bucket_name)
            print(f"Deleted all contents of bucket: {bucket_name}")
            if not self.dry_run:
                self.s3_client.delete_bucket(Bucket=bucket_name)
            print(f"Deleted S3 bucket: {bucket_name}")
            DELETED_RESOURCES["s3"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("s3_bucket", bucket_name)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"S3 bucket {bucket_name} does not exist")
                return True
            print(f"Error deleting S3 bucket {bucket_name}: {e}")

    # Function to delete an AWS IAM user
    def iam_user(self, user):
        try:
            policies = self.iam_client.list_user_policies(UserName=user)
            if not self.dry_run:
                for policy in policies["PolicyNames"]:
                    self.iam_client.delete_user_policy(UserName=user, PolicyName=policy)
            print(f"Deleted Policies for User: {user}")
            access_keys = self.iam_client.list_access_keys(UserName=user)
            if not self.dry_run:
                for key in access_keys["AccessKeyMetadata"]:
                    self.iam_client.delete_access_key(UserName=user, AccessKeyId=key["AccessKeyId"])
            print(f"Deleted Access Keys for User: {user}")
            if not self.dry_run:
                self.iam_client.delete_user(UserName=user)
            print(f"Deleted User: {user}")
            DELETED_RESOURCES["iam_user"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("iam_user", user)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"User {user} does not exist")
                return True
            print(f"Error deleting User {user}: {e}")

    # Function to delete an AWS IAM instance profiles
    def iam_instance_profile(self, profile):
        try:
            profile_roles = profile["Roles"]
            profile_name = profile["InstanceProfileName"]
            if not self.dry_run:
                for role in profile_roles:
                    self.iam_client.remove_role_from_instance_profile(
                        InstanceProfileName=profile_name, RoleName=role["RoleName"]
                    )
                    try:
                        self.iam_client.delete_role(RoleName=role["RoleName"])
                    except Exception:
                        self.iam_role(role["RoleName"])
            if profile_roles:
                print(f"Deleted Roles for Instance Profile: {profile_name}")
            if not self.dry_run:
                self.iam_client.delete_instance_profile(InstanceProfileName=profile_name)
            print(f"Deleted Instance profile: {profile_name}")
            DELETED_RESOURCES["iam_profile"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("iam_profile", profile_name)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"Instance profile {profile['InstanceProfileName']} does not exist")
                return True
            print(f"Error deleting Role {profile['InstanceProfileName']}: {e}")

    # Function to delete an AWS IAM roles
    def iam_role(self, role):
        try:
            at_policies = self.iam_client.list_attached_role_policies(RoleName=role)
            if not self.dry_run:
                for policy in at_policies["AttachedPolicies"]:
                    self.iam_client.delete_policy(RoleName=role, PolicyArn=policy["PolicyArn"])
            if at_policies.get("AttachedPolicies"):
                print(f"Deleted Attached Policies for Role: {role}")

            policies = self.iam_client.list_role_policies(RoleName=role)
            if not self.dry_run:
                for policy in policies["PolicyNames"]:
                    self.iam_client.delete_role_policy(RoleName=role, PolicyName=policy)
            if policies.get("PolicyNames"):
                print(f"Deleted Policies for Role: {role}")

            if not self.dry_run:
                self.iam_client.delete_role(RoleName=role)
            print(f"Deleted Role: {role}")
            DELETED_RESOURCES["iam_role"] += 1
            TOTAL_SAVED["total"] += self.price.estimate("iam_role", role)
            return True
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"Role {role} does not exist")
                return True
            print(f"Error deleting Role {role}: {e}")


def has_expired(obj):
    def _parse_expiration_date(date_str):
        # Manually parse the string assuming the format "YYYY-MM-DDTHH:MM+00:00"
        try:
            date_part, time_part = date_str.split("T")
            year, month, day = map(int, date_part.split("-"))
            hour, minute = map(int, time_part.split("+")[0].split(":"))
            # Create a datetime object with the parsed values
            return datetime.datetime(year, month, day, hour, minute, tzinfo=datetime.timezone.utc)
        except Exception as e:
            print(f"Error parsing date: {e}")
            return None

    tags = obj.get("Tags", [])
    if not tags:
        return False
    # Current UTC time
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    # Build a dictionary from the tag list for easy lookup
    tag_dict = {tag["Key"]: tag["Value"] for tag in tags}

    for tag in obj.get("Tags", []):
        if tag["Key"] == "expirationDate":
            expiration_date = _parse_expiration_date(tag_dict["expirationDate"])
            if expiration_date is None:
                continue

            # Check if the expiration date is more than 6 hours late
            if now_utc > expiration_date + datetime.timedelta(hours=HOURS_TO_EXPIRE):
                obj.update({"delta": (now_utc - expiration_date)})
                return True
    return False


def unattached(eip_obj):
    return "InstanceId" not in eip_obj and "NetworkInterfaceId" not in eip_obj


def old_dated(obj):

    def get_tag(obj, key):
        for tag in obj.get("Tags", []):
            if tag.get("Key", "") == key:
                return tag["Value"]
        return ""

    if (
        not ("Name" in obj and obj["Name"].startswith(CI_TAG))
        and not ("Tags" in obj and has_ci_tag(obj))
        and not ("UserName" in obj and obj["UserName"].startswith(CI_TAG))
        and not ("RoleName" in obj and obj["RoleName"].startswith(CI_TAG))
        and not ("InstanceProfileName" in obj and obj["InstanceProfileName"].startswith(CI_TAG))
        and not ("DhcpOptionsId" in obj and get_tag(obj, "cg-Name").startswith(CI_TAG))
    ):
        return False
    creation_date = None
    if "CreateDate" in obj:
        creation_date = obj["CreateDate"]
    if "CreateTime" in obj:
        creation_date = obj["CreateTime"]
    if creation_date:
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        if now_utc > creation_date + datetime.timedelta(hours=HOURS_TO_EXPIRE):
            return True
    return False


def has_ci_tag(obj, tag=CI_TAG):
    tags = obj.get("Tags", [])
    tags = {tag["Key"]: tag["Value"] for tag in tags}
    return any([i.replace("kubernetes.io/cluster/", "").startswith(tag) for i in tags.keys()])


def parse_args():
    import argparse

    parser = argparse.ArgumentParser(description="AWS Resource Deletion")
    parser.add_argument("--tag", default="ci-op-", help="Tag to search for")
    parser.add_argument("--profile", default="telco-ci", help="AWS Profile to use")
    parser.add_argument(
        "--region", default=None, choices=["us-east-1", "us-east-2", "us-west-1", "us-west-2"], help="AWS Region to use"
    )
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    parser.add_argument("--send-email", action="store_true", help="Send email report", default=False)
    return parser.parse_args()


def create_report():
    # Create report content first
    report = (
        f"Hi,\nToday's cleanup run has saved you:\n\n"
        f"💰 ${(TOTAL_SAVED['total'] * 24):.2f} USD per day,\n"
        f"💰 ${(TOTAL_SAVED['total'] * 24 * 7):.2f} USD per week,\n"
        f"💰 ${(TOTAL_SAVED['total'] * 24 * 30):.2f} USD per month,\n"
        f"💰 ${(TOTAL_SAVED['total'] * 24 * 365):.2f} USD per year\n\n"
        f"Thanks,\nAWS Cleanup Bot\nSend any questions or comments to sshnaidm@redhat.com"
    )

    # Write to file
    with open("report.txt", "w") as f:
        f.write(report)

    # send report by mail
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart()
    msg["Subject"] = f"💲 AWS Resource Deletion Report - saved ${TOTAL_SAVED['total'] * 24 * 30:.2f} USD per month"
    msg["From"] = "telco5g-ci@redhat.com"
    msg["To"] = "sshnaidm@redhat.com"
    msg.attach(MIMEText(report, "plain"))
    # msg.attach(MIMEApplication(open('report.txt', 'rb').read(), Name='report.txt'))
    with smtplib.SMTP("smtp.corp.redhat.com", 25) as server:
        server.sendmail(msg["From"], msg["To"], msg.as_string())


def main():
    args = parse_args()
    # Create a session using the specified profile
    regions = [args.region] if args.region else ["us-east-1", "us-east-2", "us-west-1", "us-west-2"]
    pricing_session = boto3.Session(profile_name=args.profile, region_name="us-east-1")
    pricing_client = pricing_session.client("pricing")
    for region in regions:
        boto3_session = boto3.Session(profile_name=args.profile, region_name=region)
        # Create service clients

        ec2_client = boto3_session.client("ec2")
        elb_client = boto3_session.client("elb")
        elbv2_client = boto3_session.client("elbv2")
        s3_client = boto3_session.client("s3")
        iam_client = boto3_session.client("iam")
        q = AWSResourceDeletion(
            ec2_client, elb_client, elbv2_client, s3_client, iam_client, pricing_client, args.tag, args.dry_run
        )
        q.run()
    for key, value in DELETED_RESOURCES.items():
        print(f"Deleted total {key} resources: {value}")
    print(
        f"Total saved:\n"
        f"${(TOTAL_SAVED['total'] * 24):.2f} USD per day,\n"
        f"${(TOTAL_SAVED['total'] * 24 * 7):.2f} USD per week,\n"
        f"${(TOTAL_SAVED['total'] * 24 * 30):.2f} USD per month,\n"
        f"${(TOTAL_SAVED['total'] * 24 * 365):.2f} USD per year"
    )
    if args.send_email:
        create_report()


if __name__ == "__main__":
    main()
