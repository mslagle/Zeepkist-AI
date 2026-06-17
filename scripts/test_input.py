import socket
import struct
import json
import time

def send_input(steering=0.0, brake=0.0, arms=0.0, reset=False, request_ghost=False, port=9091):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    host = '127.0.0.1'
    
    header = struct.pack('<fffBB', float(steering), float(brake), float(arms), 1 if reset else 0, 1 if request_ghost else 0)
    msg = header + json.dumps({"p": [[0,0,0]]*4, "t": 0.0}).encode('utf-8')
    sock.sendto(msg, (host, port))
    print(f"Sent: Steer={steering}, Brake={brake}, Arms={arms}, Reset={reset}, RequestGhost={request_ghost}")
    sock.close()

if __name__ == "__main__":
    print("Zeepkist AI Input Tester")
    print("1. Steering Left")
    send_input(steering=-1.0)
    time.sleep(1)
    
    print("2. Steering Right")
    send_input(steering=1.0)
    time.sleep(1)
    
    print("3. Neutral")
    send_input(steering=0.0)
