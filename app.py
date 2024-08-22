import os
import signal
import sys
from flask import Flask, render_template, request, jsonify, send_file
from flask_cors import CORS
from aws_utils import check_spot_quotas, cleanup_spot_requests
from ec2_spot import create_instance, terminate_instance
from state_manager import StateManager
from logging_config import logger
import requests

app = Flask(__name__)
CORS(app)

state_manager = StateManager()

def signal_handler(sig, frame):
    logger.info("\nCleaning up spot requests before exiting...")
    cleanup_spot_requests()
    logger.info("Cleanup completed. Exiting.")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

@app.route('/')
def index():
    if os.getenv('ENVIRONMENT', 'DEVELOPMENT') == 'PRODUCTION':
        return render_template('index.html')
    else:
        return send_file('templates/index.html')

@app.route('/get_state')
def api():
    return jsonify(
        ecr_image_uri=state_manager.get_ecr_image_uri(),
        instance_prefix=state_manager.get_instance_prefix(),
        instances=state_manager.get_instances(),
        total_cost=state_manager.get_total_cost()
    )

@app.route('/set_ecr_uri_and_prefix', methods=['POST'])
def set_ecr_uri_and_prefix():
    ecr_uri = request.form['ecr_uri']
    instance_prefix = request.form['instance_prefix']
    state_manager.update_ecr_uri_and_prefix(ecr_uri, instance_prefix)
    return jsonify(success=True)

@app.route('/scale_up')
def scale_up():
    if not state_manager.get_ecr_image_uri() or not state_manager.get_instance_prefix():
        return jsonify(error="ECR URI or Instance Prefix not set"), 400
    
    usage, quota = check_spot_quotas()
    if quota != "Unknown" and usage >= quota:
        cleanup_spot_requests()  # clean up any lingering requests
        return jsonify(error="Spot Instance quota reached. Please try again later or request a quota increase."), 429
    
    instance_counter = state_manager.get_instance_counter()
    instance_name = f"{state_manager.get_instance_prefix()}-{instance_counter + 1}"
    env_vars = state_manager.get_env_vars()
    instance_dict = create_instance(state_manager.get_ecr_image_uri(), instance_name, env_vars)
    if instance_dict and instance_dict['id']:
        state_manager.add_instance(instance_dict)
        return jsonify(success=True, instance=instance_dict)
    else:
        return jsonify(success=False, error="Failed to create instance. Please check logs for more details."), 500

@app.route('/cleanup')
def cleanup():
    cleanup_spot_requests()
    return jsonify(success=True, message="Cleanup completed")

@app.route('/delete_instance/<instance_id>')
def delete_instance(instance_id):
    if state_manager.remove_instance(instance_id):
        terminate_instance(instance_id)
        return jsonify(success=True, terminated_instance_id=instance_id)
    else:
        return jsonify(error="Instance not found"), 404

@app.route('/instances')
def get_instances():
    return jsonify(instances=state_manager.get_instances())

@app.route('/instance_stats/<instance_id>')
def instance_stats(instance_id):
    instance = next((inst for inst in state_manager.get_instances() if inst['id'] == instance_id), None)
    if not instance:
        return jsonify({"error": "Instance not found"}), 404
    
    try:
        response = requests.get(f"http://{instance['ip']}:3928/stats", timeout=5)
        return jsonify(response.json())
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get_env_vars')
def get_env_vars():
    env_vars = state_manager.get_env_vars()
    return jsonify(env_vars=env_vars)

@app.route('/save_env_vars', methods=['POST'])
def save_env_vars():
    env_vars = request.json
    state_manager.save_env_vars(env_vars)
    return jsonify(success=True)

if __name__ == '__main__':
    if os.getenv('TF_INSTANCE_PROFILE_NAME'):
        app.run(host='0.0.0.0', port=8090)
    else:
        logger.warning("TF_INSTANCE_PROFILE_NAME environment variable is not set. The application may not function correctly.")