import time
import json
import argparse
import AWSIoTPythonSDK.MQTTLib as AWSIoTPyMQTT

# 引数の解析
parser = argparse.ArgumentParser()
parser.add_argument("--endpoint", required=True, help="AWS IoT Core endpoint")
parser.add_argument("--cert", required=True, help="Path to certificate file")
parser.add_argument("--key", required=True, help="Path to private key file")
parser.add_argument("--ca", required=True, help="Path to CA certificate file (rootCA.pem)")
parser.add_argument("--device-id", required=True, help="Device ID (used as client ID)")
args = parser.parse_args()

# MQTT クライアントの設定
client_id = args.device_id
mqtt_client = AWSIoTPyMQTT.AWSIoTMQTTClient(client_id)
mqtt_client.configureEndpoint(args.endpoint, 8883)
mqtt_client.configureCredentials(args.ca, args.key, args.cert)

# MQTT 接続パラメータの設定
mqtt_client.configureAutoReconnectBackoffTime(1, 32, 20)
mqtt_client.configureOfflinePublishQueueing(-1)
mqtt_client.configureDrainingFrequency(2)
mqtt_client.configureConnectDisconnectTimeout(10)
mqtt_client.configureMQTTOperationTimeout(5)

# 接続コールバック関数
def simple_on_online_callback():
    print("Client is online.")

# onOnlineイベントに関数を割り当て（接続成功時に呼び出される）
mqtt_client.onOnline = simple_on_online_callback

# 接続試行
print(f"Attempting to connect to AWS IoT Core as device {args.device_id}...")
try:
    if mqtt_client.connect(10): # 接続タイムアウト10秒
        print("Connection successful.")
        # メッセージ発行
        topic = f"devices/{args.device_id}/status"
        message = {
            "message": f"Hello from device {args.device_id}",
            "timestamp": time.time()
        }
        print(f"Publishing message to topic: {topic}")
        mqtt_client.publish(topic, json.dumps(message), 1) # QoS 1

        # メッセージが送信され、コールバックが処理されるのを少し待つ
        # 実際のアプリケーションではこのような固定待機ではなく、適切なイベント処理を行う
        time.sleep(5)
        print("Disconnecting...")
        mqtt_client.disconnect()
        print("Disconnected.")
    else:
        # connect()がFalseを返した場合 (タイムアウトまたは即時接続失敗)
        print("Connect attempt failed or timed out.")
except Exception as e:
    print(f"An error occurred: {str(e)}")