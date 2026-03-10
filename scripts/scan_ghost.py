import lzma
import struct
import os
import io

def scan_ghost(file_path):
    with open(file_path, 'rb') as f:
        raw_data = f.read()
    
    if raw_data.startswith(b'\x5d\x00\x00'):
        decompressed = lzma.decompress(raw_data, format=lzma.FORMAT_ALONE)
        print(f"Decompressed size: {len(decompressed)}")
        
        # Scan for sequences of floats
        # Most ghosts will have at least 3 floats (XYZ) that are reasonable
        for i in range(len(decompressed) - 12):
            try:
                x, y, z = struct.unpack('<fff', decompressed[i:i+12])
                # reasonable world coords for Zeepkist
                if all(-2000 < val < 5000 for val in [x, y, z]) and any(abs(val) > 1.0 for val in [x,y,z]):
                    # Check if there are more floats following
                    # Maybe a quaternion? (4 floats)
                    if i + 28 <= len(decompressed):
                        rx, ry, rz, rw = struct.unpack('<ffff', decompressed[i+12:i+28])
                        if all(-1.1 <= val <= 1.1 for val in [rx, ry, rz, rw]):
                            print(f"Potential Frame start at offset {i}:")
                            print(f"  Pos: ({x:.2f}, {y:.2f}, {z:.2f})")
                            print(f"  Rot: ({rx:.2f}, {ry:.2f}, {rz:.2f}, {rw:.2f})")
                            
                            # Check the next frame at +28 or +32
                            for stride in [28, 32, 36]:
                                if i + stride + 12 <= len(decompressed):
                                    nx, ny, nz = struct.unpack('<fff', decompressed[i+stride:i+stride+12])
                                    if abs(nx-x) < 10 and abs(ny-y) < 10:
                                        print(f"  Confirmed Stride: {stride} (Next X: {nx:.2f})")
                                        break
            except:
                continue

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ghost_path = os.path.join(script_dir, "ghosts", "ea1.zeepghost")
    scan_ghost(ghost_path)
