import lzma
import struct
import os

def debug_ghost(file_path):
    with open(file_path, 'rb') as f:
        raw_data = f.read()
    
    if raw_data.startswith(b'\x5d\x00\x00'):
        data = lzma.decompress(raw_data, format=lzma.FORMAT_ALONE)
        
        # We know a frame is at 1457 (timestamp 0.352)
        start = 1457
        print(f"Inspecting frame data at {start}:")
        
        chunk = data[start:start+100]
        print(f"HEX: {chunk.hex(' ')}")
        
        # Unpack as various types to find the pattern
        print("\nInterpretations:")
        for i in range(0, 40, 4):
            val_f = struct.unpack('<f', chunk[i:i+4])[0]
            val_i = struct.unpack('<i', chunk[i:i+4])[0]
            val_I = struct.unpack('<I', chunk[i:i+4])[0]
            print(f"Offset +{i:2d}: float={val_f:12.6f}, int32={val_i:12d}, uint32={val_I:12d}")

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ghost_path = os.path.join(script_dir, "ghosts", "ea1.zeepghost")
    debug_ghost(ghost_path)
