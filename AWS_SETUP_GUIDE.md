# CloudBox – AWS Setup Guide

This guide walks you through deploying CloudBox on AWS step by step using the AWS Console.  
All resource names use the `cloudbox-` prefix so they're easy to find.

---

## What You're Building

```
Internet → ALB (Load Balancer) → EC2 (your Flask app) → RDS (database)
                                                       → S3  (file storage)
```

---

## Step 1 – Create Your VPC (Virtual Private Cloud)

**Go to:** VPC → Your VPCs → Create VPC

| Setting | Value |
|---|---|
| Name tag | `cloudbox-vpc` |
| IPv4 CIDR | `10.0.0.0/16` |

**Then create subnets:**

| Name | AZ | CIDR | Type |
|---|---|---|---|
| `cloudbox-pub-1a` | us-east-1a | 10.0.1.0/24 | Public |
| `cloudbox-pub-1b` | us-east-1b | 10.0.2.0/24 | Public |
| `cloudbox-priv-1a` | us-east-1a | 10.0.11.0/24 | Private |
| `cloudbox-priv-1b` | us-east-1b | 10.0.12.0/24 | Private |
| `cloudbox-rds-1a` | us-east-1a | 10.0.21.0/24 | Private (RDS) |
| `cloudbox-rds-1b` | us-east-1b | 10.0.22.0/24 | Private (RDS) |

**Internet Gateway:**  
VPC → Internet Gateways → Create → Name: `cloudbox-igw` → Attach to `cloudbox-vpc`

**NAT Gateway:**  
VPC → NAT Gateways → Create → Subnet: `cloudbox-pub-1a` → Allocate Elastic IP → Name: `cloudbox-nat`

**Route Tables:**

- Public RT (`cloudbox-rt-public`): route `0.0.0.0/0 → cloudbox-igw`, associate pub subnets  
- Private RT (`cloudbox-rt-private`): route `0.0.0.0/0 → cloudbox-nat`, associate priv + rds subnets

---

## Step 2 – Security Groups

**Go to:** VPC → Security Groups → Create Security Group

### ALB Security Group: `cloudbox-alb-sg`
| Type | Port | Source |
|---|---|---|
| HTTP | 80 | 0.0.0.0/0 |
| HTTPS | 443 | 0.0.0.0/0 |

### EC2 Security Group: `cloudbox-ec2-sg`
| Type | Port | Source |
|---|---|---|
| HTTP | 80 | `cloudbox-alb-sg` |
| SSH | 22 | Your IP (e.g. 203.0.113.5/32) |

### RDS Security Group: `cloudbox-rds-sg`
| Type | Port | Source |
|---|---|---|
| PostgreSQL | 5432 | `cloudbox-ec2-sg` |

---

## Step 3 – IAM Role for EC2

**Go to:** IAM → Roles → Create Role

1. Trusted entity: **AWS service** → EC2
2. Add permission: **AmazonS3FullAccess**
3. Role name: `cloudbox-ec2-role`

This lets your EC2 instance upload files to S3 without hardcoded keys.

---

## Step 4 – S3 Bucket

**Go to:** S3 → Create Bucket

| Setting | Value |
|---|---|
| Bucket name | `cloudbox-files-YOURNAME` (must be globally unique) |
| Region | us-east-1 |
| Block all public access | ✅ ON |

**Enable versioning:** Properties tab → Versioning → Enable

**Add lifecycle rule:**  
Management tab → Create lifecycle rule  
- Name: `cloudbox-archive`  
- Move to Standard-IA after 30 days  
- Move to Glacier after 90 days

---

## Step 5 – RDS Database

**Go to:** RDS → Create Database

| Setting | Value |
|---|---|
| Engine | PostgreSQL 16 |
| Template | Free tier (or Dev/Test) |
| DB identifier | `cloudbox-db` |
| Master username | `cloudbox_admin` |
| Master password | (choose a strong password) |
| DB name | `cloudbox` |
| Instance | db.t3.micro |
| Storage | 20 GB gp2, autoscaling off |
| VPC | `cloudbox-vpc` |
| Subnet group | Create new → add both RDS subnets |
| Security group | `cloudbox-rds-sg` |
| Public access | ❌ NO |
| Multi-AZ | Optional (costs more) |

**After creation**, copy the endpoint — you'll need it.

---

## Step 6 – Launch Your EC2 Instance

**Go to:** EC2 → Launch Instance

| Setting | Value |
|---|---|
| Name | `cloudbox-web-01` |
| AMI | Ubuntu Server 22.04 LTS |
| Instance type | t3.micro (or t2.micro for Free Tier) |
| Key pair | Create new or use existing |
| VPC | `cloudbox-vpc` |
| Subnet | `cloudbox-pub-1a` |
| Auto-assign public IP | ✅ Enable |
| Security group | `cloudbox-ec2-sg` |
| IAM instance profile | `cloudbox-ec2-role` |
| Storage | 20 GB gp3 |

---

## Step 7 – Deploy the Application

**SSH into your instance:**
```bash
ssh -i your-key.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

**Upload your code (from your laptop):**
```bash
scp -i your-key.pem -r cloudbox_friend/ ubuntu@YOUR_EC2_PUBLIC_IP:/tmp/cloudbox/
```

**On the EC2 instance, run setup:**
```bash
chmod +x /tmp/cloudbox/setup_ec2.sh
bash /tmp/cloudbox/setup_ec2.sh
```

**Edit the environment file with real values:**
```bash
sudo nano /opt/cloudbox/.env
```

Fill in:
```
DATABASE_HOST=cloudbox-db.xxxxxxxxxx.us-east-1.rds.amazonaws.com
DATABASE_PORT=5432
DATABASE_NAME=cloudbox
DATABASE_USER=cloudbox_admin
DATABASE_PASSWORD=YourRealPassword
STORAGE_BUCKET=cloudbox-files-YOURNAME
CLOUD_REGION=us-east-1
APP_SECRET=some-very-long-random-secret-string-here
```

**Create the database tables:**
```bash
PGPASSWORD=YourRealPassword psql -h YOUR_RDS_ENDPOINT -U cloudbox_admin -d cloudbox << 'SQL'
CREATE TABLE IF NOT EXISTS accounts (
    id SERIAL PRIMARY KEY,
    account_name VARCHAR(80) UNIQUE NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    plan VARCHAR(20) DEFAULT 'Free',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS uploads (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    s3_key VARCHAR(512) NOT NULL,
    file_size BIGINT DEFAULT 0,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    full_name VARCHAR(120) NOT NULL,
    email VARCHAR(120),
    company VARCHAR(120),
    storage_used VARCHAR(20) DEFAULT '0 MB',
    storage_limit VARCHAR(20) DEFAULT '5 GB',
    status VARCHAR(20) DEFAULT 'Active',
    plan VARCHAR(20) DEFAULT 'Pro',
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
SQL
```

**Restart the app:**
```bash
sudo systemctl restart cloudbox
sudo systemctl status cloudbox
```

**Test:** Open `http://YOUR_EC2_PUBLIC_IP` in your browser.

---

## Step 8 – EBS Snapshot (Backup of Disk)

**Go to:** EC2 → Volumes → select your instance volume  
Actions → Create Snapshot  
- Description: `cloudbox-backup-v1`

This saves your disk state. If anything breaks you can restore.

---

## Step 9 – Create AMI (Machine Image)

**Go to:** EC2 → Instances → select your instance  
Actions → Image and templates → Create image

| Setting | Value |
|---|---|
| Image name | `cloudbox-ami-v1` |
| Description | CloudBox production image v1 |

Wait ~5 minutes. The AMI will appear under EC2 → AMIs.

This is a full snapshot of your configured EC2. You'll use it to launch identical copies behind the load balancer.

---

## Step 10 – Launch Template

**Go to:** EC2 → Launch Templates → Create launch template

| Setting | Value |
|---|---|
| Name | `cloudbox-lt` |
| AMI | `cloudbox-ami-v1` |
| Instance type | t3.micro |
| Key pair | (your key) |
| Security group | `cloudbox-ec2-sg` |
| IAM instance profile | `cloudbox-ec2-role` |

---

## Step 11 – Application Load Balancer (ALB)

**Create Target Group first:**  
EC2 → Target Groups → Create

| Setting | Value |
|---|---|
| Name | `cloudbox-tg` |
| Target type | Instances |
| Protocol | HTTP |
| Port | 80 |
| VPC | `cloudbox-vpc` |
| Health check path | `/` |

Register your running EC2 as a target.

**Create ALB:**  
EC2 → Load Balancers → Create → Application Load Balancer

| Setting | Value |
|---|---|
| Name | `cloudbox-alb` |
| Scheme | Internet-facing |
| VPC | `cloudbox-vpc` |
| Subnets | `cloudbox-pub-1a`, `cloudbox-pub-1b` |
| Security group | `cloudbox-alb-sg` |
| Listener | HTTP:80 → Forward to `cloudbox-tg` |

After creation, copy the **DNS name** — this is your public URL.

---

## Step 12 – Auto Scaling Group (ASG)

**Go to:** EC2 → Auto Scaling Groups → Create

| Setting | Value |
|---|---|
| Name | `cloudbox-asg` |
| Launch template | `cloudbox-lt` |
| VPC | `cloudbox-vpc` |
| Subnets | `cloudbox-pub-1a`, `cloudbox-pub-1b` |
| Attach to ALB | `cloudbox-tg` |
| Desired capacity | 1 |
| Minimum | 1 |
| Maximum | 3 |
| Scaling policy | Target tracking – CPU 60% |

---

## Step 13 – CloudWatch Monitoring

**Go to:** CloudWatch → Alarms → Create Alarm

**CPU High alarm:**
- Metric: EC2 → By Auto Scaling Group → `cloudbox-asg` → CPUUtilization
- Condition: Greater than 70% for 2 data points
- Action: (optional) Send SNS email notification

**Storage alarm:**
- Metric: S3 → your bucket → BucketSizeBytes
- Condition: Greater than 4 GB

**CloudWatch Dashboard:**  
Dashboards → Create → `cloudbox-dashboard`  
Add widgets: CPU Utilization, ALB Request Count, RDS Connections, S3 Bucket Size

---

## Step 14 – How to Update the App

When you fix a bug or change code:

1. SSHinto your EC2 and update the files:
   ```bash
   scp -i your-key.pem -r cloudbox_friend/ ubuntu@YOUR_EC2_IP:/tmp/cloudbox_update/
   ssh -i your-key.pem ubuntu@YOUR_EC2_IP
   sudo cp -r /tmp/cloudbox_update/* /opt/cloudbox/
   sudo systemctl restart cloudbox
   ```

2. Create a new AMI: `cloudbox-ami-v2`

3. Update Launch Template to use the new AMI.

4. Do an **Instance Refresh** in the ASG:
   EC2 → Auto Scaling Groups → `cloudbox-asg` → Instance Refresh → Start

---

## Step 15 – RDS Read Replica (Optional)

**Go to:** RDS → your `cloudbox-db` → Actions → Create Read Replica

| Setting | Value |
|---|---|
| DB identifier | `cloudbox-db-replica` |
| Region | us-east-1 |
| Instance | db.t3.micro |

Used for read-heavy queries without touching the primary DB.

---

## Quick Reference – Resource Names

| Resource | Name |
|---|---|
| VPC | `cloudbox-vpc` |
| ALB SG | `cloudbox-alb-sg` |
| EC2 SG | `cloudbox-ec2-sg` |
| RDS SG | `cloudbox-rds-sg` |
| IAM Role | `cloudbox-ec2-role` |
| S3 Bucket | `cloudbox-files-YOURNAME` |
| RDS Instance | `cloudbox-db` |
| DB Name | `cloudbox` |
| DB User | `cloudbox_admin` |
| Table: users | `accounts` |
| Table: files | `uploads` |
| Table: clients | `contacts` |
| Launch Template | `cloudbox-lt` |
| AMI | `cloudbox-ami-v1` |
| ALB | `cloudbox-alb` |
| Target Group | `cloudbox-tg` |
| ASG | `cloudbox-asg` |
| Dashboard | `cloudbox-dashboard` |
| App directory | `/opt/cloudbox/` |
| Service name | `cloudbox` |
| Env vars | `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`, `STORAGE_BUCKET`, `CLOUD_REGION`, `APP_SECRET` |

---

## Useful Commands

```bash
# Check if app is running
sudo systemctl status cloudbox

# View live logs
sudo journalctl -u cloudbox -f

# Restart after changes
sudo systemctl restart cloudbox

# Reload nginx
sudo systemctl restart nginx

# Check nginx config
sudo nginx -t

# Connect to RDS directly from EC2
PGPASSWORD=YourPassword psql -h YOUR_RDS_ENDPOINT -U cloudbox_admin -d cloudbox

# List tables
\dt

# Check uploads
SELECT * FROM uploads ORDER BY uploaded_at DESC LIMIT 5;

# Check accounts
SELECT id, account_name, email, plan FROM accounts;
```
