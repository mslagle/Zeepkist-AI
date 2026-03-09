import socket
import json
import time

def send_input(steering=0.0, acceleration=0.0, brake=False, reset=False, port=9091):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    host = '127.0.0.1'
    
    input_data = {
        "Steering": float(steering),
        "Acceleration": float(acceleration),
        "Brake": bool(brake),
        "Reset": bool(reset)
    }
    
    msg = json.dumps(input_data).encode('utf-8')
    sock.sendto(msg, (host, port))
    print(f"Sent: {input_data}")
    sock.close()

if __name__ == "__main__":
    print("Zeepkist AI Input Tester")
    print("1. Steering Left")
    send_input(steering=-1.0, acceleration=1.0)
    time.sleep(1)
    
    print("2. Steering Right")
    send_input(steering=1.0, acceleration=1.0)
    time.sleep(1)
    
    print("3. Neutral")
    send_input(steering=0.0, acceleration=0.0)
