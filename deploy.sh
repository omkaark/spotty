#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Pipelines return the exit status of the last command in the pipe to fail
set -o pipefail

# Treat unset variables as an error when substituting
set -u

set -a
source .env
set +a

# Check for required environment variables
required_vars=("TF_AMI_ID" "TF_INSTANCE_TYPE" "TF_SECURITY_GROUP_ID" "TF_SUBNET_ID" "TF_INSTANCE_PROFILE_NAME" "AWS_REGION")
for var in "${required_vars[@]}"; do
    if [ -z "${!var}" ]; then
        echo "Error: Environment variable $var is not set"
        exit 1
    fi
done

if [ $# -eq 0 ]; then
    echo "Error: Docker image not provided"
    echo "Usage: $0 <docker-image:tag>"
    exit 1
fi

DOCKER_IMAGE=$(echo "$1" | sed 's|^https://||')
INSTANCE_NAME="docker-image-loader-$(date +%s)"
VOLUME_SIZE=4
VOLUME_TYPE="gp2"
VOLUME_NAME=$DOCKER_IMAGE

# Get the availability zone for the subnet
AZ=$(aws ec2 describe-subnets \
    --subnet-ids "$TF_SUBNET_ID" \
    --query 'Subnets[0].AvailabilityZone' \
    --output text \
    --region "$AWS_REGION")

# Create EBS volume with a name tag
echo "Creating EBS volume..."
VOLUME_ID=$(aws ec2 create-volume \
    --size "$VOLUME_SIZE" \
    --volume-type "$VOLUME_TYPE" \
    --availability-zone "$AZ" \
    --region "$AWS_REGION" \
    --tag-specifications "ResourceType=volume,Tags=[{Key=Name,Value=$VOLUME_NAME}]" \
    --query 'VolumeId' \
    --output text)

echo "Volume ID: $VOLUME_ID"
echo "Volume Name: $VOLUME_NAME"

# Wait for volume to be available
echo "Waiting for volume to be available..."
aws ec2 wait volume-available --volume-ids "$VOLUME_ID" --region "$AWS_REGION"

# Now define USER_DATA after VOLUME_ID is available
USER_DATA=$(cat << 'EOF'
#!/bin/bash
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

echo "Starting user data script execution at $(date)"

DOCKER_IMAGE="__DOCKER_IMAGE__"
VOLUME_ID="__VOLUME_ID__"

# Function to find the device
find_device() {
    # Check for traditional device names
    if [ -e /dev/xvdf ]; then
        DEVICE="/dev/xvdf"
        echo "Found device at $DEVICE"
        return
    fi

    # Check for NVMe devices
    if ! command -v nvme &> /dev/null; then
        echo "nvme-cli not found. Installing..."
        sudo yum install -y nvme-cli
    fi

    for device in /dev/nvme*n1; do
        if [ -e "$device" ]; then
            volume_id=$(nvme id-ctrl -v $device | grep -o 'vol-[a-f0-9]\+')
            echo "Device $device has volume ID $volume_id"
            if [ "$volume_id" = "$VOLUME_ID" ]; then
                DEVICE=$device
                echo "Found matching device: $DEVICE"
                return
            fi
        fi
    done

    echo "Error: Could not find the device for volume $VOLUME_ID"
    exit 1
}

# Wait for EBS volume to be attached
echo "Waiting for EBS volume to be attached..."
attempt=0
max_attempts=60  # 5 minutes maximum wait time
while true; do
    sleep 5
    attempt=$((attempt+1))
    echo "Attempt $attempt: Checking for EBS volume..."

    find_device

    if [ -n "$DEVICE" ]; then
        echo "EBS volume attached successfully as $DEVICE"
        break
    fi

    if [ $attempt -ge $max_attempts ]; then
        echo "Error: EBS volume not attached after 5 minutes. Exiting."
        exit 1
    fi
done

sleep 2

# Check if the volume has a file system
if ! file -s $DEVICE | grep -q filesystem; then
    echo "Creating XFS file system on $DEVICE"
    if ! mkfs -t xfs $DEVICE; then
        echo "Failed to create XFS filesystem. Exiting."
        exit 1
    fi
    echo "XFS filesystem created successfully"
else
    echo "File system already exists on $DEVICE"
fi

sleep 2

# Create mount point
echo "Creating mount point /data"
mkdir -p /data

sleep 2

# Mount the volume
echo "Mounting the volume"
mount $DEVICE /data
if [ $? -ne 0 ]; then
    echo "Failed to mount the volume. Exiting."
    exit 1
fi

sleep 2

echo "Mounted volume contents:"
ls -la /data

# Check if Docker is installed and running
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Installing Docker..."
    sudo yum update -y
    sudo yum install docker -y
    sudo systemctl start docker
    sudo systemctl enable docker
fi

# Ensure Docker is running
echo "Ensuring Docker is running..."
while ! docker info > /dev/null 2>&1; do
    echo "Waiting for Docker to start..."
    sleep 1
done

sleep 2

echo "Logging into ECR"
$(aws ecr get-login --no-include-email --region "us-east-1")
echo "ECR login completed"

sleep 2

# Pull and save Docker image
echo "Pulling Docker image: $DOCKER_IMAGE"
if docker pull $DOCKER_IMAGE; then
    echo "Docker image pulled successfully"
    echo "Saving Docker image to /data/docker_image.tar"
    if sudo docker save $DOCKER_IMAGE > /data/docker_image.tar; then
        echo "Docker image saved successfully"
        ls -l /data/docker_image.tar
    else
        echo "Failed to save Docker image"
        docker images
        df -h /data
        exit 1
    fi
else
    echo "Failed to pull Docker image"
    docker --version
    docker info
    exit 1
fi

sleep 2

# Verify the saved image
if [ -f /data/docker_image.tar ]; then
    echo "Verifying saved Docker image:"
    tar -tvf /data/docker_image.tar
else
    echo "Docker image file not found in /data"
    echo "Contents of /data directory:"
    ls -la /data
    echo "Disk space information:"
    df -h
fi

# Signal that the process is complete
echo "User data script completed at $(date)"
touch /tmp/user_data_complete
EOF
)

# Substitute placeholders with actual values
USER_DATA="${USER_DATA//__DOCKER_IMAGE__/$DOCKER_IMAGE}"
USER_DATA="${USER_DATA//__VOLUME_ID__/$VOLUME_ID}"
USER_DATA="${USER_DATA//__AWS_REGION__/$AWS_REGION}"
USER_DATA_ENCODED=$(echo "$USER_DATA" | base64)

# Create EC2 instance
echo "Creating EC2 instance..."
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$TF_AMI_ID" \
    --instance-type "$TF_INSTANCE_TYPE" \
    --security-group-ids "$TF_SECURITY_GROUP_ID" \
    --subnet-id "$TF_SUBNET_ID" \
    --iam-instance-profile Name="$TF_INSTANCE_PROFILE_NAME" \
    --user-data "$USER_DATA_ENCODED" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
    --region "$AWS_REGION" \
    --query 'Instances[0].InstanceId' \
    --output text)

echo "Instance ID: $INSTANCE_ID"

# Wait for instance to be running
echo "Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$AWS_REGION"

# Attach volume to instance
echo "Attaching volume to instance..."
aws ec2 attach-volume \
    --volume-id "$VOLUME_ID" \
    --instance-id "$INSTANCE_ID" \
    --device /dev/sdf \
    --region "$AWS_REGION"

# Wait for volume to be in-use
echo "Waiting for volume to be in-use..."
aws ec2 wait volume-in-use --volume-ids "$VOLUME_ID" --region "$AWS_REGION"

# Wait for user data script to complete (Implement a better mechanism in production)
echo "Waiting for user data script to complete..."
start_time=$(date +%s)
timeout=600  # 10 minutes timeout

while true; do
    current_time=$(date +%s)
    elapsed_time=$((current_time - start_time))

    if [ $elapsed_time -ge $timeout ]; then
        echo "Timeout reached. User data script did not complete in time."
        break
    fi

    # Check if the instance is still running
    instance_state=$(aws ec2 describe-instances \
        --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].State.Name' \
        --output text \
        --region "$AWS_REGION")

    if [ "$instance_state" != "running" ]; then
        echo "Instance state is $instance_state. Exiting wait loop."
        break
    fi

    # Check if the user data script completed
    # (Implement a proper check, e.g., via AWS SSM or checking for a completion signal)
    echo "Waiting for user data script to finish..."
    sleep 30
done

# Detach volume
echo "Detaching volume..."
aws ec2 detach-volume --volume-id "$VOLUME_ID" --region "$AWS_REGION"

# Wait for volume to be available after detaching
echo "Waiting for volume to be available after detaching..."
detach_start_time=$(date +%s)
detach_timeout=300  # 5 minutes timeout

while true; do
    current_time=$(date +%s)
    elapsed_time=$((current_time - detach_start_time))

    if [ $elapsed_time -ge $detach_timeout ]; then
        echo "Timeout reached. Volume detachment did not complete in time."
        break
    fi

    # Check volume status
    volume_state=$(aws ec2 describe-volumes \
        --volume-ids "$VOLUME_ID" \
        --query 'Volumes[0].State' \
        --output text \
        --region "$AWS_REGION")

    echo "Current volume state: $volume_state"

    if [ "$volume_state" = "available" ]; then
        echo "Volume successfully detached and available."
        break
    fi

    sleep 10
done

# Terminate the EC2 instance
echo "Terminating EC2 instance..."
aws ec2 terminate-instances --instance-ids "$INSTANCE_ID" --region "$AWS_REGION"

# Wait for the instance to be terminated
echo "Waiting for instance to be terminated..."
aws ec2 wait instance-terminated --instance-ids "$INSTANCE_ID" --region "$AWS_REGION"

echo "Script completed successfully!"
echo "EBS Volume ID: $VOLUME_ID has been created and detached."
echo "EBS Volume Name: $VOLUME_NAME"
echo "All other resources have been cleaned up."
