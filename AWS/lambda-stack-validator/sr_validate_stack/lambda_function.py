import boto3
import json
import socket
import dns.resolver
import base64
import time
from datetime import datetime
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

class Stack:

    # Initializer / Instance Attributes
    def __init__(self, response):
        print(response)
        self.url = response['url']
        self.secondurl = response['secondurl']
        self.hostid = response['hostid']
        self.rolearn = response['rolearn']
        self.id = response['id']
        self.codepipelineid = response['codepipelineid']
        self.loadbalancerarn = response['loadbalancerarn']
        self.credentials = AssumeRole(self.rolearn)
        self.dnscount = 0
        self.flag = 0
        self.redirect_bucket = ''
        self.msg = ''
        self.new = ''
        try:
            self.repo = response['repo']
            self.branch = response['branch']
        except:
            self.repo = ''
            self.branch = ''

def getRecord(url):
    now = datetime.now()
    timestamp = datetime.timestamp(now)
    timestamp = Decimal(timestamp)

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('sourcereports')

    response = table.scan(
        FilterExpression = Attr('type').eq('stack') & Attr("url").eq(url)
    )
    items = response['Items']
    recent = max(items,key=lambda item:item['timestamp'])
    print (recent)

    return recent


def lambda_handler(event, context):

    myvar = json.loads(event['body'])
    url = myvar['url']
    print('hi')
    print(url)

    response = getRecord(url)
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
        print('msg: "Instances not identical"')
        print(my_stack.deploymentInstances)
        print(my_stack.live_targets)


    getASGinfo(my_stack)
    deploymentVsASG(my_stack)

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
    response = client.get_pipeline_state(
        name=my_stack.codepipelineid
    )
    print(response)
    for pipeline_state in response['stageStates']:
        if pipeline_state['stageName'] == 'Deploy':
            for action_state in pipeline_state['actionStates']:
                if action_state['actionName'] == 'Deploy':
                    if action_state['latestExecution']['status'] == 'Succeeded':
                        my_stack.latest_execution = action_state['latestExecution']['externalExecutionId']
                        print(my_stack.latest_execution)
                    else:
                        my_stack.msg = 'This site is currently undergoing a new deployment, please wait a few minutes.'
    response = client.get_pipeline(
        name=my_stack.codepipelineid
    )
    print(response)
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
                    print ('deploy: '+my_stack.deploymentgroupName)

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
    my_stack.deploymentid = response['deploymentGroupInfo']['lastSuccessfulDeployment']['deploymentId']

    response = client.list_deployment_instances(
        deploymentId=my_stack.deploymentid
    )
    instanceids = response['instancesList']
    my_stack.deploymentInstances = set(instanceids)

def deploymentVsASG(my_stack):


    risky_deployments=[]
    new_deployments=[]
    deployment_info = []
    deployments_data = []
    last_success= 0
    good_deployments = 0
    bad_deployments = 0


    # response = client.list_deployment_instances(
    #     deploymentId=deploymentid
    # )
    # instanceids = response['instancesList']
    client = boto3.client('codedeploy',
        aws_access_key_id=my_stack.credentials['ACCESS_KEY'],
        aws_secret_access_key=my_stack.credentials['SECRET_KEY'],
        aws_session_token=my_stack.credentials['SESSION_TOKEN']
    )

    response = client.list_applications()

    for application in response['applications'] :
        response = client.list_deployment_groups(applicationName = application)
        try:
            response = client.batch_get_deployment_groups(
                applicationName=response['applicationName'],
                deploymentGroupNames=response['deploymentGroups']
            )

            for deploymentgroup in response['deploymentGroupsInfo']:

                print(deploymentgroup)

                #no tag based filter codedeploy actions allowed
                if 'ec2TagSet' in deploymentgroup:
                    if not deploymentgroup['ec2TagSet']['ec2TagSetList']:
                        pass
                    else:
                        my_stack.msg = 'Ec2-tag codedeploy deployments not allowed. Account flagged.'
                        bad_deployments = bad_deployments + 1
                        my_stack.flag = 1

                #no tag based filter codedeploy actions allowed
                elif 'ec2TagFilters' in deploymentgroup:
                    if not deploymentgroup['ec2TagFilters']:
                        pass
                    else:
                        my_stack.msg = 'Ec2-filter codedeploy deployments not allowed. Account flagged.'
                        my_stack.flag=2
                        bad_deployments = bad_deployments + 1

                if 'autoScalingGroups' in deploymentgroup:
                    my_stack.codedeploy_asg = deploymentgroup['autoScalingGroups'][0]['name']
                    my_stack.codedeploy_deployment_group = deploymentgroup['deploymentGroupName']

                    if my_stack.codedeploy_asg == my_stack.ASG:
                        if my_stack.deploymentgroupName == my_stack.codedeploy_deployment_group:
                            if len(deploymentgroup['autoScalingGroups']) > 1:
                                my_stack.msg = 'Only 1 ASG allowed; the one defined in the pipeline'
                            else:
                                if my_stack.deploymentid == my_stack.latest_execution:
                                    good_deployments = good_deployments + 1
                                else:
                                    my_stack.msg = "Your pipeline deployment has been overwritten by a different deployment, so you've been flagged."
                                    my_stack.flag = 3
                        else:
                            #flag for mischief
                            bad_deployments = bad_deployments + 1
                            my_stack.msg = 'You cannot deploy anything except your CodePipeline deployment group to your AutoScalingGroup'
                            my_stack.flag = 4
                    else:
                        pass


                else:
                    pass

        except:
            print('could not locate deployment groups:')
    print('deployments: '+str(good_deployments) +' good '+ str(bad_deployments) + ' bad')
    if good_deployments<1:
        my_stack.msg = "Your pipeline is not working because your pipeline CodeDeploy is not reflecting your AutoScalingGroup's current deployment"


    #save in case I need ec2 ARNs


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
                my_stack.msg = "invalid 443 listener; forward to target group"

        else:
            my_stack.msg = "invalid port on listener"

    response = client.describe_target_health(
        TargetGroupArn = my_stack.target_group
    )
    print("targetInfo:")
    print(response)
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
    if (len(set(launchconfig))!=1):
        my_stack.msg = "you cannot use 2 launchconfig!"

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
    if my_stack.msg is 'pass':
        response = client.update_item(
                    TableName = 'sourcereports',
                    Key = {'id':{'S':my_stack.id},'type':{'S':'stack'}},
                    UpdateExpression='SET lastchecked = :val1, msg = :val2',
                    ExpressionAttributeValues={
                        ':val1': {'N':str(time.time())},
                        ':val2': {'S':my_stack.msg}
                    }
                )
    else:
        response = client.update_item(
                TableName = 'sourcereports',
                Key = {'id':{'S':my_stack.id},'type':{'S':'stack'}},
                UpdateExpression='SET msg = :val1',
                ExpressionAttributeValues={
                    ':val1': {'S':my_stack.msg}
                }
            )
    if my_stack.new is 1:
        response = client.update_item(
                    TableName = 'sourcereports',
                    Key = {'id':{'S':my_stack.id},'type':{'S':'stack'}},
                    UpdateExpression='SET branch = :val1, repo = :val2, #source = :val3',
                    ExpressionAttributeValues={
                        ':val1': {'S':my_stack.branch},
                        ':val2': {'S':my_stack.repo},
                        ':val3': {'S':my_stack.source}
                    },
                    ExpressionAttributeNames={"#source": "source"}
                )
    if my_stack.flag is 1:
        response = client.update_item(
                    TableName = 'sourcereports',
                    Key = {'id':{'S':my_stack.id},'type':{'S':'stack'}},
                    UpdateExpression='SET flag = :val1',
                    ExpressionAttributeValues={
                        ':val1': {'S':str(my_stack.flag)}
                    }
                )
    print (response)


def chunks(l, n):
    for i in range(0, len(l), n):
        yield l[i:i+n]
