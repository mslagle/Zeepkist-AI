import lzma
import struct
import os

def debug_ghost(file_path):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    with open(file_path, 'rb') as f:
        raw_data = f.read()
    
    print(f"File size: {len(raw_data)}")
    if raw_data.startswith(b'\x5d\x00\x00'):
        print("Detected LZMA")
        try:
            decompressed = lzma.decompress(raw_data, format=lzma.FORMAT_ALONE)
            print(f"Decompressed size: {len(decompressed)}")
            
            # Dump first 512 bytes hex
            hex_dump = " ".join(f"{b:02X}" for b in decompressed[:512])
            print(f"Raw hex dump (first 512 bytes):\n{hex_dump}")
            
            # String search
            import re
            strings = re.findall(b"[a-zA-Z0-9_\-\.]{3,}", decompressed[:1024])
            print(f"Recognizable strings in first 1024 bytes: {strings}")
            
        except Exception as e:
            print(f"Decompression error: {e}")

if __name__ == "__main__":
    # Get script dir
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ghost_path = os.path.join(script_dir, "ghosts", "ea1.zeepghost")
    debug_ghost(ghost_path)
