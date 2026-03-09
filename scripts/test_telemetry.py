import socket
import json

def test_telemetry(port=9090):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', port))
    sock.settimeout(10.0)
    
    print(f"Listening for telemetry on port {port}...")
    try:
        data, addr = sock.recvfrom(4096)
        print(f"Received data from {addr}:")
        telemetry = json.loads(data.decode('utf-8'))
        print(json.dumps(telemetry, indent=2))
    except socket.timeout:
        print("Timed out waiting for telemetry. Is the game running and AI mod enabled?")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    test_telemetry()
