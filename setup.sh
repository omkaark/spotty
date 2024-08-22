#!/bin/bash

ROOT_DIR=$(pwd)

cd terraform

terraform init
terraform apply -auto-approve

# check if tf apply was successful
if [ $? -ne 0 ]; then
    echo "Terraform apply failed. Exiting."
    cd "$ROOT_DIR"
    exit 1
fi

# export outputs as envs
export TF_AMI_ID=$(terraform output -raw ami_id)
export TF_INSTANCE_TYPE=$(terraform output -raw instance_type)
export TF_SECURITY_GROUP_ID=$(terraform output -raw security_group_id)
export TF_SUBNET_ID=$(terraform output -raw subnet_id)
export TF_INSTANCE_PROFILE_NAME=$(terraform output -raw instance_profile_name)

cd "$ROOT_DIR"