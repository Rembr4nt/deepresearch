#!/usr/bin/env python3
"""
Deep Research Web Interface Startup Script

This script provides an easy way to start the Deep Research web interface
with proper configuration and error handling.
"""

import os
import sys
import argparse
import logging
from pathlib import Path

os.environ.setdefault("TOGETHER_NO_BANNER", "1")  # the 1.x SDK prints an upgrade banner on import

# Add the parent directory to Python path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Look for .env file in project root (parent of web_interface)
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        print(f"📄 Loaded .env file from: {env_path}")
    else:
        print(f"⚠️  No .env file found at: {env_path}")
        print("📄 Looking for .env in current directory...")
        if Path('.env').exists():
            load_dotenv('.env')
            print("📄 Loaded .env from current directory")
        else:
            print("⚠️  No .env file found in current directory either")
except ImportError:
    print("⚠️  python-dotenv not available, skipping .env file loading")

def check_dependencies():
    """Check if all required dependencies are installed"""
    required_packages = [
        'fastapi', 'uvicorn', 'websockets', 'pydantic', 
        'dotenv', 'yaml', 'together', 'voyageai', 'tavily', 'tiktoken'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("❌ Missing required packages:")
        for package in missing_packages:
            print(f"  - {package}")
        print("\nInstall them with:")
        print(f"pip install {' '.join(missing_packages)}")
        print("\nOr install all requirements:")
        print("pip install -r requirements.txt   # from the project root")
        return False
    
    return True

def check_api_keys():
    """Check if required API keys are set"""
    required_keys = ['TOGETHER_API_KEY', 'VOYAGE_API_KEY', 'TAVILY_API_KEY']
    missing_keys = []
    
    print(f"🔍 Checking API keys in environment...")
    for key in required_keys:
        value = os.getenv(key)
        if not value:
            missing_keys.append(key)
        else:
            print(f"  ✅ {key}: set")
    
    if missing_keys:
        print("❌ Missing required API keys:")
        for key in missing_keys:
            print(f"  - {key}")
        print(f"\nCreate a .env file in the project root ({Path(__file__).parent.parent}) with:")
        for key in missing_keys:
            print(f"{key}=your_api_key_here")
        return False
    
    return True

def main():
    parser = argparse.ArgumentParser(
        description="Start the Deep Research Web Interface",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python start_server.py                    # Start with default settings
  python start_server.py --port 8080       # Start on port 8080
  python start_server.py --host 0.0.0.0    # Allow external connections
  python start_server.py --dev             # Development mode with auto-reload
        """
    )
    
    parser.add_argument('--host', default='127.0.0.1', 
                       help='Host to bind the server (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8000,
                       help='Port to bind the server (default: 8000)')
    parser.add_argument('--dev', action='store_true',
                       help='Enable development mode with auto-reload')
    parser.add_argument('--log-level', default='info',
                       choices=['debug', 'info', 'warning', 'error'],
                       help='Set logging level (default: info)')
    parser.add_argument('--check-only', action='store_true',
                       help='Only check dependencies and exit')
    
    args = parser.parse_args()
    
    print("🧠 Deep Research Web Interface Startup")
    print("=" * 50)
    
    # Check dependencies
    print("🔍 Checking dependencies...")
    if not check_dependencies():
        sys.exit(1)
    print("✅ All dependencies found")
    
    # Check API keys
    print("🔑 Checking API keys...")
    if not check_api_keys():
        sys.exit(1)
    print("✅ All API keys configured")
    
    if args.check_only:
        print("✅ All checks passed! Ready to start server.")
        sys.exit(0)
    
    # Import uvicorn after dependency check
    try:
        import uvicorn
    except ImportError:
        print("❌ uvicorn not found. Install with: pip install uvicorn[standard]")
        sys.exit(1)
    
    # Set environment for development
    if args.dev:
        os.environ['WEB_ENVIRONMENT'] = 'development'
        print("🔧 Development mode enabled")
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print(f"🚀 Starting server on http://{args.host}:{args.port}")
    print("📊 Access the web interface in your browser")
    print("⚠️  Press Ctrl+C to stop the server")
    print()
    
    try:
        # Start the server
        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port,
            reload=args.dev,
            log_level=args.log_level,
            workers=1,  # sessions live in memory, so one process only
            access_log=True
        )
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()