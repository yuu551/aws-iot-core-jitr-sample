import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iot from 'aws-cdk-lib/aws-iot';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as path from 'path';
import * as cr from 'aws-cdk-lib/custom-resources';

export class AwsIotJitrLambdaCdkStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const deviceWhitelistTable = new dynamodb.Table(this, 'DeviceWhitelistTable', {
      tableName: 'DeviceWhitelist',
      partitionKey: { name: 'DeviceId', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const certificateValidatorLambda = new lambda.Function(this, 'IoTCertificateValidatorFunction', {
      functionName: 'IoTCertificateValidator',
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'handler.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '..', 'lambda', 'IoTCertificateValidator'), {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output'
          ],
        },
      }),
      environment: {
        DEVICE_WHITELIST_TABLE: deviceWhitelistTable.tableName,
      },
      timeout: cdk.Duration.seconds(30), // タイムアウトを適宜設定
      memorySize: 256, // メモリサイズを適宜設定,
      architecture: lambda.Architecture.ARM_64,
    });


    deviceWhitelistTable.grantReadData(certificateValidatorLambda);

    certificateValidatorLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: [
        'iot:DescribeCertificate',
        'iot:UpdateCertificate',
        'iot:CreatePolicy',
        'iot:AttachPolicy',
        'iot:GetPolicy', 
        'iot:CreateThing',
        'iot:DescribeThing',
        'iot:AttachThingPrincipal',
      ],
      resources: ['*'],
    }));


    const certificateRegistrationRule = new iot.CfnTopicRule(this, 'CertificateRegistrationRule', {
      ruleName: 'CertificateRegistrationRule',
      topicRulePayload: {
        sql: "SELECT * FROM '$aws/events/certificates/registered/#'",
        actions: [{
          lambda: {
            functionArn: certificateValidatorLambda.functionArn,
          },
        }],
        ruleDisabled: false,
        awsIotSqlVersion: '2016-03-23',
        description: 'Triggers a Lambda function when a certificate is registered using JITR.',
      },
    });

    certificateValidatorLambda.addPermission('IoTRulePermission', {
      principal: new iam.ServicePrincipal('iot.amazonaws.com'),
      sourceArn: certificateRegistrationRule.attrArn,
    });

    new cr.AwsCustomResource(this, 'InitDeviceWhitelistData', {
      onCreate: {
        service: 'DynamoDB',
        action: 'putItem',
        parameters: {
          TableName: deviceWhitelistTable.tableName,
          Item: {
            DeviceId: { S: 'DEVICE123456' },
            Status: { S: 'ACTIVE' },
            Description: { S: 'Test Device' },
          },
        },
        physicalResourceId: cr.PhysicalResourceId.of('InitDeviceWhitelistData'),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ['dynamodb:PutItem'],
          resources: [deviceWhitelistTable.tableArn],
        }),
      ]),
    });
  }
}

