## About
This function will return the source files for the lambda function of any ApiGateway endpoint which has been publically exposed.

## How to use
1.  Inspect the element of the page with the API endpoint

2.  Launch the template on your AWS account

3.  Replace the environment variable values with the endpoint URL, the http method (eg. POST, PUT etc.), and the IAM Role Arn provided by the developer 

4.  Test the function, and it will return the s3 url with the lambda zip file!

P.S. This code can work for any publically exposed lambda, as long as the developer gives you the IAM Role Arn to read their resources! If you'd like help implementing this on your own account, email me: andy@sourcereports.com

## To verify Source Reports
* Deploy and run as is

   * This will show the code of the API Gateway checker. You can be sure that the online checker is working as advertised. 

* Change the DOMAIN environment variable from https://rr459muydl.execute-api.us-east-1.amazonaws.com/prod/gateway to https://rr459muydl.execute-api.us-east-1.amazonaws.com/prod/checker

   * This will show the code of the pipeline checker. Now you can be sure the pipeline checker is working as advertised as well!

