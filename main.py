#!/usr/bin/env python
import asyncio
import websockets
import json
import base64
import subprocess
import os
import uuid
import logging
import yt_dlp
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Store active connections
active_connections = {}

# Ensure downloads directory exists
os.makedirs('downloads', exist_ok=True)


async def handle_websocket(websocket, path=""):
    """Handle WebSocket connections and messages"""
    # Generate a unique ID for this connection
    connection_id = str(uuid.uuid4())
    client_ip = websocket.remote_address[0]

    logger.info(f"New connection from {client_ip} (ID: {connection_id})")

    # Store connection info
    active_connections[connection_id] = {
        'websocket': websocket,
        'ip': client_ip,
        'user_agent': None,
        'browser_info': None,
        'connected_at': datetime.now().isoformat()
    }

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                action = data.get('action', '')

                logger.info(f"Received {action} action from {connection_id}")

                # Handle registration with browser info
                if action == 'register':
                    await handle_register(connection_id, data)

                # Handle download request
                elif action == 'download':
                    await handle_download(connection_id, data)

                # Handle proxy response
                elif action == 'proxyResponse':
                    await handle_proxy_response(connection_id, data)

                # Handle proxy error
                elif action == 'proxyError':
                    logger.error(f"Proxy error from {connection_id}: {data.get('error')}")

                else:
                    logger.warning(f"Unknown action: {action}")

            except json.JSONDecodeError:
                logger.error(f"Invalid JSON from {connection_id}")

    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"Connection closed for {connection_id}: {e}")

    except Exception as e:
        logger.error(f"Error handling connection {connection_id}: {e}")

    finally:
        # Clean up connection
        if connection_id in active_connections:
            del active_connections[connection_id]
            logger.info(f"Removed connection {connection_id}")


async def handle_register(connection_id, data):
    """Handle registration message with browser information"""
    if connection_id not in active_connections:
        return

    user_info = data.get('userInfo', {})

    # Store browser information
    active_connections[connection_id]['browser_info'] = user_info
    active_connections[connection_id]['user_agent'] = user_info.get('userAgent')

    logger.info(f"Registered browser info for {connection_id}")

    # Send confirmation
    await send_to_connection(connection_id, {
        'action': 'registered',
        'message': 'Browser successfully registered as proxy'
    })


async def handle_download(connection_id, data):
    """Handle download request"""
    video_url = data.get('videoUrl')
    format_option = data.get('format', 'best')

    if not video_url:
        await send_to_connection(connection_id, {
            'action': 'downloadResult',
            'result': {
                'status': 'error',
                'message': 'Missing video URL'
            }
        })
        return

    logger.info(f"Processing download for {video_url}")

    # Process the download request
    result = await process_ytdlp(connection_id, video_url, format_option)

    # Send result back to client
    await send_to_connection(connection_id, {
        'action': 'downloadResult',
        'result': result
    })


async def handle_proxy_response(connection_id, data):
    """Handle proxy response from browser"""
    request_id = data.get('requestId')
    url = data.get('url')
    status = data.get('status')

    logger.info(f"Received proxy response for {url} (status: {status})")

    # In a real implementation, we would store or process this response
    # For this proof of concept, we'll just log it


async def send_to_connection(connection_id, data):
    """Send message to WebSocket connection"""
    if connection_id not in active_connections:
        logger.warning(f"Attempted to send to non-existent connection {connection_id}")
        return False

    try:
        websocket = active_connections[connection_id]['websocket']
        await websocket.send(json.dumps(data))
        return True
    except Exception as e:
        logger.error(f"Error sending to {connection_id}: {e}")
        return False


async def process_ytdlp(connection_id, video_url, format_option=None):
    """Process a video download using yt-dlp with browser fingerprinting"""
    if connection_id not in active_connections:
        return {'status': 'error', 'message': 'Connection lost'}

    connection = active_connections[connection_id]
    user_agent = connection.get('user_agent')

    if not user_agent:
        return {'status': 'error', 'message': 'No user agent available'}

    # Generate a unique download ID
    download_id = f"{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Set up downloads folder
    download_folder = os.path.join(os.getcwd(), 'downloads')
    os.makedirs(download_folder, exist_ok=True)

    try:
        logger.info(f"Processing download for {video_url} with ID {download_id}")

        # Create yt-dlp options using the browser's user agent
        ydl_opts = {
            # 'format': 'best' if not format_option else format_option,
            'outtmpl': os.path.join(download_folder, f"{download_id}.%(ext)s"),
            'noplaylist': True,
            'user_agent': user_agent,
            'quiet': False,
            'no_warnings': False,
            'ignoreerrors': False,
            'verbose': True
        }

        logger.info(f"Using yt-dlp options: {ydl_opts}")

        # Download the video using yt-dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)

        # Determine the output file path
        file_path = os.path.join(download_folder, f"{download_id}.{info.get('ext', 'mp4')}")

        logger.info(f"Download completed: {file_path}")

        return {
            'status': 'success',
            'download_id': download_id,
            'file_path': file_path,
            'message': 'Video downloaded successfully'
        }

    except Exception as e:
        logger.error(f"Error processing download: {str(e)}")
        return {
            'status': 'error',
            'message': str(e)
        }


async def send_proxy_request(connection_id, url, method='GET', headers=None, response_type='text'):
    """Send a proxy request to a browser"""
    request_id = str(uuid.uuid4())

    success = await send_to_connection(connection_id, {
        'action': 'proxyRequest',
        'requestId': request_id,
        'url': url,
        'method': method,
        'headers': headers or {},
        'responseType': response_type
    })

    if not success:
        return None

    # In a real implementation, we would wait for the response
    # This would require some kind of async queue or callback mechanism
    # For this proof of concept, we're just demonstrating the request flow

    return request_id


async def main():
    """Main entry point for the server"""
    host = 'localhost'
    port = 8765

    logger.info(f"Starting WebSocket server on {host}:{port}")

    server = await websockets.serve(handle_websocket, host, port)
    logger.info("Server started")

    # Keep the server running
    await server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")