import socket
import struct

def test_telemetry(port=9090):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', port))
    sock.settimeout(10.0)
    
    print(f"Listening for telemetry on port {port}...")
    try:
        data, addr = sock.recvfrom(8192)
        print(f"Received {len(data)} bytes from {addr}")
        
        # Parse first 56 bytes: Time (f), Position (3f), Rotation (4f), Velocity (3f), AngVel (3f)
        header = struct.unpack('<ffffffffffffff', data[:56])
        print("Parsed initial telemetry values:")
        print(f"  Time: {header[0]:.2f}")
        print(f"  Pos: ({header[1]:.2f}, {header[2]:.2f}, {header[3]:.2f})")
        print(f"  Rot: ({header[4]:.2f}, {header[5]:.2f}, {header[6]:.2f}, {header[7]:.2f})")
        print(f"  Vel: ({header[8]:.2f}, {header[9]:.2f}, {header[10]:.2f})")
        print(f"  AngVel: ({header[11]:.2f}, {header[12]:.2f}, {header[13]:.2f})")
    except socket.timeout:
        print("Timed out waiting for telemetry. Is the game running and AI mod enabled?")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    test_telemetry()
