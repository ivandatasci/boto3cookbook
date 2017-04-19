#!/usr/bin/python3
# Ivan Gregoretti, PhD. March 2017.

import subprocess
import boto3
import json
import jmespath
import datetime # Usage: execute datetime.datetime.now(datetime.timezone.utc); then instead of tzinfo=tzutc() use tzinfo=datetime.timezone.utc.
import pandas as pd

pd.set_option('display.width', 270)


################################################################################
# Create session and identify relevant VPC and subnet
################################################################################

# Create custom session
se1 = boto3.Session( profile_name='default' )    # profile: default
#se2= boto3.Session( profile_name='ivan'    )    # profile: ivan


# Create Identity and Access Managemet resource and client
iamre = se1.resource('iam')
iamcl = se1.client(  'iam')

# Identify my user name
iam_user_name = jmespath.search('Users[*] | [?UserName!=`null`] | [?contains(UserName, `Gregoretti`) || contains(UserName, `gregoretti`)].UserName | [0]', iamcl.list_users())

# Create an EC2 resource and/or client
ec2re = se1.resource('ec2')
ec2cl = se1.client(  'ec2')


# Creating an EFS requires identification of the VPC and its subnets.
# The VPC is required to create the Security Groups.
# The subnets are required to define the mount targets.

# Identify a relevant VPC in which to work
# Note: The idea is to first and quickly avoid the default VPC and then search for a good VPC by tags
my_vpcid = jmespath.search(
        'Vpcs[?!( IsDefault )] | [?Tags[?Key==`Name` && Value==`CSTSANDBOXVPC`]].VpcId',
        ec2cl.describe_vpcs()
        )[0]

# Note: Construct a dataframe with relevant subnets organised by availability zone (rows) and exposure (columns)
my_subnetid_df = pd.DataFrame({'Public':['', ''], 'Private':['', '']}, index=['us-east-1a', 'us-east-1e'])
my_subnetid_df.loc['us-east-1a','Public' ] = jmespath.search('Subnets[?VpcId==`' + my_vpcid + '`] | [?Tags[?Key==`Name` && Value==`Public1A subnet` ]].SubnetId | [0]', ec2cl.describe_subnets())
my_subnetid_df.loc['us-east-1a','Private'] = jmespath.search('Subnets[?VpcId==`' + my_vpcid + '`] | [?Tags[?Key==`Name` && Value==`Private1A subnet`]].SubnetId | [0]', ec2cl.describe_subnets())
my_subnetid_df.loc['us-east-1e','Public' ] = jmespath.search('Subnets[?VpcId==`' + my_vpcid + '`] | [?Tags[?Key==`Name` && Value==`Public1E subnet` ]].SubnetId | [0]', ec2cl.describe_subnets())
my_subnetid_df.loc['us-east-1e','Private'] = jmespath.search('Subnets[?VpcId==`' + my_vpcid + '`] | [?Tags[?Key==`Name` && Value==`Private1E subnet`]].SubnetId | [0]', ec2cl.describe_subnets())
# For example:
#                     Private           Public
# us-east-1a  subnet-d00ed699  subnet-d30ed69a
# us-east-1e  subnet-9701ecab  subnet-2e01ec12
#
# Elements can be selected by index, like this:
# my_subnetid_df.loc['us-east-1a','Public']



################################################################################
# Identify or create security groups
################################################################################

# Identify my own IP address
# Note: This runs as a OS process and it is used to figure out what local public IP internet services can see.
my_ip_child = subprocess.run(['curl', '--silent', 'http://checkip.amazonaws.com'], stdout=subprocess.PIPE)
my_ip       = my_ip_child.stdout.decode('utf-8').rstrip()


# Note: The logic below will either identify or create two security groups
# 1) Security group for the EC2 instance
#        my_security_group_name
#        my_security_group_id
# 2) Security group for the EFS mount target
#        my_security_group_efs_name
#        my_security_group_efs_id


########################################
# 1) Security group for the EC2 instance
########################################

# Determine whether the compbio-research-00-sg security group exists
my_security_group_name = 'compbio-research-00-sg'

if my_security_group_name in jmespath.search('SecurityGroups[*].GroupName', ec2cl.describe_security_groups()):

    print('Security group ' + my_security_group_name + ' already exists.')

    # get the security group id (string)
    my_security_group_id = jmespath.search('SecurityGroups[?GroupName==`' + my_security_group_name + '`].GroupId',
            ec2cl.describe_security_groups(Filters=[{'Name':'vpc-id', 'Values':[my_vpcid] }])
            )[0]

    # get the security group (resource object)
    my_security_group = ec2re.SecurityGroup( my_security_group_id   )

else:

    print('Security group ' + my_security_group_name + ' does not exist. Creating it...')

    # Create a security group
    my_security_group = ec2re.create_security_group(GroupName=my_security_group_name, Description='Allows access to Computational Biology Research', VpcId=my_vpcid)
    # Add a tag
    my_security_group.create_tags(Tags=[{'Key': 'Name', 'Value': my_security_group_name + '-name'}, {'Key':'Owner', 'Value':iam_user_name}, {'Key': 'Department', 'Value': 'Computational Biology Research'}])
    # Set security group attributes
    my_security_group.authorize_ingress(IpPermissions=[{'IpProtocol':'tcp', 'FromPort':22, 'ToPort':22, 'IpRanges':[{'CidrIp':'10.10.6.0/24'},{'CidrIp': my_ip + '/32'}]}])

    print('Security group ' + my_security_group.group_name + ' has now been created.')


########################################
# 2) Security group for the EFS mount target
########################################

# Determine whether the compbio-research-efs -00-sg security group exists
my_security_group_efs_name = 'compbio-research-efs-00-sg'

if my_security_group_efs_name in jmespath.search('SecurityGroups[*].GroupName', ec2cl.describe_security_groups()):

    print('Security group ' + my_security_group_efs_name + ' already exists.')

    # get the security group id (string)
    my_security_group_efs_id = jmespath.search('SecurityGroups[?GroupName==`' + my_security_group_efs_name + '`].GroupId',
            ec2cl.describe_security_groups(Filters=[{'Name':'vpc-id', 'Values':[my_vpcid] }])
            )[0]

    # get the security group (resource object)
    my_security_group_efs = ec2re.SecurityGroup( my_security_group_efs_id   )

else:

    print('Security group ' + my_security_group_efs_name + ' does not exist. Creating it...')

    # Create a security group
    my_security_group_efs = ec2re.create_security_group(GroupName=my_security_group_efs_name, Description='Allows access to Computational Biology Research EFS', VpcId=my_vpcid)
    # Add a tag
    my_security_group_efs.create_tags(Tags=[{'Key': 'Name', 'Value': my_security_group_efs_name + '-name'}, {'Key':'Owner', 'Value':iam_user_name}, {'Key': 'Department', 'Value': 'Computational Biology Research'}])
    # Set security group attributes
    my_security_group_efs.authorize_ingress(IpPermissions=[
        {
            'IpProtocol':'tcp',
            'FromPort':2049,
            'ToPort':2049,
            'UserIdGroupPairs':[
                {
                    'UserId':'af8bea628cb1eda67ee4016e51034c7272cdf7c062a62107157648f175214a25',
                    'GroupId':my_security_group_id,
                    'VpcId':my_vpcid
                }
            ]
        },
        {
            'IpProtocol':'tcp',
            'FromPort':2049,
            'ToPort':2049,
            'IpRanges':[
                {
                    'CidrIp':'10.10.6.0/24'
                },
                {
                    'CidrIp': my_ip + '/32'
                }
            ]
        }
        ]
    )

    print('Security group ' + my_security_group_efs.group_name + ' has now been created.')


# Display security groups if desired
jmespath.search('SecurityGroups[*].[GroupId,GroupName]', ec2cl.describe_security_groups(Filters=[{'Name':'vpc-id', 'Values':[my_vpcid] }]))


# If desired, delete the security groups
#ec2cl.delete_security_group(GroupId=my_security_group.id    )
#ec2cl.delete_security_group(GroupId=my_security_group_efs.id)



################################################################################
# Create EFS
################################################################################

# Create an EFS client.
# Note: there is only a Client interface with AWS, no Resources interface at the
# time of this writing.
efscl = se1.client('efs')

# Define EFS name and CreationToken strings
my_efs_name = 'compbio-research-00-efs'
my_efs_creation_token = my_efs_name + '-token'

try:
    my_efs_id = efscl.describe_file_systems(CreationToken=my_efs_creation_token)['FileSystems'][0]['FileSystemId']

except:

    efscl.create_file_system(CreationToken=my_efs_creation_token, PerformanceMode='generalPurpose')
    my_efs_id = efscl.describe_file_systems(CreationToken=my_efs_creation_token)['FileSystems'][0]['FileSystemId']
    # Tag the newly created EFS
    efscl.create_tags(FileSystemId=my_efs_id, Tags=[{'Key':'Name', 'Value':my_efs_name},
                                                    {'Key':'Owner', 'Value':iam_user_name},
                                                    {'Key':'Department', 'Value':'Computational Biology Research'}])


# Now that the file system exists, create a mount target in each availability
# zone. Only one mount target can be created per availability zone.
#efscl.create_mount_target(FileSystemId=my_efs_id, SubnetId=my_subnetid_df.loc['us-east-1a','Public' ], SecurityGroups=[ my_security_group_efs.id ])
efscl.create_mount_target(FileSystemId=my_efs_id, SubnetId=my_subnetid_df.loc['us-east-1a','Private'], SecurityGroups=[ my_security_group_efs.id ])
#efscl.create_mount_target(FileSystemId=my_efs_id, SubnetId=my_subnetid_df.loc['us-east-1e','Public' ], SecurityGroups=[ my_security_group_efs.id ])
efscl.create_mount_target(FileSystemId=my_efs_id, SubnetId=my_subnetid_df.loc['us-east-1e','Private'], SecurityGroups=[ my_security_group_efs.id ])



################################################################################
# Done. Now just display the mount targets.
################################################################################

# Display the IPv4 of the mount targets
[m['IpAddress'] for m in efscl.describe_mount_targets(FileSystemId=my_efs_id)['MountTargets']]

# Merge AvailabilityZone and IPv4 address into a single DataFrame for each mount
# target involved in this EFS.
my_azip_df = pd.merge(pd.DataFrame(efscl.describe_mount_targets(FileSystemId=my_efs_id)['MountTargets']), pd.DataFrame(ec2cl.describe_subnets()['Subnets']), left_on=None)[['AvailabilityZone','IpAddress']]

# Construct the DNS server names and place them in a convenient DataFrame
my_efsservers_df = pd.DataFrame({'ip':my_azip_df['IpAddress'].tolist(), 'dns_name':['', '']}, index=my_azip_df['AvailabilityZone'].tolist())
my_efsservers_df['dns_name'] = [row[1] + '.' + my_efs_id + '.efs.' + row[1][:-1] + '.amazonaws.com' for row in my_azip_df.itertuples()]
# Usage examples:
# my_efsservers_df.loc['us-east-1a','dns_name']
# 'us-east-1a.fs-ae4efde7.efs.us-east-1.amazonaws.com'
# my_efsservers_df.loc['us-east-1a','ip']
# '10.50.251.144'



################################################################################
# Mounting
################################################################################

# sudo mkdir /mnt/e0
# sudo chmod 777 /mnt/e0

# Mounting manually
# sudo mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2 us-east-1a.fs-ae4efde7.efs.us-east-1.amazonaws.com:/ /mnt/e0
# or
# sudo mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2 fs-ae4efde7.efs.us-east-1.amazonaws.com:/ /mnt/e0
# or
# sudo mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2 10.50.250.168:/ /mnt/e0

# Mounting automatically at boot time
# Edit /etc/fstab and add at the end:
# us-east-1a.fs-ae4efde7.efs.us-east-1.amazonaws.com:/ /mnt/e0 nfs4 rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2 0 0
# or simply
# fs-ae4efde7.efs.us-east-1.amazonaws.com:/ /mnt/e0 nfs4 rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2 0 0



