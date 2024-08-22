# ec2_spot.py

import time
from typing import Dict
import boto3
import os
import base64
import dotenv
from botocore.exceptions import ClientError
from logging_config import logger

dotenv.load_dotenv('.env')

def get_user_data(ecr_image_uri, env_vars):
    env_vars_str = ' '.join([f'-e {k}="{v}"' for k, v in env_vars.items()])
    user_data_script = f"""#!/bin/bash
    exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
    set -e

    echo "Step 1: Starting user data script execution"

    echo "Step 2: Installing Docker"
    amazon-linux-extras install docker -y > /dev/null 2>&1 # silencing the terminal spam
    systemctl start docker
    systemctl enable docker
    usermod -a -G docker ec2-user
    echo "Docker installation completed"

    echo "Step 3: Configuring AWS CLI"
    aws configure set region {os.environ.get('AWS_REGION')}
    echo "AWS CLI configuration completed"

    ECR_URI=$(echo {ecr_image_uri} | sed 's|^https://||')

    echo "Step 4: ECR login"
    $(aws ecr get-login --no-include-email --region {os.environ.get('AWS_REGION')})
    echo "ECR login completed"

    echo "Step 5: Pulling Docker image"
    docker pull --platform linux/amd64 $ECR_URI
    docker pull --platform linux/amd64 363187237379.dkr.ecr.us-east-1.amazonaws.com/spotty-monitoring:latest
    echo "Docker image pull completed"

    docker run -d --name main-container -p 80:80 -p 3928:3928 {env_vars_str} $ECR_URI
    echo "Main container started"

    docker run -d --name monitor-container \
        --network container:main-container \
        -v /var/run/docker.sock:/var/run/docker.sock \
        363187237379.dkr.ecr.us-east-1.amazonaws.com/spotty-monitoring:latest
    echo "Monitoring container started"

    echo "User data script completed successfully"
    """
    return base64.b64encode(user_data_script.encode()).decode()

def request_spot_instance(ecr_image_uri, instance_name, env_vars):
    required_vars = ['TF_AMI_ID', 'TF_INSTANCE_TYPE', 'TF_SECURITY_GROUP_ID', 
                     'TF_SUBNET_ID', 'TF_INSTANCE_PROFILE_NAME', 'AWS_REGION']
    
    for var in required_vars:
        if not os.environ.get(var):
            raise EnvironmentError(f"Environment variable {var} is not set")
    
    ami_id = os.environ['TF_AMI_ID']
    instance_type = os.environ['TF_INSTANCE_TYPE']
    security_group_id = os.environ['TF_SECURITY_GROUP_ID']
    subnet_id = os.environ['TF_SUBNET_ID']
    instance_profile_name = os.environ['TF_INSTANCE_PROFILE_NAME']

    ec2_client = boto3.client('ec2', region_name=os.environ['AWS_REGION'])
    
    spot_price = 0.005  # starting bid price
    max_attempts = 10
    spot_price_increment = 0.001 # bid increase delta
    attempt = 0

    while attempt < max_attempts:
        try:
            response = ec2_client.request_spot_instances(
                SpotPrice=str(spot_price),
                InstanceCount=1,
                Type='one-time',
                LaunchSpecification={
                    'ImageId': ami_id,
                    'InstanceType': instance_type,
                    'SecurityGroupIds': [security_group_id],
                    'SubnetId': subnet_id,
                    'IamInstanceProfile': {'Name': instance_profile_name},
                    'UserData': get_user_data(ecr_image_uri, env_vars)                }
            )
            
            spot_request_id = response['SpotInstanceRequests'][0]['SpotInstanceRequestId']
            logger.info(f"Spot instance request ID: {spot_request_id}")
            
            # waiter stops program exec and checks every 15 seconds if need is fulfilled twice
            logger.info(f"Waiting for spot instance to be fulfilled (Attempt {attempt + 1}, Price: ${spot_price:.4f})...")
            waiter = ec2_client.get_waiter('spot_instance_request_fulfilled')
            waiter.wait(SpotInstanceRequestIds=[spot_request_id], WaiterConfig={'Delay': 15, 'MaxAttempts': 2})
            
            response = ec2_client.describe_spot_instance_requests(SpotInstanceRequestIds=[spot_request_id])
            instance_id = response['SpotInstanceRequests'][0]['InstanceId']
            logger.info(f"Spot instance fulfilled. Instance ID: {instance_id}")

            # give the instance a name on aws
            ec2_client.create_tags(
                Resources=[instance_id],
                Tags=[{'Key': 'Name', 'Value': instance_name}]
            )
            
            return instance_id, spot_price, time.time()

        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            logger.error(f"ClientError: {error_code} - {error_message}")
            
            if error_code in ['MaxSpotInstanceCountExceeded', 'InstanceLimitExceeded']:
                logger.error("Spot Instance limit reached. Please check your AWS quotas.")
                return None, None, time.time()
            elif error_code == 'InsufficientInstanceCapacity':
                logger.error("Insufficient capacity for the requested instance type.")
                return None, None, time.time()
            else:
                spot_price += spot_price_increment
                logger.info(f"Increasing price to ${spot_price:.4f} and retrying...")
                attempt += 1

        except Exception as e:
            logger.exception(f"Unexpected error in request_spot_instance: {str(e)}")
            return None, None, time.time()

    logger.error("Failed to create Spot Instance after maximum attempts")
    return None, None, time.time()

def get_instance_public_ip(ec2_client, instance_id, max_retries=10, delay=10):
    for _ in range(max_retries):
        instance_info = ec2_client.describe_instances(InstanceIds=[instance_id])
        if 'PublicIpAddress' in instance_info['Reservations'][0]['Instances'][0]:
            return instance_info['Reservations'][0]['Instances'][0]['PublicIpAddress']
        logger.info(f"Public IP not yet available. Waiting {delay} seconds...")
        time.sleep(delay)
    raise Exception("Failed to get public IP address after multiple retries")

def terminate_instance(instance_id: str):
    ec2_client = boto3.client('ec2', region_name=os.environ.get('AWS_REGION'))
    ec2_client.terminate_instances(InstanceIds=[instance_id])

def create_instance(ecr_image_uri: str, instance_name: str, env_vars: Dict[str, str]):
    try:
        instance_id, spot_price, time_now = request_spot_instance(ecr_image_uri, instance_name, env_vars)
        
        if not instance_id:
            logger.error(f"Failed to create Spot Instance for {instance_name}")
            return None

        ec2_client = boto3.client('ec2', region_name=os.environ.get('AWS_REGION'))
        
        try:
            public_ip = get_instance_public_ip(ec2_client, instance_id)
        except Exception as e:
            logger.error(f"Failed to get public IP for instance {instance_id}: {str(e)}")
            public_ip = None

        return {
            "id": instance_id,
            "ip": public_ip,
            "name": instance_name,
            "spot_price": spot_price,
            "time_now": time_now
        }
    except Exception as e:
        logger.exception(f"Error in create_instance: {str(e)}")
        return None
