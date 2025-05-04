import os
import json
import boto3
import logging
from datetime import datetime

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize DynamoDB client
table_name = os.environ['TABLE_NAME']
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(table_name)

# Initialize API Gateway Management API client
api_id = os.environ['API_ID']
stage = os.environ['STAGE']
region = os.environ['REGION']
endpoint_url = f'https://{api_id}.execute-api.{region}.amazonaws.com/{stage}'
api_client = boto3.client('apigatewaymanagementapi', endpoint_url=endpoint_url)


def lambda_handler(event, context):
    """
    Handles WebSocket events: $connect, $disconnect, and $default for echo testing
    """
    connection_id = event['requestContext']['connectionId']
    route_key = event['requestContext']['routeKey']

    logger.info(f"Received {route_key} event from connection: {connection_id}")

    try:
        # Handle connection
        if route_key == '$connect':
            # Store connection ID and metadata in DynamoDB
            connection_item = {
                'connectionId': connection_id,
                'connected_at': datetime.now().isoformat(),
                'ip': event['requestContext'].get('identity', {}).get('sourceIp', 'unknown'),
                'status': 'CONNECTED'
            }
            table.put_item(Item=connection_item)
            logger.info(f"Stored new connection: {connection_id}")
            return {'statusCode': 200, 'body': 'Connected successfully'}

        # Handle disconnection
        elif route_key == '$disconnect':
            # Remove connection from DynamoDB
            table.delete_item(Key={'connectionId': connection_id})
            logger.info(f"Removed disconnected connection: {connection_id}")
            return {'statusCode': 200, 'body': 'Disconnected'}

        # Handle default route (echo for testing)
        elif route_key == '$default':
            # Echo the message back to the client
            message = 'No message received'
            if 'body' in event:
                try:
                    body = json.loads(event['body'])
                    message = body.get('message', 'No message received')
                except json.JSONDecodeError:
                    message = event['body']

            # Send echo response
            response_message = {
                'message': f"Echo: {message}",
                'timestamp': datetime.now().isoformat()
            }
            send_to_connection(connection_id, response_message)
            logger.info(f"Sent echo response to {connection_id}")
            return {'statusCode': 200, 'body': 'Message sent'}

        else:
            logger.warning(f"Unknown route: {route_key}")
            return {'statusCode': 400, 'body': 'Unknown route'}

    except Exception as e:
        logger.error(f"Error processing {route_key} event: {str(e)}")
        return {'statusCode': 500, 'body': str(e)}


def send_to_connection(connection_id, data):
    """
    Send a message to a WebSocket connection
    """
    try:
        api_client.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(data).encode('utf-8')
        )
        return True
    except api_client.exceptions.GoneException:
        # Connection is no longer available
        logger.info(f"Connection {connection_id} is gone, removing from database")
        table.delete_item(Key={'connectionId': connection_id})
        return False
    except Exception as e:
        logger.error(f"Error sending message to {connection_id}: {str(e)}")
        return False