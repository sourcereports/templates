import boto3
import json
import socket
import dns.resolver
import base64
import time
from boto3.dynamodb.conditions import Key, Attr

class Stack:

    # Initializer / Instance Attributes
    def __init__(self, response):
        self.url = response['Items'][0]['url']
        self.secondurl = response['Items'][0]['secondurl']
        self.hostid = response['Items'][0]['hostid']
        self.rolearn = response['Items'][0]['rolearn']
        self.id = response['Items'][0]['id']
        self.codepipelineid = response['Items'][0]['codepipelineid']
        self.loadbalancerarn = response['Items'][0]['loadbalancerarn']
        self.credentials = AssumeRole(self.rolearn)
        self.dnscount = 0
        self.redirect_bucket = ''
        self.msg = ''
        self.new = ''
        try:
            self.repo = response['Items'][0]['repo']
            self.branch = response['Items'][0]['branch']
        except:
            self.repo = ''
            self.branch = ''


def lambda_handler(event, context):
    id= ''
    try:
        myvar = json.loads(event['body'])
        id = myvar['uid']
    except:
        print('not apigateway')

    try:
        id = event['Records'][0]['body']
    except:
        print('not sqs')

    print(event)

    response = getRecord(id)
    my_stack = Stack(response)
    getLiveNS(my_stack)
    pipelineInfo(my_stack)
    getPipelineNS(my_stack)

    if my_stack.live_NS != my_stack.pipeline_NS:
        my_stack.msg = "Nameservers do not match"

    if my_stack.redirect_bucket != '':
        verifyBucketRedirect(my_stack)

    if my_stack.dnscount != 2:
        my_stack.msg = "Missing 1 or more dns validation. Both A records set?"

    codedeployInfo(my_stack)
    getLBinfo(my_stack)

    if my_stack.deploymentInstances != my_stack.live_targets:
        my_stack.msg ="Instances not identical"


    getASGinfo(my_stack)

    if my_stack.msg is '':
        my_stack.msg = 'pass'

    updateLastChecked(my_stack)

    print('msg:'+my_stack.msg)
    print('repo:'+my_stack.repo)
    print('id:'+my_stack.id)

    return {
        'statusCode': 200,
        'headers': {
            "Access-Control-Allow-Headers": "Access-Control-Allow-Headers, Origin,Accept, X-Requested-With, Content-Type, Access-Control-Request-Method, Access-Control-Request-Headers",
            "Access-Control-Allow-Methods": "GET,HEAD,OPTIONS,POST,PUT",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": "true"
        },
        'body': json.dumps({"msg":my_stack.msg, "repo":my_stack.repo, "uid":my_stack.id})
    }

def getRecord(id):
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('sourceshare')
    response = table.query(
      KeyConditionExpression=Key('id').eq(id)
    )
    return response


def AssumeRole(rolearn):
    sts_connection = boto3.client('sts')
    acct_b = sts_connection.assume_role(
        RoleArn=rolearn,
        RoleSessionName="cross_acct_lambda"
    )
    credentials = {
        'ACCESS_KEY': acct_b['Credentials']['AccessKeyId'],
        'SECRET_KEY': acct_b['Credentials']['SecretAccessKey'],
        'SESSION_TOKEN' : acct_b['Credentials']['SessionToken']
    }
    return credentials

def getLiveNS(my_stack):
    live_ns = []
    nameservers = dns.resolver.query(my_stack.url,'NS')
    for nameserver in nameservers:
        live_ns.append(str(nameserver))
    my_stack.live_NS = set(live_ns)

def getPipelineNS(my_stack):
    client = boto3.client('route53',
        aws_access_key_id=my_stack.credentials['ACCESS_KEY'],
        aws_secret_access_key=my_stack.credentials['SECRET_KEY'],
        aws_session_token=my_stack.credentials['SESSION_TOKEN']
    )

    response = client.list_resource_record_sets(HostedZoneId=my_stack.hostid)
    print(response)
    records = response['ResourceRecordSets']
    pipeline_NS = []
    pipeline_A = []
    for record in records:
        if record['Type'] == 'NS':
            for entry in record['ResourceRecords']:
                pipeline_NS.append(entry['Value'])
        elif record['Type'] == 'A':
            print(record['Name'])
            print(my_stack.url)
            if record['Name'] == my_stack.url + '.':
                print('match!')

                pipeline_A.append(record['AliasTarget']['DNSName'])
                my_stack.dnscount = my_stack.dnscount + 1
            if record['Name'] == my_stack.secondurl + '.':
                my_stack.dnscount = my_stack.dnscount + 1

           # pipeline_A.append({'Name':record['Name'],'Alias':record['AliasTarget']['DNSName']})
            print('A record')
            print(record)


    my_stack.pipeline_NS = set(pipeline_NS)
    my_stack.pipeline_A = pipeline_A


def pipelineInfo(my_stack):
    client = boto3.client('codepipeline',
        aws_access_key_id=my_stack.credentials['ACCESS_KEY'],
        aws_secret_access_key=my_stack.credentials['SECRET_KEY'],
        aws_session_token=my_stack.credentials['SESSION_TOKEN']
    )
    response = client.get_pipeline(
        name=my_stack.codepipelineid
    )
    for stage in response['pipeline']['stages']:
        print(stage)
        if stage['name'] == 'Source':
            for action in stage['actions']:
                print(action)
                my_stack.source = action['actionTypeId']['provider']
                if my_stack.source == 'GitHub':
                    if my_stack.repo == '' or my_stack.branch =='':
                        my_stack.repo=action['configuration']['Owner'] + '/' + action['configuration']['Repo']
                        my_stack.branch= action['configuration']['Branch']
                        my_stack.new = 1
                    else:
                        if my_stack.repo != action['configuration']['Owner'] + '/' + action['configuration']['Repo']:
                            my_stack.msg = 'repo does not match!'
                        elif my_stack.branch != action['configuration']['Branch']:
                            print('b1:' + my_stack.branch)
                            print('b2:' + action['configuration']['Branch'])
                            my_stack.msg = 'branch does not match!'

        if stage['name'] == 'Deploy':
            for action in stage['actions']:
                print(action)
                if action['actionTypeId']['provider'] == 'CodeDeploy':
                    my_stack.codedeployApp = action['configuration']['ApplicationName']
                    my_stack.deploymentgroupName = action['configuration']['DeploymentGroupName']
                    print (my_stack.deploymentgroupName)

def codedeployInfo(my_stack):
    client = boto3.client('codedeploy',
        aws_access_key_id=my_stack.credentials['ACCESS_KEY'],
        aws_secret_access_key=my_stack.credentials['SECRET_KEY'],
        aws_session_token=my_stack.credentials['SESSION_TOKEN']
    )
    response = client.get_deployment_group(
        applicationName=my_stack.codedeployApp,
        deploymentGroupName=my_stack.deploymentgroupName
    )
    deploymentid = response['deploymentGroupInfo']['lastSuccessfulDeployment']['deploymentId']
    response = client.list_deployment_instances(
        deploymentId=deploymentid
    )
    instanceids = response['instancesList']
    response = client.batch_get_deployment_instances(
        deploymentId=deploymentid,
        instanceIds=instanceids
    )
    #save in case I need ec2 ARNs
    my_stack.deploymentInstances = set(instanceids)

def getLBinfo(my_stack):
    client = boto3.client('elbv2',
        aws_access_key_id=my_stack.credentials['ACCESS_KEY'],
        aws_secret_access_key=my_stack.credentials['SECRET_KEY'],
        aws_session_token=my_stack.credentials['SESSION_TOKEN']
    )
    response = client.describe_listeners(
        LoadBalancerArn = my_stack.loadbalancerarn
    )
    print('LB info')

    for listener in response['Listeners']:
        if listener['Port'] == 80:
            config = listener['DefaultActions'][0]['RedirectConfig']
            if config['Port'] == '443'  \
            and config['Host'] == my_stack.url \
            and config['Path'] == '/#{path}' \
            and config['Query'] == '#{query}':
                pass
            else:
                my_stack.msg = "invalid path"
        elif listener['Port'] == 443:
            print (listener['DefaultActions'])
            if listener['DefaultActions'][0]['Type'] == 'forward':
                my_stack.target_group = listener['DefaultActions'][0]['TargetGroupArn']
            else:

                pass
                my_stack.msg = "invalid 443 listener; forward to target group"
        else:
            my_stack.msg = "invalid port on listener"
            #return '{"msg":"invalid port on listener"}'

    response = client.describe_target_health(
        TargetGroupArn = my_stack.target_group
    )
    targets = []
    for target in response['TargetHealthDescriptions']:
        targets.append(target['Target']['Id'])

    my_stack.live_targets = set(targets)

    response = client.describe_load_balancers(
        LoadBalancerArns=[
            my_stack.loadbalancerarn
        ]
    )
    print('lbinfo')
    print(response)
    print('dualstack.'+ response['LoadBalancers'][0]['DNSName'].lower())
    print(my_stack.pipeline_A)
    if 'dualstack.'+ response['LoadBalancers'][0]['DNSName'].lower()+ '.' not in my_stack.pipeline_A:
        my_stack.msg = 'loadbalancer not detected as deployment target'


def getASGinfo(my_stack):
    client = boto3.client('autoscaling',
        aws_access_key_id=my_stack.credentials['ACCESS_KEY'],
        aws_secret_access_key=my_stack.credentials['SECRET_KEY'],
        aws_session_token=my_stack.credentials['SESSION_TOKEN']
    )
    response = client.describe_auto_scaling_instances(
        InstanceIds= list(my_stack.deploymentInstances)
    )
    asg = []
    launchconfig = []
    for instance in response['AutoScalingInstances']:
        asg.append(instance['AutoScalingGroupName'])
        launchconfig.append(instance['LaunchConfigurationName'])
    if (len(set(asg))!=1):
        my_stack.msg = "you cannot use 2 ASGs!"
    my_stack.ASG = asg[0]
    my_stack.launchconfig = launchconfig[0]

    response = client.describe_launch_configurations(
        LaunchConfigurationNames= [my_stack.launchconfig]
    )

    userdata = base64.b64decode(response['LaunchConfigurations'][0]['UserData'])
    ami = response['LaunchConfigurations'][0]['ImageId']
    keyname = response['LaunchConfigurations'][0]['KeyName']
    ami_list = ['ami-02913db388613c3e1', 'ami-0e1e385b0a934254a', 'ami-0ab3e16f9c414dee7', 'ami-05c859630889c79c8', 'ami-07cc15c3ba6f8e287', 'ami-04070f04f450607dc', 'ami-010fae13a16763bb4', 'ami-028188d9b49b32a80', 'ami-04de2b60dd25fbb2e', 'ami-0e2c2c29d8017dd99', 'ami-035b3c7efe6d061d5', 'ami-02f706d959cedf892', 'ami-0bce08e823ed38bdd', 'ami-03920bf5f903e90d4']

    if userdata == b'\n#!/bin/bash -x\n\nsudo yum update\nsudo yum install ruby -y\nsudo yum install wget -y\ncd /home/ec2-user\nwget https://aws-codedeploy-us-east-1.s3.us-east-1.amazonaws.com/latest/install\nsudo chmod +x ./install\nsudo ./install auto\n' \
    and keyname == ''\
    and ami in ami_list:
        my_stack.lcinfo = {'ami':ami,'keyname':keyname,'userdata':userdata}
    else:
        my_stack.msg = "invalid ami, userdata, or use of pem key!"

def updateLastChecked(my_stack):
    client = boto3.client('dynamodb')
    print(my_stack.id)
    response = client.update_item(
                    TableName = 'sourceshare',
                    Key = {'id':{'S':my_stack.id},'type':{'S':'stack'}},
                    UpdateExpression='SET lastchecked = :val1, pass = :val2',
                    ExpressionAttributeValues={
                        ':val1': {'N':str(time.time())},
                        ':val2': {'S':my_stack.msg}
                    }
                )
    if my_stack.new is 1:
        response = client.update_item(
                    TableName = 'sourceshare',
                    Key = {'id':{'S':my_stack.id},'type':{'S':'stack'}},
                    UpdateExpression='SET branch = :val1, repo = :val2, #source = :val3',
                    ExpressionAttributeValues={
                        ':val1': {'S':my_stack.branch},
                        ':val2': {'S':my_stack.repo},
                        ':val3': {'S':my_stack.source}
                    },
                    ExpressionAttributeNames={"#source": "source"}
                )
        print('new repo added')
    print (response)

def verifyBucketRedirect(my_stack):
    print(my_stack.redirect_bucket)
    bucketname = my_stack.redirect_bucket
    bucketname = bucketname.split('.s3-website')[0]
    print(bucketname)

    client = boto3.client('s3',
        aws_access_key_id=my_stack.credentials['ACCESS_KEY'],
        aws_secret_access_key=my_stack.credentials['SECRET_KEY'],
        aws_session_token=my_stack.credentials['SESSION_TOKEN']
    )
    response = client.get_bucket_website(
        Bucket=bucketname
    )
    print ('bucket info')
    print (response)
    if response['RedirectAllRequestsTo']['HostName'] != my_stack.url:
        my_stack.msg = 'Second url is not redirected to primary url'
