import uvicorn
import socket
from app.config import get_settings

def get_local_ip():
    try:
        # Create a dummy socket to find the local IP address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    settings = get_settings()
    host = settings.app_host
    port = settings.app_port
    
    local_ip = get_local_ip()
    
    print("╔" + "═" * 50 + "╗")
    print("║" + " " * 18 + "CAMPUS EYE STARTING" + " " * 13 + "║")
    print("╚" + "═" * 50 + "╝")
    print(f"▸ Host: {host}")
    print(f"▸ Port: {port}")
    print(f"▸ Local Network Access: http://{local_ip}:{port}")
    print(" " * 52)
    print("Starting server...")
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True
    )
