import json
import boto3
import os

class Resource:
    def __init__(self, event):
        
        self.domain = os.environ['DOMAIN']
        self.httpMethod = os.environ['HTTPMETHOD'] 
        self.roleArn = os.environ['ROLEARN'] 
        self.apiId = ''
        self.methodId = ''
        self.apiPath = ''
        self.lambdaArn = ''
        self.msg = ''
        self.credentials = AssumeRole(self.roleArn)
        

def lambda_handler(event, context):
   
    resource = Resource(event)
    trimProtocol(resource)
    parseDomain(resource)
    getResourceId(resource)
    getIntegration(resource)
    getLambdaCode(resource)
    
    return resource.msg 

def getResourceId(resource):
    client = boto3.client('apigateway',
        aws_access_key_id=resource.credentials['ACCESS_KEY'],
        aws_secret_access_key=resource.credentials['SECRET_KEY'],
        aws_session_token=resource.credentials['SESSION_TOKEN']
    )
    
    response = client.get_resources(
        restApiId= resource.apiId
    )
    
    for item in response['items']:
        if item['path'] == resource.apiPath:
            resource.methodId = item['id']
            
def trimProtocol(resource):
    domain = resource.domain
    domain = domain.replace("https://","")
    resource.domain = domain

def parseDomain(resource):
    domain = resource.domain
    idSplit = domain.split(".")
    resource.apiId = idSplit[0]
    
    pathSplit = domain.split('/')
    pathSplit = pathSplit[2:]
    resource.apiPath = "/" + "/".join(pathSplit)

def getIntegration(resource):
    
    client = boto3.client('apigateway',
        aws_access_key_id=resource.credentials['ACCESS_KEY'],
        aws_secret_access_key=resource.credentials['SECRET_KEY'],
        aws_session_token=resource.credentials['SESSION_TOKEN']
    )
    
    response = client.get_integration(
        restApiId=resource.apiId,
        resourceId=resource.methodId,
        httpMethod=resource.httpMethod
    )
    lambdaUri = response['uri']
    lambdaUri = lambdaUri.split("/functions/")
    lambdaArn = lambdaUri[1:]
    lambdaArn = "/functions/".join(lambdaArn)
    resource.lambdaArn = lambdaArn[:-12]
    print(lambdaArn)
    
def getLambdaCode(resource):
    
    client = boto3.client('lambda',
        aws_access_key_id=resource.credentials['ACCESS_KEY'],
        aws_secret_access_key=resource.credentials['SECRET_KEY'],
        aws_session_token=resource.credentials['SESSION_TOKEN']
    )
    
    response = client.get_function(
        FunctionName= resource.lambdaArn
    )
    resource.msg = response['Code']['Location']
    
def AssumeRole(roleArn):
    sts_connection = boto3.client('sts')
    acct_b = sts_connection.assume_role(
        RoleArn=roleArn,
        RoleSessionName="cross_acct_lambda"
    )
    credentials = {
        'ACCESS_KEY': acct_b['Credentials']['AccessKeyId'],
        'SECRET_KEY': acct_b['Credentials']['SecretAccessKey'],
        'SESSION_TOKEN' : acct_b['Credentials']['SessionToken']
    }
    return credentials   