<p align="center">
  <img src="https://github.com/omkaark/spotty-monitoring/blob/main/static/spotty.png" height="200" alt="Spotty" />
</p>

# Spotty

## What is it?

Spotty is a Spot Container Orchestrator that I am building. I have a lot more infra explorations and this tool simplifies my dev workflow.

Yes... I know... Kubernetes and a bunch of other tools let people do this. So why did I build it? Spotty makes non-critical infrastructure cheaper, provisioning simpler and setup faster.

The following is a guide that provides step-by-step instructions on how to set up and run self-hosted Spotty.

## Prerequisites

Before you begin, ensure you have the following requirements installed:

- Python 3.8+
- pip
- Docker
- AWS CLI
- Terraform
- Access to a terminal or command line interface

## Installation

### Prepare Configuration Files

1. Locate the `.env.template` file in the root directory.
2. Fill in the required information.
3. Rename the file to `.env` (remove the `.template` suffix).
4. Locate the `terraform.tfvars.template` file.
5. Fill in the necessary details.
6. Rename the file to `terraform.tfvars` (remove the `.template` suffix).

### Set Up Docker ECR

Ensure your Amazon Elastic Container Registry (ECR) is correctly set up. For any folder in the `examples` directory that you want to test, verify that the `push.sh` file has the correct ECR repo setup.

### Install Required Packages

Navigate to the project directory and install the required Python packages (preferably in a [virtual environment](https://docs.python.org/3/library/venv.html)):

```bash
pip install -r requirements.txt
```

## Authentication

Ensure you are logged in to both the Docker ECR CLI and AWS CLI before proceeding.

## Usage

### Initialize the Environment

Run the setup script to initialize the environment:

```bash
source ./setup.sh
```

### Start the Application

Launch the main application:

```bash
python app.py
```

## Final Notes

- For troubleshooting and detailed logs, refer to any log files generated during the setup and running process.
- If you encounter any issues with Terraform or AWS services, ensure your AWS credentials are correctly configured and you have the necessary permissions.
- Remember to clean up any resources created in AWS to avoid unexpected charges when you're done using Spotty.
