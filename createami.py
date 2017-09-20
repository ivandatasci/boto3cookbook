#!/usr/bin/python3
# Ivan Gregoretti, PhD. April 2017.

import subprocess
import boto3
import json
import jmespath
import datetime # Usage: execute datetime.datetime.now(datetime.timezone.utc); then instead of tzinfo=tzutc() use tzinfo=datetime.timezone.utc.
import pandas as pd

pd.set_option("display.width", None)


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
s3cl = se1.client(  's3')




################################################################################
# Identify or create security groups
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
    my_security_group.create_tags(Tags=[{'Key': 'Name', 'Value': my_security_group_name}, {'Key':'Owner', 'Value':iam_user_name}, {'Key': 'Department', 'Value': 'Computational Biology Research'}])
    # Set security group attributes
    my_security_group.authorize_ingress(IpPermissions=[{'IpProtocol':'tcp', 'FromPort':22, 'ToPort':22, 'IpRanges':[{'CidrIp':'10.10.6.0/24'},{'CidrIp':'10.100.100.0/24'},{'CidrIp': my_ip + '/32'}]}])

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
# Complete upgrade cycle: running, stopping, snapshoting, imaging, launching
################################################################################

# Steps
# running formosa-01
# creation of snapshot formosa-01-snap and creation of its image formosa-01
# launching formosa-02 (from image formosa-01)

my_ec2instance.stop()
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 25 for Computational Biology' )
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-01',
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
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 25'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])


jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
my_ec2instance.terminate()
my_ec2image.wait_until_exists()
my_keypair = ec2re.KeyPair('kp-compbio0')
my_ec2instance = ec2re.create_instances(ImageId=my_ec2image.id,
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='m4.large',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':96, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-02'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.reload()
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))



####################
# Clean up
####################

# Identify images (and their source snapshots) in my account
pd.DataFrame(  jmespath.search('Images[*][ImageId, CreationDate, Name, BlockDeviceMappings[][Ebs][].SnapshotId, BlockDeviceMappings[][Ebs][].VolumeSize, Tags[?Key==`Name`].Value,Description]', ec2cl.describe_images(Filters=[{'Name':'owner-id', 'Values':['406215614988']}]))  )
#                0                         1                                   2                         3      4                            5                                                  6
# 0   ami-08fc331e  2017-02-13T20:32:28.000Z                 Boomi Molecule Node  [snap-09f06db5aaf1cba6b]    [8]  [Boomi Molecule Node Image]  Image for Boomi Molecule node with EFS and upd...
# 1   ami-0e0b1f19  2016-12-21T12:10:47.000Z                 CST_OEL_6.7_GOLDAMI  [snap-0da5e3e6d4d932346]  [100]        [CST_OEL_6.7_GOLDAMI]                                CST_OEL_6.7_GOLDAMI
# 2   ami-1c70f60a  2017-04-03T20:02:34.000Z                       SCPD-CORE-TMP           [snap-f812b766]  [100]                         None                          temp image to debug mount
# 3   ami-3dcf382b  2017-01-23T17:16:19.000Z    Oracle_AA_10.50.251.44_23JAN2017  [snap-0ac102177bc4e6795]  [100]                         None                   Oracle_AA_10.50.251.44_23JAN2017
# 4   ami-52e47144  2017-04-13T19:17:29.000Z                          formosa-00  [snap-0772a2dbbeb46d566]   [96]                 [formosa-00]                Fedora 25 for Computational Biology
# 5   ami-5ca7334a  2017-04-14T19:46:44.000Z                          formosa-01  [snap-0321e8cd56c0aa5c3]   [96]                 [formosa-01]                Fedora 25 for Computational Biology
# 6   ami-800cba96  2017-03-21T18:18:54.000Z                           SCPD-CORE           [snap-048e118d]  [100]                         None                                                   
# 7   ami-81e77297  2017-04-13T19:47:55.000Z  CameronLamdaDevEc2WithOracleClient           [snap-6ee5b395]    [8]                         None  Cameron's lambda development ec2.  includes Or...
# 8   ami-95f04183  2017-03-21T19:03:21.000Z                        SCPD-CORE-v2           [snap-cc3bbe44]  [100]                         None                                                   
# 9   ami-e09240f6  2017-02-24T18:46:54.000Z                     SCPD-JIRA-IMAGE           [snap-eb5d37f7]  [100]                         None                                         test image
# 10  ami-f0cd66e6  2017-03-16T18:38:36.000Z                   SCPD-CORE-CENTOS7  [snap-03e0576d045292c46]  [100]                         None                                                   

# Deregister deprecated image and delete its source snapshot
# ec2cl.deregister_image(ImageId='ami-52e47144')
# ec2cl.delete_snapshot(SnapshotId='snap-0772a2dbbeb46d566')


# Another cycle. Creation of snapshot and image of formosa-02 and new instance formosa-03
my_ec2instance.stop()
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 25 for Computational Biology' )
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-02',
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
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 25'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])


jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
my_ec2instance.terminate()
my_ec2image.wait_until_exists()
my_keypair = ec2re.KeyPair('kp-compbio0')
my_ec2instance = ec2re.create_instances(ImageId=my_ec2image.id,
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='m4.large',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':96, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-03'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.reload()
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))


# Another cycle. Creation of snapshot and image of formosa-03 and new instance formosa-04
my_ec2instance.stop()
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 25 for Computational Biology' )
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-03',
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
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 25'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])


jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
my_ec2instance.terminate()
my_ec2image.wait_until_exists()
my_keypair = ec2re.KeyPair('kp-compbio0')
my_ec2instance = ec2re.create_instances(ImageId=my_ec2image.id,
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='m4.large',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':96, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-04'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.reload()
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))


# Another cycle. Creation of snapshot and image of formosa-04 and new instance formosa-05
# Note: relaunching with m4.xlarge
my_ec2instance.stop()
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 25 for Computational Biology' )
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-04',
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
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 25'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
my_ec2instance.terminate()
my_ec2image.wait_until_exists()
my_keypair = ec2re.KeyPair('kp-compbio0')
my_ec2instance = ec2re.create_instances(ImageId=my_ec2image.id,
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='m4.xlarge',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':96, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-05'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.reload()
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))


# Another cycle. Creation of snapshot and image of formosa-05 and new instance formosa-06
my_ec2instance.stop()
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 25 for Computational Biology' )
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-05',
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
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 25'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
my_ec2instance.terminate()
my_ec2image.wait_until_exists()
my_keypair = ec2re.KeyPair('kp-compbio0')
my_ec2instance = ec2re.create_instances(ImageId=my_ec2image.id,
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='m4.xlarge',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':96, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-06'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.reload()
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))


# Last cycle for this release of Fedora. Creation of snapshot of formosa-06
my_ec2instance.stop()
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 25 for Computational Biology' )
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-06',
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
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 25'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
#my_ec2instance.terminate()


################################################################################
# Create an EC2 instance based on a modern linux distribution (Fedora 26)
################################################################################

# Launch an instance
# Note: Instance types m4.large and m2.xlarge are a good starting point for
# computational biology.
# Important: include UserData to execute dnf update -y
my_user_data = """#!/bin/bash
sudo dnf update -y
sudo dnf install htop nano -y
"""

my_ec2instance = ec2re.create_instances(ImageId='ami-1f595c09',
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        UserData=my_user_data,
        InstanceType='m4.xlarge',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':60, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]

# Tag immediately my instance
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-07'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

# Tag immediately its attached volume
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2instance.reload()
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))


# Creation of snapshot of formosa-07
my_ec2instance.stop()
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 26 for Computational Biology' )
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-07',
    Description='Fedora 26 for Computational Biology',
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
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 26'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
my_ec2instance.terminate()
my_ec2image.wait_until_exists()
my_keypair = ec2re.KeyPair('kp-compbio0')
my_ec2instance = ec2re.create_instances(ImageId='ami-aab88dd1',
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='m4.xlarge',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':60, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-08'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.reload()
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))


# Another cycle. Creation of snapshot and image of formosa-08 and new instance formosa-09
my_ec2instance.stop()
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 26 for Computational Biology' )
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-08',
    Description='Fedora 26 for Computational Biology',
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
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 26'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
my_ec2instance.terminate()
my_ec2image.wait_until_exists()
my_keypair = ec2re.KeyPair('kp-compbio0')
my_ec2instance = ec2re.create_instances(ImageId=my_ec2image.id,
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='m4.xlarge',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':60, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-09'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.reload()
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))

# Another cycle. Creation of snapshot and image of formosa-09 and new instance formosa-10
my_ec2instance.stop()
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 26 for Computational Biology' )
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-09',
    Description='Fedora 26 for Computational Biology',
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
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 26'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
my_ec2instance.terminate()
my_ec2image.wait_until_exists()
my_keypair = ec2re.KeyPair('kp-compbio0')
my_ec2instance = ec2re.create_instances(ImageId=my_ec2image.id,
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='r4.xlarge',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':60, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-10'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.reload()
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))

# Another cycle. Creation of snapshot and image of formosa-10 and new instance formosa-11
my_ec2instance.stop()
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 26 for Computational Biology' )
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-10',
    Description='Fedora 26 for Computational Biology',
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
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 26'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
my_ec2instance.terminate()
my_ec2image.wait_until_exists()
my_keypair = ec2re.KeyPair('kp-compbio0')
my_ec2instance = ec2re.create_instances(ImageId=my_ec2image.id,
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='r4.xlarge',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':60, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-11'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.reload()
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))

# Another cycle. Creation of snapshot and image of formosa-11 and new instance formosa-12
my_ec2instance.stop()
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_stopped()
my_ec2snapshot = ec2re.create_snapshot( VolumeId=my_ec2volume_id, Description='Root device snapshot of Fedora 26 for Computational Biology' )
my_ec2snapshot.create_tags(Tags=[{'Key':'Name', 'Value':jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-snap'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

my_ec2snapshot.wait_until_completed()
my_ec2image = ec2re.register_image(
    Name='formosa-11',
    Description='Fedora 26 for Computational Biology',
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
my_ec2image.create_tags(Tags=[{'Key':'Name', 'Value':my_ec2image.name},{'Key':'Platform', 'Value':'Fedora 26'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

jmespath.search('Images[*] | [?!( Public )] | [?Tags[?Key==`Department` && Value==`Computational Biology Research`]]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))
my_ec2instance.terminate()
my_ec2image.wait_until_exists()
my_keypair = ec2re.KeyPair('kp-compbio0')
my_ec2instance = ec2re.create_instances(ImageId=my_ec2image.id,
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='r4.xlarge',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':60, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-12'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.reload()
jmespath.search('InstanceStatuses[*].[SystemStatus.Status,InstanceStatus.Status] | []', ec2cl.describe_instance_status(InstanceIds=[my_ec2instance.id]))

# Re-launch formosa-12 (from formosa-11's AMI) but use a larger machine type r4.2xlarge
my_keypair = ec2re.KeyPair('kp-compbio0')
my_ec2instance = ec2re.create_instances(ImageId='ami-8e866bf4',
        MinCount=1, MaxCount=1,
        KeyName=my_keypair.name,
        InstanceType='r4.2xlarge',
        BlockDeviceMappings=[{'DeviceName':'/dev/sda1', 'Ebs':{'VolumeSize':60, 'DeleteOnTermination':True, 'VolumeType':'gp2'}}],
        NetworkInterfaces=[{'SubnetId':my_subnetid_df.loc['us-east-1a','Public'], 'Groups':[my_security_group.id], 'DeviceIndex':0, 'AssociatePublicIpAddress':True}],
        InstanceInitiatedShutdownBehavior='terminate'
        )[0]
my_ec2instance.create_tags(Tags=[{'Key':'Name', 'Value':'formosa-12'},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])
my_ec2instance.wait_until_exists(Filters=[{'Name':'block-device-mapping.status','Values':['attached']}])
my_ec2volume_id = my_ec2instance.block_device_mappings[0]['Ebs']['VolumeId']
my_ec2volume_name = jmespath.search('[?Key==`Name`].Value | [0]', my_ec2instance.tags) + '-vol'
ec2re.Volume(  my_ec2volume_id  ).create_tags(Tags=[{'Key':'Name', 'Value':my_ec2volume_name},{'Key':'Owner', 'Value':iam_user_name},{'Key':'Department', 'Value':'Computational Biology Research'}])

### LEFT HERE ###









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

# Identify snapshots by one Tag filtered at the server side and display pretty
pd.DataFrame(  jmespath.search('Snapshots[*][SnapshotId,StartTime,Tags[?Key==`Name`].Value,Description]', ec2cl.describe_snapshots(Filters=[{'Name':'tag:Department', 'Values':['Computational Biology Research']}]))  )

# Identify Images, first client side and then server side
jmespath.search('Images[*] | [?OwnerId==`"406215614988"`] | [?!( Public )]', ec2cl.describe_images())
jmespath.search('Images[*] | [?!( Public )]', ec2cl.describe_images(   Filters=[{'Name':'owner-id', 'Values':['406215614988']}]   ))

# Identify images owned by my account; display pretty
pd.DataFrame(  jmespath.search('Images[*][ImageId, CreationDate, Name, BlockDeviceMappings[][Ebs][].SnapshotId, BlockDeviceMappings[][Ebs][].VolumeSize, Tags[?Key==`Name`].Value, Description]', ec2cl.describe_images(Filters=[{'Name':'owner-id', 'Values':['406215614988']}]))  )


