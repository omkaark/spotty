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
        apps=state_manager.get_apps(),
        total_cost=state_manager.get_total_cost()
    )

@app.route('/add_app', methods=['POST'])
def add_app():
    app_name = request.form['app_name']
    ecr_uri = request.form['ecr_uri']
    if state_manager.add_app(app_name, ecr_uri):
        return jsonify(success=True)
    else:
        return jsonify(error="App already exists"), 400

@app.route('/update_ecr_uri', methods=['POST'])
def update_ecr_uri():
    app_name = request.form['app_name']
    ecr_uri = request.form['ecr_uri']
    if state_manager.update_ecr_uri(app_name, ecr_uri):
        return jsonify(success=True)
    else:
        return jsonify(error="App not found"), 404

@app.route('/scale_up/<app_name>')
def scale_up(app_name):
    app = state_manager.get_app(app_name)
    if not app:
        return jsonify(error="App not found"), 404
    
    usage, quota = check_spot_quotas()
    if quota != "Unknown" and usage >= quota:
        cleanup_spot_requests()  # clean up any lingering requests
        return jsonify(error="Spot Instance quota reached. Please try again later or request a quota increase."), 429
    
    instance_counter = state_manager.get_instance_counter(app_name)
    instance_name = f"{app_name}-{instance_counter + 1}"
    env_vars = state_manager.get_env_vars(app_name)
    instance_dict = create_instance(app['ecr_image_uri'], instance_name, env_vars)
    if instance_dict and instance_dict['id']:
        state_manager.add_instance(app_name, instance_dict)
        return jsonify(success=True, instance=instance_dict)
    else:
        return jsonify(success=False, error="Failed to create instance. Please check logs for more details."), 500

@app.route('/cleanup')
def cleanup():
    cleanup_spot_requests()
    return jsonify(success=True, message="Cleanup completed")

@app.route('/delete_instance/<app_name>/<instance_id>')
def delete_instance(app_name, instance_id):
    if state_manager.remove_instance(app_name, instance_id):
        terminate_instance(instance_id)
        return jsonify(success=True, terminated_instance_id=instance_id)
    else:
        return jsonify(error="Instance not found"), 404

@app.route('/instances/<app_name>')
def get_instances(app_name):
    return jsonify(instances=state_manager.get_instances(app_name))

@app.route('/instance_stats/<instance_id>')
def instance_stats(instance_id):
    for app in state_manager.get_apps().values():
        instance = next((inst for inst in app['instances'] if inst['id'] == instance_id), None)
        if instance:
            try:
                response = requests.get(f"http://{instance['ip']}:3928/stats", timeout=5)
                return jsonify(response.json())
            except requests.RequestException as e:
                return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Instance not found"}), 404

@app.route('/get_env_vars/<app_name>')
def get_env_vars(app_name):
    try:
        env_vars = state_manager.get_env_vars(app_name)
        return jsonify(env_vars=env_vars)
    except ValueError as e:
        return jsonify(error=str(e)), 404

@app.route('/save_env_vars/<app_name>', methods=['POST'])
def save_env_vars(app_name):
    env_vars = request.json
    try:
        state_manager.save_env_vars(app_name, env_vars)
        return jsonify(success=True)
    except ValueError as e:
        return jsonify(error=str(e)), 404

if __name__ == '__main__':
    if os.getenv('TF_INSTANCE_PROFILE_NAME'):
        app.run(host='0.0.0.0', port=8090)
    else:
        logger.warning("TF_INSTANCE_PROFILE_NAME environment variable is not set. The application may not function correctly.")