import os
import sys

# Add project root to sys.path so 'core' and other modules are found
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from core.friday import FridayCore
from core.config import Config
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
friday = FridayCore()

# Setup workspace directory for user files and Friday's created files
WORKSPACE_DIR = os.path.abspath("workspace")
os.makedirs(WORKSPACE_DIR, exist_ok=True)

@app.route('/ask', methods=['POST'])
def ask():
    data = request.json
    if not data or 'message' not in data:
        return jsonify({"error": "No message provided"}), 400
    
    user_message = data['message']
    
    # Process message through Friday's core (this handles web searches, tool calls, and file creation)
    response, metadata = friday.process_message(user_message)
    
    result = {
        "response": response,
        "model": friday.brain.current_model if hasattr(friday.brain, 'current_model') else "NVIDIA API"
    }
    
    if metadata:
        result["metadata"] = metadata
        
    return jsonify(result)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    if file:
        filename = secure_filename(file.filename)
        file_path = os.path.join(WORKSPACE_DIR, filename)
        file.save(file_path)
        
        # Optionally tell Friday about the upload
        if request.form.get('analyze', 'false').lower() == 'true':
            response = friday.process_message(f"I have uploaded a file named {filename} at path: {file_path}. Please analyze it or take note.")
            return jsonify({"message": f"File {filename} uploaded successfully", "path": file_path, "friday_response": response})
            
        return jsonify({"message": f"File {filename} uploaded successfully", "path": file_path})

@app.route('/files', methods=['GET'])
def list_files():
    """List all files in the workspace (user uploads + Friday creations)."""
    try:
        files = os.listdir(WORKSPACE_DIR)
        return jsonify({"files": files, "workspace_path": WORKSPACE_DIR})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download/<path:filename>', methods=['GET'])
def download_file(filename):
    """Download a specific file from the workspace."""
    try:
        return send_from_directory(WORKSPACE_DIR, filename, as_attachment=True)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404

@app.route('/history', methods=['GET'])
def history():
    limit = request.args.get('limit', default=50, type=int)
    history_data = friday.db.get_conversation_history(limit=limit)
    return jsonify({"history": history_data})

@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        "status": "online",
        "name": "Friday AI API",
        "workspace": WORKSPACE_DIR
    })

@app.route('/', methods=['GET'])
def index():
    """Welcome page with available routes."""
    return jsonify({
        "message": "Friday AI Backend is Online",
        "endpoints": {
            "ask": "/ask (POST)",
            "upload": "/upload (POST)",
            "list_files": "/files (GET)",
            "download": "/download/<filename> (GET)",
            "status": "/status (GET)",
            "history": "/history (GET)"
        },
        "version": "1.0.0"
    })

if __name__ == "__main__":
    # We use 0.0.0.0 so it can be accessed within the local network
    app.run(host='0.0.0.0', port=5000)

