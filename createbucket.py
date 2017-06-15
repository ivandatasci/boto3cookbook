#!/usr/bin/python3
# Ivan Gregoretti, PhD. April 2017.

import subprocess
import boto3
import json
import jmespath
import datetime # Usage: execute datetime.datetime.now(datetime.timezone.utc); then instead of tzinfo=tzutc() use tzinfo=datetime.timezone.utc.
import pandas as pd



################################################################################
# Create session and identify user (self)
################################################################################

# Create custom session
se1 = boto3.Session( profile_name='default' )    # profile: default
#se2= boto3.Session( profile_name='ivan'    )    # profile: ivan


# Create Identity and Access Managemet resource and client
iamre = se1.resource('iam')
iamcl = se1.client(  'iam')

# Identify my user name
iam_user_name = jmespath.search('Users[*] | [?UserName!=`null`] | [?contains(UserName, `Gregoretti`) || contains(UserName, `gregoretti`)].UserName | [0]', iamcl.list_users())
iam_user_id   = jmespath.search('Users[*] | [?UserName!=`null`] | [?contains(UserName, `Gregoretti`) || contains(UserName, `gregoretti`)].UserId   | [0]', iamcl.list_users())


################################################################################
# Create Resources and Client for interation with S3 and IAM
################################################################################

# Create an S3 resource and/or client
s3re = se1.resource('s3')
s3cl = se1.client(  's3')

# In case it is needed, this is how to display the canonical user ID of this acccount
s3cl.list_buckets()['Owner']


##############################
# Convenience function to avoid the problem of "datetime ... is not JSON serializable".
##############################

def date_handler(obj):
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    else:
        raise TypeError

# Usage: json.dumps(s3cl.list_buckets(), default=date_handler)
# or json.dumps(s3cl.list_buckets()['Buckets'], default=date_handler)
# Note: Pretty print like this: print(json.dumps(s3cl.list_buckets()['Buckets'], default=date_handler, indent=4))



################################################################################
# Create bucket and the perception of directories
################################################################################

# Create a bucket in the S3 resource
my_s3bucket = s3re.create_bucket(ACL='private', Bucket='cst-compbio-research-00-buc') # Bug in the S3 API. Do nto specidy region if us-east-1 is desired.
#my_s3bucket = s3re.create_bucket(ACL='private', Bucket='cst-compbio-research-00-buc', CreateBucketConfiguration={'LocationConstraint': 'us-east-1'})


# Tag immediately
s3re.BucketTagging( bucket_name=my_s3bucket.name ).put( Tagging={'TagSet': [
    {'Key':'Name', 'Value':'cst-compbio-research-00-buc'},
    {'Key':'Owner', 'Value':iam_user_name},
    {'Key':'Department', 'Value':'Computational Biology Research'}
]})


# Create directories
my_s3bucket.put_object(Key='home/')
my_s3bucket.put_object(Key='snapshots/')
my_s3bucket.put_object(Key='scratch/')
my_s3bucket.put_object(Key='tmp/')


# Create subdirectories
my_s3bucket.put_object(Key='home/ivan.gregoretti@cellsignal.com/'        )
my_s3bucket.put_object(Key='home/stephen.brinton@cellsignal.com/'        )
my_s3bucket.put_object(Key='home/sean.landry@cellsignal.com/'            )
my_s3bucket.put_object(Key='home/elizabeth.kolacz@cellsignal.com/'       )
my_s3bucket.put_object(Key='home/yuichi.nishi@cellsignal.com/'           )
my_s3bucket.put_object(Key='home/raphael.rozenfeld@cellsignal.com/'      )
my_s3bucket.put_object(Key='home/florian.gnad@cellsignal.com/'           )


my_s3bucket.put_object(Key='snapshots/ivan.gregoretti@cellsignal.com/'  )
my_s3bucket.put_object(Key='snapshots/stephen.brinton@cellsignal.com/'  )
my_s3bucket.put_object(Key='snapshots/sean.landry@cellsignal.com/'      )
my_s3bucket.put_object(Key='snapshots/elizabeth.kolacz@cellsignal.com/' )
my_s3bucket.put_object(Key='snapshots/yuichi.nishi@cellsignal.com/'     )
my_s3bucket.put_object(Key='snapshots/raphael.rozenfeld@cellsignal.com/')
my_s3bucket.put_object(Key='snapshots/florian.gnad@cellsignal.com/'     )


my_s3bucket.put_object(Key='scratch/ivan.gregoretti@cellsignal.com/'    )
my_s3bucket.put_object(Key='scratch/stephen.brinton@cellsignal.com/'    )
my_s3bucket.put_object(Key='scratch/sean.landry@cellsignal.com/'        )
my_s3bucket.put_object(Key='scratch/elizabeth.kolacz@cellsignal.com/'   )
my_s3bucket.put_object(Key='scratch/yuichi.nishi@cellsignal.com/'       )
my_s3bucket.put_object(Key='scratch/raphael.rozenfeld@cellsignal.com/'  )
my_s3bucket.put_object(Key='scratch/florian.gnad@cellsignal.com/'       )



################################################################################
# Create the bucket's access policy
################################################################################

# Note: S3 actions and examples are documented here:
# http://docs.aws.amazon.com/AmazonS3/latest/dev/using-with-s3-actions.html
# https://aws.amazon.com/blogs/security/writing-iam-policies-grant-access-to-user-specific-folders-in-an-amazon-s3-bucket/
# Note: The "Principal":"*" component has been removed from the statement because
# in IAM policies it is implicitly assumed that the Principal is the user to
# whom the policy is attached.
my_policy_json = json.dumps(
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "1AllowSeeingBucketsList",
            "Effect": "Allow",
            "Action": [ "s3:ListAllMyBuckets", "s3:GetBucketLocation" ],
            "Resource": [ "arn:aws:s3:::*" ]
        },
        {
            "Sid": "2AllowRootLevelListingOfThisBucketAndItsMainDirectories",
            "Effect": "Allow",
            "Action": [ "s3:ListBucket" ],
            "Resource": [ "arn:aws:s3:::cst-compbio-research-00-buc" ],
            "Condition": {
                "StringEquals": {
                    "s3:prefix": [ "", "home/" ],
                    "s3:delimiter": [ "/" ]
                }
            }
        },
        {
            "Sid": "3AllowUserListingOfUsersOwnHomeAndEverybodysSnapshotAndScratchAndTmp",
            "Effect": "Allow",
            "Action": [ "s3:ListBucket" ],
            "Resource": [ "arn:aws:s3:::cst-compbio-research-00-buc" ],
            "Condition": {
                "StringLike": {
                    "s3:prefix": [ "home/${aws:username}/*", "snapshots/*", "scratch/*", "tmp/*" ]
                }
            }
        },
        {
            "Sid": "4AllowGetAndPutAndDelTmp",
            "Effect": "Allow",
            "Action": [ "s3:GetObject", "s3:GetObjectTagging", "s3:PutObject", "s3:PutObjectTagging", "s3:DeleteObject", "s3:DeleteObjectTagging" ],
            "Resource": [ "arn:aws:s3:::cst-compbio-research-00-buc/tmp/*" ]
        },
        {
            "Sid": "5AllowGetSnapshotsAndScratch",
            "Effect": "Allow",
            "Action": [ "s3:GetObject", "s3:GetObjectTagging", "s3:GetObjectVersion", "s3:GetObjectVersionTagging" ],
            "Resource": [ "arn:aws:s3:::cst-compbio-research-00-buc/snapshots/*", "arn:aws:s3:::cst-compbio-research-00-buc/scratch/*" ]
        },
        {
            "Sid": "6AllowEverythingInUsersOwnHomeAndSnapshotsAndScratch",
            "Effect": "Allow",
            "Action": [ "s3:*" ],
            "Resource": [ "arn:aws:s3:::cst-compbio-research-00-buc/home/${aws:username}/*", "arn:aws:s3:::cst-compbio-research-00-buc/snapshots/${aws:username}/*", "arn:aws:s3:::cst-compbio-research-00-buc/scratch/${aws:username}/*" ]
        }
    ]
}
, indent=4)

my_iampolicy = iamre.create_policy(PolicyName='compbio-research-s3-00-pol', PolicyDocument=my_policy_json, Description='Computational Biology Research S3 access control.' )


########################################
# Creating a new version of an existing policy
########################################

# Policy documents are organised and indexed by verion (eg v1, v2, v3, etc).
# One version is considered the default policy version.

# Here it is assumed that a new my_policy_json document has been created.
# Add it as non-default.
my_iampolicy.create_version(PolicyDocument=my_policy_json, SetAsDefault=False)

# Show versions and report whether or not it is the default
for x in my_iampolicy.versions.all(): print(x.version_id, x.is_default_version)


########################################
# Deleting a policy, if needed.
########################################

# When there are multiple versions, all non-default versions of the policy must
# be deleted before the policy in its entirety can be deleted.


####################
# Deleting a policy when there are multiple versions
####################

# Show versions and report whether or not it is the default
for x in my_iampolicy.versions.all(): print(x.version_id, x.is_default_version)

# Display the document of the policy (examples)
#     iamre.PolicyVersion(arn=my_iampolicy.arn, version_id='v1').document
#     iamre.PolicyVersion(arn=my_iampolicy.arn, version_id='v2').document

# Assuming that v2 is not the default version, delete version v2.
#     iamcl.delete_policy_version(PolicyArn=my_iampolicy.arn, VersionId='v2')


####################
# Deleting a policy when there is only one version (the default one)
####################

iamcl.delete_policy(PolicyArn=my_iampolicy.arn)



################################################################################
# Attach Policy to a Group of users
################################################################################

#iamre.Group(name='compbio-research-group-00').attach_policy(PolicyArn=my_iampolicy.arn)
# Note: The command above is not executed at the moment because the members of
# this group already have AmazonS3FullAccess.


### DONE ###



################################################################################
# Appendix 1. Delete a non-empty bucket.
################################################################################

# List content of the bucket
for obj in my_s3bucket.objects.all(): print(obj.key)

# Delete the objects inside the bucket
for obj in my_s3bucket.objects.all(): obj.delete()

# Delete the bucket itself.
my_s3bucket.delete()

# Bonus. This is how to list all objects in all bucket. Warning: big output.
#for bucket in s3re.buckets.all():
#    for obj in bucket.objects.all():
#        print(obj.key)



################################################################################
# Appendix 2. Pretty print JSON documents at the BASH command line.
################################################################################

# Note: the BASH command line is less flexible than ipython3 command line. BASH accepts only double quotes inside the expression.

# Example
# echo '{"Version":"2012-10-17","Statement":[{"Effect":"Deny","Principal":"*","Action":"s3:*","Resource":["arn:aws:s3:::my-bucket-12345","arn:aws:s3:::my-bucket-12345/*"],"Condition":{"StringNotLike":{"aws:userId":["AIDAJ4ICC4DFD5DCGTM5C"]}}}]}'  | python3 -m json.tool

#{
#    "Version": "2012-10-17",
#    "Statement": [
#        {
#            "Effect": "Deny",
#            "Principal": "*",
#            "Action": "s3:*",
#            "Resource": [
#                "arn:aws:s3:::my-bucket-12345",
#                "arn:aws:s3:::my-bucket-12345/*"
#            ],
#            "Condition": {
#                "StringNotLike": {
#                    "aws:userId": [
#                        "AIDAJ4ICC4DFD5DCGTM5C"
#                    ]
#                }
#            }
#        }
#    ]
#}




