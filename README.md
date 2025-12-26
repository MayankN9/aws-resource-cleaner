
# AWS Resource Cleaner 🚀

## ✅ Overview
This project automates the cleanup of AWS VPC resources using **Python** and **Boto3**. It helps reduce costs and maintain a clean environment by deleting unused resources such as:
- VPC Endpoints
- NAT Gateways
- Elastic IPs
- Internet Gateways
- Route Tables
- Subnets
- Security Groups
- (Optional) EC2 Instances

---

## ✅ Features
- **Interactive Prompts**: Choose regions, dry-run mode, and instance termination.
- **Dry-Run Mode**: Preview resources before deletion.
- **Tag-Based Safety**: Skips VPCs tagged as `env=prod` or `keep=true`.
- **Multi-Region Support**: Clean multiple regions in one run.
- **Logging**: Actions logged to `cleanup.log` for auditing.

---

## ✅ Tech Stack
- **Python 3**
- **Boto3**
- **AWS CloudShell** (or local environment)
- **GitHub** for version control

---

## ✅ Setup Instructions
### 1. Clone the Repository
```bash
git clone https://github.com/MayankN9/aws-resource-cleaner.git
cd aws-resource-cleaner


2. Install Dependencies
pip install -r requirements.txt

3.Run the Script
python3 aws_cleanup_runner.py

Follow prompts:

Enter AWS region(s): us-east-1, ap-south-1
Terminate EC2 instances? yes/no
Dry-run? yes/no
Type DELETE to confirm destructive actions.

