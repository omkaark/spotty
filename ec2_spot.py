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

import base64
import os

def get_user_data(ecr_image_uri, env_vars):
    env_vars_str = ' '.join([f'-e {k}="{v}"' for k, v in env_vars.items()])
    user_data_script = f"""#!/bin/bash
    exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
    set -e

    start_time=$(date +%s)

    echo "Step 1: Configuring AWS CLI"
    aws configure set region {os.environ.get('AWS_REGION')}
    step1_end=$(date +%s)
    echo "Step 1 duration: $((step1_end - start_time)) seconds"

    echo "Step 2: Preparing ECR URI"
    ECR_URI=$(echo {ecr_image_uri} | sed 's|^https://||')
    step2_end=$(date +%s)
    echo "Step 2 duration: $((step2_end - step1_end)) seconds"

    echo "Step 3: Mounting EBS volume"
    while [ ! -e /dev/xvdf ]; do
      echo "Waiting for EBS volume to be attached..."
      sleep 5
    done
    mkdir -p /data
    mount /dev/xvdf /data
    echo "Mounted EBS volume. Contents of /data:"
    ls -la /data
    step3_end=$(date +%s)
    echo "Step 3 duration: $((step3_end - step2_end)) seconds"

    echo "Step 4: Loading Docker image"
    if [ -f /data/docker_image.tar ]; then
        echo "Docker image file found. Loading..."
        docker load -i /data/docker_image.tar
    else
        echo "Error: Docker image file not found in /data"
        echo "Contents of /data directory:"
        ls -la /data
        exit 1
    fi
    step4_end=$(date +%s)
    echo "Step 4 duration: $((step4_end - step3_end)) seconds"

    echo "Step 5: Starting main container"
    docker run -d --name main-container -p 80:80 -p 3928:3928 {env_vars_str} $ECR_URI
    step5_end=$(date +%s)
    echo "Step 5 duration: $((step5_end - step4_end)) seconds"

    echo "Step 6: Starting monitoring container"
    docker run -d --name monitor-container \
        --network container:main-container \
        -v /var/run/docker.sock:/var/run/docker.sock \
        omkaark/spotty-monitoring:latest
    step6_end=$(date +%s)
    echo "Step 6 duration: $((step6_end - step5_end)) seconds"

    total_duration=$((step6_end - start_time))
    echo "Total duration: $total_duration seconds"

    echo "Second breakdown of each step:"
    echo "Step 1 (AWS CLI config): $((step1_end - start_time)) seconds"
    echo "Step 2 (ECR URI prep): $((step2_end - step1_end)) seconds"
    echo "Step 3 (Mount EBS volume): $((step3_end - step2_end)) seconds"
    echo "Step 4 (Load Docker image): $((step4_end - step3_end)) seconds"
    echo "Step 5 (Start main container): $((step5_end - step4_end)) seconds"
    echo "Step 6 (Start monitoring container): $((step6_end - step5_end)) seconds"

    echo "User data script completed successfully at $(date)"
    """
    return base64.b64encode(user_data_script.encode()).decode()

def request_spot_instance(ecr_image_uri, instance_name, env_vars):
    required_vars = ['TF_AMI_ID', 'TF_INSTANCE_TYPE', 'TF_SECURITY_GROUP_ID', 
                     'TF_SUBNET_ID', 'TF_INSTANCE_PROFILE_NAME', 'AWS_REGION']
    
    for var in required_vars:
        if not os.environ.get(var):
            raise EnvironmentError(f"Environment variable {var} is not set")
        
    volume_id = "vol-0754cb603c08a75fa"
    
    ami_id = os.environ['TF_AMI_ID']
    instance_type = os.environ['TF_INSTANCE_TYPE']
    security_group_id = os.environ['TF_SECURITY_GROUP_ID']
    subnet_id = os.environ['TF_SUBNET_ID']
    instance_profile_name = os.environ['TF_INSTANCE_PROFILE_NAME']

    ec2_client = boto3.client('ec2', region_name=os.environ['AWS_REGION'])
    
    spot_price = 0.005
    max_attempts = 10
    spot_price_increment = 0.001
    attempt = 0

    while attempt < max_attempts:
        try:
            # First, describe the volume to get its Availability Zone
            volume_response = ec2_client.describe_volumes(VolumeIds=[volume_id])
            volume_az = volume_response['Volumes'][0]['AvailabilityZone']

            # Now, request the spot instance in the same AZ as the volume
            response = ec2_client.request_spot_instances(
                SpotPrice=str(spot_price),
                InstanceCount=1,
                Type='one-time',
                LaunchSpecification={
                    'ImageId': ami_id,
                    'InstanceType': instance_type,
                    'SecurityGroupIds': [security_group_id],
                    'SubnetId': subnet_id,
                    'Placement': {
                        'AvailabilityZone': volume_az
                    },
                    'IamInstanceProfile': {'Name': instance_profile_name},
                    'UserData': get_user_data(ecr_image_uri, env_vars)
                }
            )
            
            spot_request_id = response['SpotInstanceRequests'][0]['SpotInstanceRequestId']
            logger.info(f"Spot instance request ID: {spot_request_id}")
            
            logger.info(f"Waiting for spot instance to be fulfilled (Attempt {attempt + 1}, Price: ${spot_price:.4f})...")
            waiter = ec2_client.get_waiter('spot_instance_request_fulfilled')
            waiter.wait(SpotInstanceRequestIds=[spot_request_id], WaiterConfig={'Delay': 15, 'MaxAttempts': 2})
            
            response = ec2_client.describe_spot_instance_requests(SpotInstanceRequestIds=[spot_request_id])
            instance_id = response['SpotInstanceRequests'][0]['InstanceId']
            logger.info(f"Spot instance fulfilled. Instance ID: {instance_id}")

            # Wait for the instance to be running
            instance_waiter = ec2_client.get_waiter('instance_running')
            instance_waiter.wait(InstanceIds=[instance_id])
            logger.info(f"Instance {instance_id} is now running")

            # Attach the existing volume
            ec2_client.attach_volume(
                Device='/dev/xvdf',
                InstanceId=instance_id,
                VolumeId=volume_id
            )
            logger.info(f"Attached volume {volume_id} to instance {instance_id}")

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
    
    try:
        # Describe the instance to get the attached volume
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        volumes = response['Reservations'][0]['Instances'][0]['BlockDeviceMappings']
        
        # Detach all volumes attached to the instance
        for volume in volumes:
            if 'Ebs' in volume and volume['DeviceName'] != '/dev/xvda':
                volume_id = volume['Ebs']['VolumeId']
                logger.info(f"Detaching volume {volume_id} from instance {instance_id}")
                ec2_client.detach_volume(
                    VolumeId=volume_id,
                    InstanceId=instance_id,
                    Force=True
                )
                
                # Wait for the volume to be detached
                waiter = ec2_client.get_waiter('volume_available')
                waiter.wait(VolumeIds=[volume_id])
                logger.info(f"Volume {volume_id} detached successfully")
        
        # Terminate the instance
        logger.info(f"Terminating instance {instance_id}")
        ec2_client.terminate_instances(InstanceIds=[instance_id])
        
        # Wait for the instance to be terminated
        waiter = ec2_client.get_waiter('instance_terminated')
        waiter.wait(InstanceIds=[instance_id])
        logger.info(f"Instance {instance_id} terminated successfully")
    
    except ClientError as e:
        logger.error(f"Error in terminate_instance: {e}")
        raise
    except Exception as e:
        logger.exception(f"Unexpected error in terminate_instance: {str(e)}")
        raise
    
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
