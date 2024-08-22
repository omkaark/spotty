import boto3
from logging_config import logger
from state_manager import StateManager

state_manager = StateManager()

def cleanup_spot_requests():
    ec2_client = boto3.client('ec2')
    
    response = ec2_client.describe_spot_instance_requests(Filters=[{'Name': 'state', 'Values': ['open', 'active']}])
    
    request_ids = [request['SpotInstanceRequestId'] for request in response['SpotInstanceRequests']]
    
    if request_ids:
        ec2_client.cancel_spot_instance_requests(SpotInstanceRequestIds=request_ids)
        logger.info(f"Cancelled {len(request_ids)} Spot Instance requests")
    else:
        logger.info("No open Spot Instance requests to cancel")

def get_instance_vcpus(instance_type):
    instance_vcpus = {
        't2.micro': 1, 't2.small': 1, 't2.medium': 2, 't2.large': 2,
        'm5.large': 2, 'm5.xlarge': 4, 'm5.2xlarge': 8,
        'c5.large': 2, 'c5.xlarge': 4, 'c5.2xlarge': 8,
        'r5.large': 2, 'r5.xlarge': 4, 'r5.2xlarge': 8
    }
    return instance_vcpus.get(instance_type, 2)

def check_spot_quotas():
    ec2_client = boto3.client('ec2')
    service_quotas_client = boto3.client('service-quotas')
    spot_requests = ec2_client.describe_spot_instance_requests()
    
    try:
        quota_response = service_quotas_client.get_service_quota(
            ServiceCode='ec2',
            QuotaCode='L-34B43A08'  # code for "All Standard (A, C, D, H, I, M, R, T, Z) Spot Instance Requests"
        )
        quota_value = quota_response['Quota']['Value']
    except Exception as e:
        logger.exception(f"Error getting quota: {str(e)}")
        quota_value = "Unknown"

    vcpu_usage = sum(
        get_instance_vcpus(request['LaunchSpecification']['InstanceType'])
        for request in spot_requests['SpotInstanceRequests']
        if request['State'] in ['open', 'active']
    )

    logger.info(f"Current Spot Instance vCPU usage: {vcpu_usage}")
    logger.info(f"Spot Instance vCPU quota: {quota_value}")
    
    return vcpu_usage, quota_value

if __name__ == "__main__":
    cleanup_spot_requests()
    usage, quota = check_spot_quotas()
    logger.info(f"Current usage: {usage}, Quota: {quota}")