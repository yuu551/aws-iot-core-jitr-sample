import boto3
import json
import os
import logging
from OpenSSL import crypto
import datetime

# ロガーの設定
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS SDKクライアント
iot_client = boto3.client('iot')
dynamodb = boto3.resource('dynamodb')
# 環境変数からDynamoDBテーブル名を取得
device_table_name = os.environ['DEVICE_WHITELIST_TABLE']
device_table = dynamodb.Table(device_table_name)

def lambda_handler(event, context):
    """
    JITR証明書登録イベントを処理するLambda関数
    """
    logger.info(f"Received event: {json.dumps(event)}")
    
    # 証明書IDを取得
    certificate_id = event['certificateId']
    logger.info(f"Processing certificate ID: {certificate_id}")
    
    try:
        # AWS IoT Coreから証明書情報を取得
        response = iot_client.describe_certificate(
            certificateId=certificate_id
        )
        
        certificate_pem = response['certificateDescription']['certificatePem']
        certificate_arn = response['certificateDescription']['certificateArn']
        
        # 証明書からデバイスIDを抽出
        device_id = extract_device_id_from_certificate(certificate_pem)
        logger.info(f"Extracted device ID: {device_id}")
        
        # DynamoDBでデバイスIDの有効性を確認
        device_response = device_table.get_item(
            Key={
                'DeviceId': device_id
            }
        )
        
        # デバイスがホワイトリストに存在するか確認
        if 'Item' in device_response:
            # デバイスが有効なので証明書をアクティブ化
            iot_client.update_certificate(
                certificateId=certificate_id,
                newStatus='ACTIVE'
            )
            
            # デバイス用のIoTポリシーを作成して付与
            policy_name = f"DevicePolicy_{device_id}"
            create_and_attach_policy(policy_name, certificate_arn, device_id) # device_id を渡す
            
            # モノを登録して証明書と関連付け
            thing_name = f"Device_{device_id}"
            register_thing(thing_name, certificate_arn)
            
            logger.info(f"Successfully registered device {device_id}")
            return {
                'statusCode': 200,
                'body': f"Device {device_id} successfully registered"
            }
        else:
            # デバイスが無効なので証明書を無効化
            iot_client.update_certificate(
                certificateId=certificate_id,
                newStatus='REVOKED'
            )
            
            logger.warning(f"Device {device_id} not found in whitelist. Certificate revoked.")
            return {
                'statusCode': 403,
                'body': f"Device {device_id} is not authorized"
            }
            
    except Exception as e:
        logger.error(f"Error processing certificate: {str(e)}")
        # エラー発生時も証明書を無効化する
        try:
            iot_client.update_certificate(
                certificateId=certificate_id,
                newStatus='REVOKED'
            )
            logger.info(f"Certificate {certificate_id} revoked due to processing error.")
        except Exception as rev_err:
            logger.error(f"Failed to revoke certificate {certificate_id} after error: {str(rev_err)}")
            
        return {
            'statusCode': 500,
            'body': f"Error: {str(e)}"
        }

def extract_device_id_from_certificate(cert_pem):
    """証明書からデバイスIDを抽出する関数"""
    try:
        x509 = crypto.load_certificate(crypto.FILETYPE_PEM, cert_pem)
        subject = x509.get_subject()
        components = dict(subject.get_components())
        
        if b'serialNumber' in components:
            return components[b'serialNumber'].decode('utf-8')
        if b'CN' in components: # Common Name をフォールバックとして使用
            return components[b'CN'].decode('utf-8')
        
        raise ValueError("No device ID (serialNumber or CN) found in certificate subject")
    except Exception as e:
        logger.error(f"Error extracting device ID: {str(e)}")
        raise

def create_and_attach_policy(policy_name, certificate_arn, device_id): # device_id を引数に追加
    """IoTポリシーを作成して証明書に付与する関数"""
    # Lambda実行リージョンとアカウントIDを動的に取得
    region = os.environ['AWS_REGION']
    account_id = boto3.client('sts').get_caller_identity()['Account']


    try:
        try:
            iot_client.get_policy(policyName=policy_name)
            logger.info(f"Policy {policy_name} already exists")
        except iot_client.exceptions.ResourceNotFoundException:
            logger.info(f"Creating new policy: {policy_name}")
            policy_document = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["iot:Connect"],
                        "Resource": [f"arn:aws:iot:{region}:{account_id}:client/{device_id}"] # Client ID を device_id に制限
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["iot:Publish", "iot:Receive"],
                        "Resource": [f"arn:aws:iot:{region}:{account_id}:topic/devices/{device_id}/*"] # トピックを device_id に制限
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["iot:Subscribe"],
                        "Resource": [f"arn:aws:iot:{region}:{account_id}:topicfilter/devices/{device_id}/*"] # トピックフィルターを device_id に制限
                    }
                ]
            }
            
            iot_client.create_policy(
                policyName=policy_name,
                policyDocument=json.dumps(policy_document)
            )
        
        iot_client.attach_policy(
            policyName=policy_name,
            target=certificate_arn
        )
        logger.info(f"Policy {policy_name} attached to certificate")
    except Exception as e:
        logger.error(f"Error creating/attaching policy: {str(e)}")
        raise

def register_thing(thing_name, certificate_arn):
    """モノを登録して証明書に関連付ける関数"""
    try:
        try:
            iot_client.describe_thing(thingName=thing_name)
            logger.info(f"Thing {thing_name} already exists")
        except iot_client.exceptions.ResourceNotFoundException:
            logger.info(f"Creating new thing: {thing_name}")
            iot_client.create_thing(
                thingName=thing_name,
                attributePayload={
                    'attributes': {
                        'source': 'jitr_registration',
                        'registration_date': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ') # 修正: ISO 8601 形式の現在時刻
                    }
                }
            )
        
        iot_client.attach_thing_principal(
            thingName=thing_name,
            principal=certificate_arn
        )
        logger.info(f"Certificate attached to thing {thing_name}")
    except Exception as e:
        logger.error(f"Error registering thing: {str(e)}")
        raise 