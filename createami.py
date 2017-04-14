#!/usr/bin/python3
# Ivan Gregoretti, PhD. April 2017.

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

# Define the name of the key pair
my_keypair = ec2re.KeyPair('kp-compbio0')

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


# Create an S3 resource and/or client
s3re = se1.resource('s3')
s3cl= se1.client(  's3')




################################################################################
# Identify or create security group
################################################################################

# Identify my own IP address
# Note: This runs as a OS process and it is used to figure out what local public IP internet services can see.
my_ip_child = subprocess.run(['curl', '--silent', 'http://checkip.amazonaws.com'], stdout=subprocess.PIPE)
my_ip       = my_ip_child.stdout.decode('utf-8').rstrip()


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
    my_security_group = ec2re.create_security_group(GroupName=my_security_group_name, Description='Allows access to Computational Biology Research Instances', VpcId=my_vpcid)
    # Add a tag
    my_security_group.create_tags(Tags=[{'Key': 'Name', 'Value': my_security_group_name + '-name'}, {'Key':'Owner', 'Value':iam_user_name}, {'Key': 'Department', 'Value': 'Computational Biology Research'}])
    # Set security group attributes
    my_security_group.authorize_ingress(IpPermissions=[{'IpProtocol':'tcp', 'FromPort':22, 'ToPort':22, 'IpRanges':[{'CidrIp':'10.10.6.0/24'},{'CidrIp': my_ip + '/32'}]}])

    print('Security group ' + my_security_group.group_name + ' has now been created.')


# If desired, delete the security group
#ec2cl.delete_security_group(GroupId=my_security_group.id)



################################################################################
# Create an EC2 instance based on a modern linux distribution (Fedora 25)
################################################################################

# Launch an instance
# Note: Instance types m4.large and t2.xlarge are a good starting point for
# computational biology.
# Important: include UserData to execute dnf update -y
my_user_data = """#!/bin/bash
sudo dnf update -y
sudo dnf install htop nano -y
"""

my_ec2instance = ec2re.create_instances(ImageId='ami-56a08841',
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        UserData=my_user_data,
        InstanceType='m4.large',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':96, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]

# Tag immediately my instance
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-00'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

# Tag immediately its attached volume
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

# Inspect the instance that has just been launched and tagged
ec2cl.describe_instances(Filters=[{'Name':'instance-id', 'Values':[my_ec2instance.id]}])

# Refresh object to get the current state (pending, running, stopped, terminated)
my_ec2instance.reload()

# Display status checks 1 and 2
# System status (AWS systems required to use this instance)
# Instance status (checks my software and network configuration)
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))

# Stop but do not yet terminate the template instance
my_ec2instance.wait_until_running()
my_ec2instance.stop()


########################################
# Important comment
# An AMI could now be created from the stopped instance but for the sake of a
# full exercise this protocol will first create a root device snapshot and from
# that snapshot an AMI will be created. See documentation on snapshots to
# understand why this is best practice.
########################################


# Create a snapshot of the stopped template instance
# Note: The argument Description is good practice but not required.
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 25 for Computational Biology' )

# tag the snapshot
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])


# Create a custom image from that root device snapshot
my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-00',
    Description='Fedora 25 for Computational Biology',
    Architecture='x86_64',
    RootDeviceName='/dev/sda1',
    BlockDeviceMappings=[
        {
            'DeviceName': '/dev/sda1',
            'Ebs': {
                'SnapshotId': my_ec2snapshot.id,
                'DeleteOnTermination': True,
                'VolumeType': 'gp2'
            }
        }
    ],
    VirtualizationType='hvm',
)

# Tag image
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 25'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])


# Example of how to find the image id by querying and filtering by known attributes
# Note: both examples result in the same output but the second example is much
# faster because it requests a server side pre-filtering of the matches.
jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
# ImageId 'ami-52e47144'


# Deregister image if needed (delete VM image)
# my_ec2image.deregister()


# terminate the template instance
my_ec2instance.terminate()


# Launch an instance from the newly created custom image
my_ec2image.wait_until_exists()
my_ec2instance = ec2re.create_instances(ImageId=my_ec2image.id,
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='m4.large',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':96, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]

# Tag immediately my instance
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-01'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

# Tag immediately its attached volume
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])


# Refresh object to get the current state (pending, running, stopped, terminated)
my_ec2instance.reload()


# Display status checks 1 and 2
# 1) System status (AWS systems required to use this instance)
# 2) Instance status (checks my software and network configuration)
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))




################################################################################
# Done
################################################################################

# Display IP address of DNS name
my_ec2instance.public_ip_address
my_ec2instance.public_dns_name












################################################################################
# Convenience queries
################################################################################

# Find volumes by size
jmespath.search('Volumes[?Size==`64`]', ec2cl.describe_volumes())

# Identify instances by tag
jmespath.search('Reservations[*].Instances[?Tags[?Key==`Owner` && Value==`' + iam_user_name + '`]] | []', ec2cl.describe_instances())

# Identify instances by tag and state
jmespath.search('Reservations[*].Instances[] | [?Tags[?Key==`Owner` && Value==`' + iam_user_name + '`]] | [?State.Name==`running`] | []', ec2cl.describe_instances())

# Display table of instance IDs, running states and their names
jmespath.search('Reservations[*].Instances[*] | [][InstanceId, State.Name, Tags[?Key==`Owner`].Value]', ec2cl.describe_instances(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))

# Identify a volume attached to my ec2 instance (there could be more than one)
jmespath.search('[].Ebs[].VolumeId | [0]', my_ec2instance.block_device_mappings)

# Identify snapshots by OwnerId, VolumeSize and Tag
jmespath.search('Snapshots[*] | [?OwnerId==`"406215614988"`] | [?VolumeSize==`100`] | [?Tags[?Key==`Name` && Value==`CST_OEL_6.7_GOLDAMI_ROOT_DO NOT DELETE`]]', ec2cl.describe_snapshots())

# Identify Images
jmespath.search('Images[*] | [?OwnerId==`"406215614988"`] | [?!( Public )]', ec2cl.describe_images())


